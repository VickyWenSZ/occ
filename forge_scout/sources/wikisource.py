"""
Wikisource — primary-source library. Same API engine as Wikipedia.

Italian Wikisource has e.g. the full text of De Bello Gallico in Latin and
translations. English Wikisource has tens of thousands of original works.
Multilingue. No key.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://{lang}.wikisource.org/w/api.php"
_TAG_RE = re.compile(r"<[^>]+>")


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client() as c:
        for lang in langs:
            try:
                r = c.get(API.format(lang=lang), params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": min(max(limit, 1), 25),
                    "srprop": "snippet|size",
                    "format": "json",
                    "formatversion": "2",
                    "utf8": "1",
                })
                r.raise_for_status()
                hits = r.json().get("query", {}).get("search", [])
            except Exception:
                continue
            for h in hits:
                title = h.get("title", "")
                # Skip namespaces: Author:, Portal:, etc. — we want works only.
                if ":" in title and not title.startswith(("Author:", "Page:")):
                    continue
                snippet = _TAG_RE.sub("", h.get("snippet", "")).strip()
                url = f"https://{lang}.wikisource.org/wiki/{title.replace(' ', '_')}"
                out.append(SourceResult(
                    source="wikisource",
                    title=title,
                    url=url,
                    snippet=truncate(snippet, 320),
                    lang=lang,
                    kind="primary",
                    size_hint=int(h.get("size") or 0),
                    extra={"title": title},
                ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    lang = result.lang or "en"
    title = result.extra.get("title") or result.title
    with http_client() as c:
        r = c.get(API.format(lang=lang), params={
            "action": "query",
            "prop": "extracts",
            "titles": title,
            "explaintext": "1",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "utf8": "1",
        })
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", [])
    body = (pages[0].get("extract", "") if pages else "") or ""
    header = f"# {result.title}\n\n_Source: {result.url} (Wikisource)_\n\n"
    name = "wikisource-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    return header + body, name
