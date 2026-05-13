"""
Stack Exchange (StackOverflow) source — top-voted accepted answers.

API: https://api.stackexchange.com/2.3 — free, 300 requests/day unauthenticated.
A registered application key would lift it to 10000/day but isn't required.

`search()` queries /search/advanced filtered to questions with an accepted
answer, sorted by votes. `fetch()` pulls the accepted answer body in markdown.
StackOverflow answers are practical, code-heavy, and exactly the kind of
material missing from purely academic sources for tech packs.
"""
from __future__ import annotations

import html
import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

API_SEARCH  = "https://api.stackexchange.com/2.3/search/advanced"
API_ANSWERS = "https://api.stackexchange.com/2.3/questions/{qid}/answers"

# All results come from Stack Exchange already gzipped — httpx handles it.


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client() as c:
        try:
            r = c.get(API_SEARCH, params={
                "q":         query,
                "site":      "stackoverflow",
                "order":     "desc",
                "sort":      "votes",
                "accepted":  "True",
                "filter":    "withbody",     # include question body
                "pagesize":  min(max(limit, 1), 20),
            })
            r.raise_for_status()
            items = r.json().get("items", []) or []
        except Exception:
            return out
    for q in items:
        title = html.unescape(q.get("title") or "")
        if not title:
            continue
        qid = q.get("question_id")
        url = q.get("link") or f"https://stackoverflow.com/q/{qid}"
        score = q.get("score") or 0
        answer_count = q.get("answer_count") or 0
        tags = q.get("tags") or []
        accepted = q.get("accepted_answer_id")
        body_html = q.get("body") or ""
        snippet_text = _html_to_text(body_html)[:300]
        meta_bits = [f"▲ {score}", f"{answer_count} answers"]
        if tags:
            meta_bits.append(", ".join(tags[:4]))
        snippet = " · ".join(meta_bits) + ("\n" + snippet_text if snippet_text else "")
        out.append(SourceResult(
            source="stackexchange",
            title=title,
            url=url,
            snippet=truncate(snippet, 380),
            lang="en",
            kind="code",
            size_hint=len(body_html),
            extra={
                "question_id": qid,
                "accepted_answer_id": accepted,
                "tags": tags,
                "score": score,
                "question_body_html": body_html,
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """Pull the accepted answer (and question body) and write as markdown."""
    e = result.extra or {}
    qid = e.get("question_id")
    accepted_id = e.get("accepted_answer_id")
    name = "so-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]

    question_md = _html_to_markdown(e.get("question_body_html") or "")

    accepted_md = ""
    if accepted_id and qid:
        with http_client() as c:
            try:
                r = c.get(API_ANSWERS.format(qid=qid), params={
                    "site": "stackoverflow", "filter": "withbody",
                    "order": "desc", "sort": "votes",
                })
                r.raise_for_status()
                answers = r.json().get("items", []) or []
            except Exception:
                answers = []
        # Find accepted, else top-voted
        chosen = next((a for a in answers if a.get("answer_id") == accepted_id), None)
        if not chosen and answers:
            chosen = answers[0]
        if chosen:
            accepted_md = _html_to_markdown(chosen.get("body") or "")

    parts = [f"# {result.title}\n"]
    if e.get("tags"):
        parts.append("**Tags:** " + ", ".join(e["tags"][:8]))
    if e.get("score") is not None:
        parts.append(f"**Question score:** {e['score']}")
    parts.append(f"\n_Source: {result.url} (StackOverflow)_\n")
    if question_md.strip():
        parts.append("## Question\n\n" + question_md.strip())
    if accepted_md.strip():
        parts.append("\n## Accepted answer\n\n" + accepted_md.strip())
    return "\n\n".join(parts), name


# ── Tiny HTML → markdown converter (enough for SO bodies) ─────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s or "")).strip()


def _html_to_markdown(s: str) -> str:
    """
    Very small subset converter for StackOverflow answer bodies.
    Preserves <pre><code> blocks, inline <code>, simple paragraphs and lists.
    """
    if not s:
        return ""
    out = s
    # Code blocks
    out = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>",
                 lambda m: "\n```\n" + html.unescape(m.group(1)) + "\n```\n",
                 out, flags=re.DOTALL)
    # Inline code
    out = re.sub(r"<code[^>]*>(.*?)</code>",
                 lambda m: "`" + html.unescape(m.group(1)) + "`",
                 out, flags=re.DOTALL)
    # Bold / italic
    out = re.sub(r"<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", out, flags=re.DOTALL)
    out = re.sub(r"<(em|i)[^>]*>(.*?)</\1>", r"*\2*", out, flags=re.DOTALL)
    # Lists
    out = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1", out, flags=re.DOTALL)
    out = re.sub(r"</?(ul|ol)[^>]*>", "\n", out)
    # Paragraphs and breaks
    out = re.sub(r"</p>\s*<p[^>]*>", "\n\n", out)
    out = re.sub(r"<p[^>]*>", "", out)
    out = re.sub(r"</p>", "\n\n", out)
    out = re.sub(r"<br\s*/?>", "\n", out)
    # Links
    out = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", out, flags=re.DOTALL)
    # Strip everything else
    out = _TAG_RE.sub("", out)
    return html.unescape(out)
