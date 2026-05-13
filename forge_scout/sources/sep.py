"""
Stanford Encyclopedia of Philosophy (SEP) — gold-standard philosophy reference.

No public API. We scrape the search page and the entry pages. Articles are
peer-reviewed scholarly essays (5-15k words each) — by far the highest signal
source for any philosophy / intellectual-history topic.

Search:  https://plato.stanford.edu/search/searcher.py?query=X
Entry:   https://plato.stanford.edu/entries/<slug>/

For fetch we route through Forge's `fetch_url`, which uses trafilatura to
extract clean main-text content from arbitrary HTML.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

SEARCH_URL = "https://plato.stanford.edu/search/searcher.py"
ENTRY_URL  = "https://plato.stanford.edu/entries/{slug}/"

# SEP search wraps each entry in a result_title div containing ONE anchor
# whose href is a redirect URL carrying `entry=/entries/<slug>/`. The title
# is the anchor's inner content (often wrapped in <b>).
_RESULT_BLOCK_RE = re.compile(
    r'<div class="result_title">\s*'
    r'<a[^>]*href="[^"]*entry=/entries/(?P<slug>[a-z0-9\-]+)/[^"]*"[^>]*>'
    r'(?P<title_html>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_BLOCK_RE = re.compile(
    r'<div class="result_snippet">(?P<body>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_TAGS_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", _TAGS_RE.sub("", s or "")).strip()


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client(headers={"Accept": "text/html"}) as c:
        try:
            r = c.get(SEARCH_URL, params={"query": query})
            r.raise_for_status()
            html_text = r.text or ""
        except Exception:
            return out

    # Iterate result_title blocks; for each, also pull the next result_snippet.
    seen: set[str] = set()
    for m in _RESULT_BLOCK_RE.finditer(html_text):
        slug = m.group("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        title = _strip_html(m.group("title_html"))
        if not title:
            continue
        # Look for a snippet within the next ~1200 chars after this block.
        snip_match = _SNIPPET_BLOCK_RE.search(html_text, m.end(), m.end() + 1200)
        snippet = _strip_html(snip_match.group("body")) if snip_match else ""
        url = f"https://plato.stanford.edu/entries/{slug}/"
        out.append(SourceResult(
            source="sep",
            title=title,
            url=url,
            snippet=truncate(snippet, 320),
            lang="en",
            kind="encyclopedia",
            extra={"slug": slug},
        ))
        if len(out) >= limit:
            break
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    Fetch the SEP entry. We do the HTTP ourselves (httpx with strict timeout)
    and only hand the in-memory HTML to trafilatura's extractor — never to
    `trafilatura.fetch_url`, which has historically hung on certain servers
    with no respect for our timeouts.
    """
    name = "sep-" + re.sub(r"[^a-z0-9]+", "-",
                            ((result.extra or {}).get("slug") or result.title).lower()).strip("-")[:60]

    # 1. Pull HTML with a hard 15s budget. http_client() has its own timeout.
    try:
        with http_client(headers={"Accept": "text/html"}) as c:
            r = c.get(result.url, timeout=15.0)
            r.raise_for_status()
            html = r.text or ""
    except Exception as exc:
        return _stub(result, name, f"HTTP fetch failed: {exc}")
    if not html.strip():
        return _stub(result, name, "Server returned empty HTML.")

    # 2. Extract main content. Try trafilatura first, then BeautifulSoup, then
    #    a brute-force tag strip — at least one always returns something usable.
    body = _extract_main_text(html)
    if not body.strip():
        return _stub(result, name, "Could not extract main content.")

    header = f"# {result.title}\n\n_Source: {result.url} (Stanford Encyclopedia of Philosophy)_\n\n"
    return header + body, name


def _extract_main_text(html: str) -> str:
    """Best-effort HTML → plain text. Tries trafilatura.extract first
    (in-memory, no network), then BeautifulSoup, then a regex strip."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text) > 200:
            return text
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        if text and len(text) > 200:
            return text
    except Exception:
        pass
    # Last resort: strip tags
    return re.sub(r"<[^>]+>", "", html)


def _stub(result: SourceResult, name: str, reason: str) -> tuple[str, str]:
    return (f"# {result.title}\n\n_Source: {result.url} (SEP)_\n\n_{reason}_", name)


def _slug_from_url(url: str) -> str:
    m = re.search(r"/entries/([^/]+)/?$", url)
    return m.group(1) if m else ""
