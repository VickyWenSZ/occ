"""
Wikipedia source — uses the public REST API.

No key required. Endpoints:
- /w/api.php (action=query, list=search) → search results
- /w/api.php (action=query, prop=extracts) → clean plaintext extracts
- /w/api.php (action=parse) → links / categories for walking
- /api/rest_v1/page/summary/{title} → 1-line description + thumbnail

Multilingue: pass `langs=["it","en","la"]` and we hit every wiki in parallel
(here: sequential single-lang, parallelism happens one level up).
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://{lang}.wikipedia.org/w/api.php"
REST = "https://{lang}.wikipedia.org/api/rest_v1"


# ── Public surface ────────────────────────────────────────────────────────────

def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    """Search Wikipedia for `query` across the given languages. Returns merged list."""
    out: list[SourceResult] = []
    with http_client() as c:
        for lang in langs:
            try:
                out.extend(_search_one_lang(c, query, lang, limit))
            except Exception:
                continue
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    Download a Wikipedia page's full text. Tries the math-preserving path
    first (parse API → HTML → math rewrite → trafilatura). Falls back to the
    plain `extracts` API on any failure. Both use OUR httpx, with strict
    timeouts — we never delegate to `trafilatura.fetch_url`, which can hang
    ignoring our timeouts.
    """
    lang = result.lang or "en"
    title = result.extra.get("title") or result.title
    name = f"wiki-{lang}-{_safe_slug(title)}"
    header = f"# {result.title}\n\n_Source: {result.url}_\n\n"

    # Path A — math-preserving via parse API + in-memory extraction.
    try:
        body = _fetch_wikipedia_with_math(title, lang)
        if body.strip():
            return header + body, name
    except Exception:
        pass

    # Path B — plain-text extracts API (no math, but reliable).
    with http_client() as c:
        text = _fetch_extract(c, title, lang)
    body = (text or "").strip()
    return header + body, name


