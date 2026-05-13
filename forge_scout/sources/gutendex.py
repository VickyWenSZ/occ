"""
Gutendex — open JSON API for Project Gutenberg. Free, no key.

Surfaces public-domain books with multiple formats. We auto-pick the plain-text
URL when available (preferred over EPUB/HTML for Forge ingestion).
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://gutendex.com/books/"


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    lang_q = ",".join(set(l.lower()[:2] for l in langs))
    with http_client() as c:
        try:
            r = c.get(API, params={
                "search": query,
                "languages": lang_q or "en",
            })
            r.raise_for_status()
            data = r.json()
        except Exception:
            return out
    for b in data.get("results", [])[:limit]:
        title = b.get("title") or ""
        if not title:
            continue
        authors = [a.get("name") for a in b.get("authors", []) if a.get("name")]
        author_str = ", ".join(authors[:3])
        formats = b.get("formats", {}) or {}
        txt_url = (
            formats.get("text/plain; charset=utf-8")
            or formats.get("text/plain; charset=us-ascii")
            or formats.get("text/plain")
            or ""
        )
        # If no plain text, link the Gutenberg page
        url = txt_url or f"https://www.gutenberg.org/ebooks/{b.get('id')}"
        langs_list = b.get("languages") or []
        snippet = (author_str + (f" · {b.get('subjects', [''])[0]}" if b.get("subjects") else "")).strip()
        out.append(SourceResult(
            source="gutendex",
            title=title,
            url=url,
            snippet=truncate(snippet, 320),
            lang=langs_list[0] if langs_list else "",
            kind="book",
            extra={
                "authors": authors,
                "txt_url": txt_url,
                "gutenberg_id": b.get("id"),
                "subjects": b.get("subjects", []),
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    Download the full book text from Project Gutenberg's plain-text URL.

    There is no "stub" mode: selecting a book in Scout means you want it as a
    raw source for Forge. The GUI gates this with a confirmation dialog so
    users never include a book accidentally.
    """
    from ..utils import http_client
    e = result.extra or {}
    txt_url = e.get("txt_url") or ""
    name = "gutenberg-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]

    if not txt_url:
        # No plain-text format available — return a tiny note instead of nothing
        header = [f"# {result.title}\n",
                  f"_Source: {result.url} (Project Gutenberg)_\n",
                  "_No plain-text format available for this book._"]
        return "\n".join(header), name

    try:
        with http_client(headers={"Accept": "text/plain"}) as c:
            r = c.get(txt_url)
            r.raise_for_status()
            body = r.text or ""
    except Exception as exc:
        header = [f"# {result.title}\n",
                  f"_Source: {txt_url} (Project Gutenberg)_\n",
                  f"_Download failed: {exc}_"]
        return "\n".join(header), name

    if not body.strip():
        header = [f"# {result.title}\n",
                  f"_Source: {txt_url} (Project Gutenberg)_\n",
                  "_Downloaded file was empty._"]
        return "\n".join(header), name

    header_parts = [f"# {result.title}\n"]
    if e.get("authors"):
        header_parts.append("**Author(s):** " + ", ".join(e["authors"]))
    if e.get("subjects"):
        header_parts.append("**Subjects:** " + ", ".join(e["subjects"][:6]))
    header_parts.append(f"\n_Source: {txt_url} (Project Gutenberg, full text)_\n")
    return "\n".join(header_parts) + "\n" + body, name
