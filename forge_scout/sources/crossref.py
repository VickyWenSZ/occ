"""
Crossref — DOI metadata for 150M+ scholarly works. Free, no key.
Good for capturing canonical citations and finding venue/year info even
when a paper is paywalled.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://api.crossref.org/works"


def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client() as c:
        try:
            r = c.get(API, params={
                "query": query,
                "rows": min(max(limit, 1), 25),
                "select": "DOI,title,author,abstract,issued,container-title,URL,type",
            })
            r.raise_for_status()
            items = r.json().get("message", {}).get("items", [])
        except Exception:
            return out
    for it in items:
        titles = it.get("title") or []
        title = (titles[0] if titles else "").strip()
        if not title:
            continue
        doi = it.get("DOI", "")
        abstract = _strip_jats(it.get("abstract") or "")
        authors = [
            " ".join(filter(None, [a.get("given", ""), a.get("family", "")])).strip()
            for a in (it.get("author") or [])
        ][:3]
        issued = it.get("issued", {}).get("date-parts", [[None]])
        year = (issued[0][0] if issued and issued[0] else None)
        venue_list = it.get("container-title") or []
        venue = (venue_list[0] if venue_list else "")
        url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        meta = " · ".join([x for x in [", ".join(authors), str(year) if year else "", venue] if x])
        snippet = (meta + "\n" + abstract).strip() if meta else abstract
        out.append(SourceResult(
            source="crossref",
            title=title,
            url=url,
            snippet=truncate(snippet, 380),
            lang="",
            kind="academic",
            size_hint=len(abstract),
            extra={
                "doi": doi or None,
                "authors": authors,
                "year": year,
                "venue": venue,
                "abstract": abstract,
                "type": it.get("type") or "",
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
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
    parts.append(f"\n_Source: {result.url}_\n")
    if e.get("abstract"):
        parts.append("\n## Abstract\n\n" + e["abstract"])
    name = "crossref-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    return "\n".join(parts), name


_JATS_TAG_RE = re.compile(r"<[^>]+>")


def _strip_jats(s: str) -> str:
    return _JATS_TAG_RE.sub("", s or "").replace("\n", " ").strip()
