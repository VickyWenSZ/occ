"""
Internet Archive (archive.org) — vast multi-format library: books, papers,
audio. We only surface 'texts' media here. Free, no key.

We do NOT auto-download the full book on fetch — those can be enormous.
We surface the work page and, when available, a plain-text URL the user can
inspect or hand to Forge.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

ADVANCED = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/{ident}"
DETAILS = "https://archive.org/details/{ident}"


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    # advancedsearch needs an explicit fields & rows.
    q = f'({query}) AND mediatype:texts'
    params = {
        "q": q,
        "fl[]": ["identifier", "title", "creator", "year", "language", "description"],
        "rows": str(min(max(limit, 1), 25)),
        "output": "json",
    }
    with http_client() as c:
        try:
            r = c.get(ADVANCED, params=params)
            r.raise_for_status()
            docs = r.json().get("response", {}).get("docs", [])
        except Exception:
            return out
    for d in docs:
        ident = d.get("identifier") or ""
        title = d.get("title") or ident
        if isinstance(title, list):
            title = title[0]
        creator = d.get("creator") or ""
        if isinstance(creator, list):
            creator = ", ".join(creator[:3])
        desc = d.get("description") or ""
        if isinstance(desc, list):
            desc = " ".join(desc)
        # Light HTML strip — archive.org descriptions often contain <br/> and <a>
        desc = re.sub(r"<[^>]+>", "", desc)
        year = d.get("year") or ""
        lang = d.get("language") or ""
        if isinstance(lang, list):
            lang = lang[0]
        meta_line = " · ".join([x for x in [creator, str(year)] if x])
        snippet = (meta_line + "\n" + desc).strip() if meta_line else desc
        out.append(SourceResult(
            source="archive_org",
            title=title if isinstance(title, str) else str(title),
            url=DETAILS.format(ident=ident),
            snippet=truncate(snippet, 380),
            lang=str(lang)[:2].lower() if lang else "",
            kind="book",
            extra={"identifier": ident, "creator": creator, "year": year},
        ))
    return out


def _find_plaintext_url(ident: str) -> str:
    """Resolve the plain-text derivative URL for an archive.org identifier."""
    if not ident:
        return ""
    with http_client() as c:
        try:
            r = c.get(META.format(ident=ident))
            r.raise_for_status()
            meta = r.json()
            for f in (meta.get("files") or []):
                name = f.get("name", "")
                fmt = (f.get("format") or "").lower()
                if fmt in ("djvutxt", "text", "plain text", "djvu txt"):
                    return f"https://archive.org/download/{ident}/{name}"
        except Exception:
            return ""
    return ""


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    Download the OCR'd plain-text derivative for this archive.org item.
    The GUI gates this with a confirmation dialog so books are never picked accidentally.
    """
    ident = (result.extra or {}).get("identifier") or ""
    title = result.title
    creator = (result.extra or {}).get("creator", "")
    year = (result.extra or {}).get("year", "")
    name = "ia-" + re.sub(r"[^a-z0-9]+", "-", (ident or title).lower()).strip("-")[:60]

    plaintext_url = _find_plaintext_url(ident)
    if not plaintext_url:
        header = [f"# {title}\n",
                  f"_Source: {result.url} (Internet Archive)_",
                  "_No plain-text derivative published for this item._"]
        return "\n".join(header), name

    try:
        with http_client(headers={"Accept": "text/plain"}) as c:
            r = c.get(plaintext_url)
            r.raise_for_status()
            body = r.text or ""
    except Exception as exc:
        header = [f"# {title}\n",
                  f"_Source: {plaintext_url} (Internet Archive)_",
                  f"_Download failed: {exc}_"]
        return "\n".join(header), name

    if not body.strip():
        header = [f"# {title}\n",
                  f"_Source: {plaintext_url} (Internet Archive)_",
                  "_Downloaded file was empty._"]
        return "\n".join(header), name

    header = [f"# {title}\n"]
    if creator:
        header.append(f"**Author:** {creator}")
    if year:
        header.append(f"**Year:** {year}")
    header.append(f"\n_Source: {plaintext_url} (Internet Archive, OCR full text)_\n")
    return "\n".join(header) + "\n" + body, name
