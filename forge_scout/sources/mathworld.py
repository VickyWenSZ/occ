"""
Wolfram MathWorld source — encyclopedic mathematics reference.

MathWorld has no public search API and its own /search page is JS-driven.
External meta-search engines (DDG/Brave/...) all hit anti-bot WAFs.

Workaround: MathWorld URLs are deterministic — `<PascalCase>.html`. We
generate a small set of candidate URLs from the query (the verbatim query,
common variants, and stripped trailing 's') and check which ones exist via
a HEAD request. MathWorld itself is firewall-free for its own pages.

The hit-rate is high for canonical math topics ("Group Theory", "Riemann
Hypothesis", "Differential Equation") and low for queries that don't match
an entry name — we just return whatever exists.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

BASE_URL = "https://mathworld.wolfram.com"


def _pascal(words: list[str]) -> str:
    return "".join(w[:1].upper() + w[1:].lower() for w in words if w)


def _candidate_urls(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+", query)
    if not words:
        return []
    cands: list[str] = []
    cands.append(_pascal(words))
    # Try without the trailing 's' if plural (Groups → Group)
    if words and words[-1].lower().endswith("s") and len(words[-1]) > 3:
        cands.append(_pascal(words[:-1] + [words[-1][:-1]]))
    # Try only the last word and only the first word as standalone topics
    if len(words) >= 2:
        cands.append(_pascal([words[-1]]))
        cands.append(_pascal([words[0]]))
    # Dedup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:6]


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    """Probe likely PascalCase URLs and return whichever resolve."""
    out: list[SourceResult] = []
    seen_urls: set[str] = set()
    with http_client(headers={"Accept": "text/html"}) as c:
        for slug in _candidate_urls(query):
            url = f"{BASE_URL}/{slug}.html"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                # HEAD is fast and skips body transfer
                r = c.head(url)
                # Some servers reject HEAD with 405 — fall back to GET in that case
                if r.status_code in (404, 410):
                    continue
                if r.status_code == 405:
                    r = c.get(url)
                if r.status_code != 200:
                    continue
            except Exception:
                continue
            # Friendly title: re-space the PascalCase
            spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", slug)
            out.append(SourceResult(
                source="mathworld",
                title=f"{spaced} — Wolfram MathWorld",
                url=url,
                snippet=truncate(f"MathWorld entry: {spaced}", 320),
                lang="en",
                kind="encyclopedia",
                extra={"page_path": f"/{slug}.html", "slug": slug},
            ))
            if len(out) >= limit:
                break
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    Fetch the MathWorld entry. Use httpx + in-memory trafilatura extraction
    (NOT trafilatura.fetch_url, which can hang ignoring our timeouts).
    Math elements (MathML / fallback images) are rewritten to inline LaTeX
    in HTML BEFORE extraction so formulas survive.
    """
    slug = ((result.extra or {}).get("page_path") or "").strip("/").split(".")[0]
    name = "mathworld-" + re.sub(r"[^a-z0-9]+", "-", (slug or result.title).lower()).strip("-")[:60]

    try:
        with http_client(headers={"Accept": "text/html"}) as c:
            r = c.get(result.url, timeout=15.0)
            r.raise_for_status()
            html = r.text or ""
    except Exception as exc:
        return _stub(result, name, f"HTTP fetch failed: {exc}")
    if not html.strip():
        return _stub(result, name, "Server returned empty HTML.")

    # Math rewrite — reuse Forge's helper since it's pure-CPU on a string.
    try:
        from forge._sources import _rewrite_math_in_html
        html = _rewrite_math_in_html(html)
    except Exception:
        pass

    body = _extract_main_text(html)
    if not body.strip():
        return _stub(result, name, "Could not extract main content.")

    header = f"# {result.title}\n\n_Source: {result.url} (Wolfram MathWorld)_\n\n"
    return header + body, name


def _extract_main_text(html: str) -> str:
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
    return re.sub(r"<[^>]+>", "", html)


def _stub(result: SourceResult, name: str, reason: str) -> tuple[str, str]:
    return (f"# {result.title}\n\n_Source: {result.url} (MathWorld)_\n\n_{reason}_", name)
