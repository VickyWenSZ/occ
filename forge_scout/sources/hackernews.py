"""
Hacker News source — community-curated tech discussion.

API: Algolia-hosted search at https://hn.algolia.com/api/v1 — free, no key.
Two endpoints:
  - /search?query=X&tags=story → ranked stories (link posts + text posts)
  - /items/<id> → full comment tree for a story

We surface stories sorted by points. On fetch, we pull the comment tree and
flatten the top N highest-voted root comments into markdown. For text posts
(Ask HN, Show HN) we also include the story body.
"""
from __future__ import annotations

import html
import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API_SEARCH = "https://hn.algolia.com/api/v1/search"
API_ITEM   = "https://hn.algolia.com/api/v1/items/{id}"


def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client() as c:
        try:
            # tags=story filters out comments/polls; sort by points via search?
            # Algolia's default ranking already factors in points. For pure
            # popularity we'd use search_by_date and order client-side.
            r = c.get(API_SEARCH, params={
                "query":       query,
                "tags":        "story",
                "hitsPerPage": min(max(limit, 1), 25),
            })
            r.raise_for_status()
            hits = r.json().get("hits", []) or []
        except Exception:
            return out
    for h in hits:
        title = h.get("title") or h.get("story_title") or ""
        if not title:
            continue
        oid = h.get("objectID") or ""
        points = h.get("points") or 0
        ncomments = h.get("num_comments") or 0
        author = h.get("author") or ""
        url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
        story_text = (h.get("story_text") or "").strip()
        story_text = _html_to_text(story_text)
        meta = " · ".join([x for x in [f"▲ {points}", f"{ncomments} comments",
                                       author and f"@{author}"] if x])
        snippet = (meta + ("\n" + story_text[:280] if story_text else "")).strip()
        out.append(SourceResult(
            source="hackernews",
            title=title,
            url=url,
            snippet=truncate(snippet, 380),
            lang="en",
            kind="general",
            size_hint=len(story_text),
            extra={
                "object_id": oid,
                "points":    points,
                "num_comments": ncomments,
                "author":    author,
                "hn_url":    f"https://news.ycombinator.com/item?id={oid}",
                "story_text": story_text,
                "linked_url": url if url != f"https://news.ycombinator.com/item?id={oid}" else "",
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """Title + story text + top N voted top-level comments."""
    e = result.extra or {}
    oid = e.get("object_id")
    name = "hn-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]

    parts = [f"# {result.title}\n"]
    if e.get("author"):
        parts.append(f"**Author:** @{e['author']}")
    if e.get("points") is not None:
        parts.append(f"**Score:** ▲ {e['points']}")
    if e.get("linked_url"):
        parts.append(f"**Linked URL:** {e['linked_url']}")
    parts.append(f"\n_Source: {e.get('hn_url') or result.url} (Hacker News)_\n")

    if e.get("story_text"):
        parts.append("## Story text\n\n" + e["story_text"])

    # Pull comment tree
    comments_md = ""
    if oid:
        with http_client() as c:
            try:
                r = c.get(API_ITEM.format(id=oid))
                r.raise_for_status()
                tree = r.json()
            except Exception:
                tree = {}
        top = _top_comments(tree, max_n=5)
        if top:
            comments_md = "\n\n".join(
                f"### Comment by @{c['author']} (▲ {c.get('points') or '?'})\n\n{c['text']}"
                for c in top
            )
    if comments_md:
        parts.append("## Top comments\n\n" + comments_md)

    return "\n\n".join(parts), name


def _top_comments(tree: dict, max_n: int = 5) -> list[dict]:
    """Return root-level comments sorted by points desc."""
    kids = (tree or {}).get("children") or []
    rated = []
    for k in kids:
        text = _html_to_markdown(k.get("text") or "")
        if not text:
            continue
        rated.append({
            "author": k.get("author") or "anon",
            "points": k.get("points"),
            "text":   text,
        })
    # Algolia's items endpoint doesn't always include points on comments —
    # falls back to sort by depth-first order if points are missing
    rated.sort(key=lambda c: c.get("points") or 0, reverse=True)
    return rated[:max_n]


_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s or "")).strip()


def _html_to_markdown(s: str) -> str:
    if not s:
        return ""
    out = s
    out = re.sub(r"<p[^>]*>", "\n\n", out)
    out = re.sub(r"</p>", "", out)
    out = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>",
                 lambda m: "\n```\n" + html.unescape(m.group(1)) + "\n```\n",
                 out, flags=re.DOTALL)
    out = re.sub(r"<code[^>]*>(.*?)</code>",
                 lambda m: "`" + html.unescape(m.group(1)) + "`",
                 out, flags=re.DOTALL)
    out = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", out, flags=re.DOTALL)
    out = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", out, flags=re.DOTALL)
    out = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", out, flags=re.DOTALL)
    out = _TAG_RE.sub("", out)
    return html.unescape(out).strip()