def _fetch_wikipedia_with_math(title: str, lang: str) -> str:
    """
    Hit Wikipedia's parse API for HTML, rewrite math, extract clean text —
    all with strict timeouts and no external fetchers.
    """
    with http_client() as c:
        r = c.get(API.format(lang=lang), params={
            "action": "parse", "page": title, "prop": "text",
            "format": "json", "formatversion": "2",
            "redirects": "1", "disableeditsection": "1", "disabletoc": "1",
        }, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    html = (data.get("parse", {}).get("text") or "").strip()
    if not html:
        return ""
    # Rewrite math elements to inline LaTeX (CPU-only).
    try:
        from forge._sources import _rewrite_math_in_html
        html = _rewrite_math_in_html(html)
    except Exception:
        pass
    # Extract main content. Trafilatura first, BeautifulSoup fallback.
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
        return soup.get_text("\n", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


# ── Walking (Wikipedia-first mode) ────────────────────────────────────────────

def walk(seed_title: str, lang: str, depth: int = 1, max_pages: int = 40,
         include_internal_links: bool = False) -> list[SourceResult]:
    """
    Walk the seed page's neighbourhood up to `depth` hops.

    `include_internal_links=False` → only "See also" + page links flagged as
    structural (categories, infobox-linked pages). Cleaner, focused.
    `include_internal_links=True`  → also follows inline body links. Wider,
    noisier — good for very deep pack creation.

    Returns the seed plus visited pages, as SourceResult objects.
    Deduplicated by title.
    """
    with http_client() as c:
        # Resolve the seed (handles redirects, exact-title misses)
        seed = _resolve_title(c, seed_title, lang)
        if not seed:
            return []
        visited: dict[str, SourceResult] = {seed.extra["title"]: seed}
        frontier = [seed.extra["title"]]
        for _ in range(max(depth, 0)):
            next_frontier: list[str] = []
            for title in frontier:
                if len(visited) >= max_pages:
                    break
                neighbours = _page_links(c, title, lang,
                                         include_inline=include_internal_links)
                for nt in neighbours:
                    if nt in visited or len(visited) >= max_pages:
                        continue
                    sr = _resolve_title(c, nt, lang)
                    if not sr:
                        continue
                    visited[nt] = sr
                    next_frontier.append(nt)
            frontier = next_frontier
            if not frontier or len(visited) >= max_pages:
                break
        return list(visited.values())


# ── Internals ─────────────────────────────────────────────────────────────────

def _search_one_lang(c, query: str, lang: str, limit: int) -> list[SourceResult]:
    r = c.get(API.format(lang=lang), params={
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": min(max(limit, 1), 25),
        "srprop": "snippet|size|wordcount",
        "format": "json",
        "formatversion": "2",
        "utf8": "1",
    })
    r.raise_for_status()
    data = r.json()
    hits = data.get("query", {}).get("search", [])
    out: list[SourceResult] = []
    for h in hits:
        title = h.get("title", "")
        snippet = _strip_html(h.get("snippet", ""))
        wordcount = int(h.get("wordcount") or 0)
        url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        out.append(SourceResult(
            source="wikipedia",
            title=title,
            url=url,
            snippet=truncate(snippet, 320),
            lang=lang,
            kind="encyclopedia",
            size_hint=wordcount * 6,
            extra={"title": title, "wordcount": wordcount},
        ))
    return out


def _resolve_title(c, title: str, lang: str) -> SourceResult | None:
    """Use the REST summary endpoint — follows redirects, includes description."""
    safe = title.replace(" ", "_")
    url = f"{REST.format(lang=lang)}/page/summary/{safe}"
    try:
        r = c.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    if data.get("type") == "disambiguation":
        return None
    final_title = data.get("title") or title
    extract = data.get("extract") or data.get("description") or ""
    page_url = (data.get("content_urls", {}) or {}).get("desktop", {}).get("page") \
               or f"https://{lang}.wikipedia.org/wiki/{final_title.replace(' ', '_')}"
    return SourceResult(
        source="wikipedia",
        title=final_title,
        url=page_url,
        snippet=truncate(extract, 320),
        lang=lang,
        kind="encyclopedia",
        extra={"title": final_title, "description": data.get("description", "")},
    )


def _fetch_extract(c, title: str, lang: str) -> str:
    """Plaintext extract of the full page (clean — no infobox markup, no refs)."""
    r = c.get(API.format(lang=lang), params={
        "action": "query",
        "prop": "extracts",
        "titles": title,
        "explaintext": "1",
        "exsectionformat": "wiki",  # produces `== Section ==` style which we keep
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "utf8": "1",
    })
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
    if not pages:
        return ""
    text = pages[0].get("extract", "") or ""
    return _wikitext_sections_to_md(text)


def _page_links(c, title: str, lang: str, include_inline: bool) -> list[str]:
    """
    Pages to follow from `title`. We always pull:
      - "See also" section links (parsed from the HTML)
      - Pages in the same categories (top N)
    If include_inline=True, we also include the page's article-namespace links.
    """
    out: list[str] = []
    # See Also section + inline links via prop=links (article namespace only)
    if include_inline:
        try:
            r = c.get(API.format(lang=lang), params={
                "action": "query",
                "prop": "links",
                "titles": title,
                "pllimit": "60",
                "plnamespace": "0",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
            })
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", [])
            for p in pages:
                for lk in p.get("links", []) or []:
                    name = lk.get("title")
                    if name:
                        out.append(name)
        except Exception:
            pass

    # See Also section specifically (always)
    try:
        sa = _section_links(c, title, lang, "See also") or \
             _section_links(c, title, lang, "Voci correlate") or \
             _section_links(c, title, lang, "Siehe auch") or \
             _section_links(c, title, lang, "Voir aussi")
        if sa:
            out.extend(sa)
    except Exception:
        pass

    # Dedup while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _section_links(c, title: str, lang: str, section_heading: str) -> list[str]:
    """Pull `<a>` titles from one specific section using action=parse."""
    # Find section index
    try:
        r = c.get(API.format(lang=lang), params={
            "action": "parse",
            "page": title,
            "prop": "sections",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        })
        r.raise_for_status()
        sections = r.json().get("parse", {}).get("sections", [])
    except Exception:
        return []
    idx = None
    for s in sections:
        if (s.get("line") or "").strip().lower() == section_heading.lower():
            idx = s.get("index")
            break
    if not idx:
        return []
    try:
        r = c.get(API.format(lang=lang), params={
            "action": "parse",
            "page": title,
            "section": idx,
            "prop": "links",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        })
        r.raise_for_status()
        links = r.json().get("parse", {}).get("links", []) or []
    except Exception:
        return []
    return [lk.get("title") for lk in links if lk.get("ns") == 0 and lk.get("title")]


_SECTION_RE = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.MULTILINE)


def _wikitext_sections_to_md(text: str) -> str:
    """
    Wikipedia's `explaintext=1` returns clean text but with `== Section ==`
    headings. Convert to `## Section` markdown headings.
    """
    def repl(m: re.Match) -> str:
        level = len(m.group(1))
        # Wiki '==' = top-level section → ## (we keep H1 for the page title)
        md_level = max(level, 2)
        return ("#" * md_level) + " " + m.group(2).strip()
    return _SECTION_RE.sub(repl, text or "")


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").replace("&nbsp;", " ").strip()


def _safe_slug(t: str) -> str:
    s = (t or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60] or "page"
