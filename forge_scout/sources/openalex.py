"""
OpenAlex — 250M+ academic works. Free, no key (a polite email gets you
into the higher-rate "polite pool", which we set in our User-Agent).

We ask for `abstract_inverted_index` and rebuild the abstract client-side.
Full text is rarely available directly; we expose `open_access.oa_url`
when present so the user can decide to grab the PDF.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://api.openalex.org/works"


def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    # OpenAlex search is language-agnostic; we just respect the limit.
    with http_client() as c:
        try:
            r = c.get(API, params={
                "search": query,
                "per-page": min(max(limit, 1), 25),
                "select": "id,title,doi,publication_year,authorships,"
                          "abstract_inverted_index,open_access,primary_location,language",
            })
            r.raise_for_status()
            data = r.json()
        except Exception:
            return out
    for w in data.get("results", []):
        title = (w.get("title") or "").strip()
        if not title:
            continue
        abstract = _rebuild_abstract(w.get("abstract_inverted_index"))
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        oa = (w.get("open_access") or {}).get("oa_url") or ""
        url = oa or w.get("id") or (f"https://doi.org/{doi}" if doi else "")
        primary = w.get("primary_location") or {}
        venue = ((primary.get("source") or {}).get("display_name")) or ""
        year = w.get("publication_year")
        # Authors string (first 3)
        authors = []
        for a in (w.get("authorships") or [])[:3]:
            name = ((a.get("author") or {}).get("display_name")) or ""
            if name:
                authors.append(name)
        meta_line = " · ".join([x for x in [", ".join(authors), str(year) if year else "", venue] if x])
        snippet = (meta_line + "\n" + abstract).strip() if meta_line else abstract
        out.append(SourceResult(
            source="openalex",
            title=title,
            url=url,
            snippet=truncate(snippet, 380),
            lang=(w.get("language") or "").lower() or "",
            kind="academic",
            size_hint=len(abstract),
            extra={
                "doi": doi or None,
                "oa_url": oa,
                "openalex_id": w.get("id"),
                "year": year,
                "venue": venue,
                "authors": authors,
                "abstract": abstract,
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    For academic papers we cannot reliably get the full text without paying or
    scraping publishers. We synthesise a clean markdown stub of all metadata
    + the abstract — already enough material for many concept-extraction passes.
    """
    e = result.extra or {}
    parts = [f"# {result.title}\n"]
    if e.get("authors"):
        parts.append("**Authors:** " + ", ".join(e["authors"]))
    if e.get("year"):
        parts.append(f"**Year:** {e['year']}")
    if e.get("venue"):
        parts.append(f"**Venue:** {e['venue']}")
    if e.get("doi"):
        parts.append(f"**DOI:** [{e['doi']}](https://doi.org/{e['doi']})")
    if e.get("oa_url"):
        parts.append(f"**Open access PDF:** {e['oa_url']}")
    parts.append(f"\n_Source: {result.url}_\n")
    if e.get("abstract"):
        parts.append("\n## Abstract\n\n" + e["abstract"])
    name = "openalex-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    return "\n".join(parts), name


def _rebuild_abstract(inv: dict | None) -> str:
    """OpenAlex stores abstracts as inverted indexes {word: [positions]}."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)
