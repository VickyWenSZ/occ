"""
GitHub source — surfaces high-signal repositories and their READMEs.

API: https://api.github.com — free, no key required, but:
- Unauthenticated rate limit: 60 requests/hour
- Authenticated rate limit: 5000 requests/hour (set GITHUB_TOKEN env var to enable)

`search()` hits /search/repositories sorted by stars to surface canonical
repos for a topic. `fetch()` hits /repos/{owner}/{name}/readme to pull the
README content (base64-encoded by the API, decoded here). README markdown is
high-quality material for tech packs — design docs, usage examples, design
philosophy, links to deeper resources.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Iterable

from ..types import SourceResult
from ..utils import http_client, truncate

SEARCH_API = "https://api.github.com/search/repositories"
README_API = "https://api.github.com/repos/{owner}/{name}/readme"

_GH_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _auth_headers() -> dict:
    h = dict(_GH_HEADERS)
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    """Search repositories sorted by stars — `langs` is ignored (GitHub is en-first)."""
    out: list[SourceResult] = []
    with http_client(headers=_auth_headers()) as c:
        try:
            r = c.get(SEARCH_API, params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": min(max(limit, 1), 20),
            })
            r.raise_for_status()
            items = r.json().get("items", []) or []
        except Exception:
            return out
    for repo in items:
        full_name = repo.get("full_name") or ""
        desc = repo.get("description") or ""
        stars = repo.get("stargazers_count") or 0
        lang = (repo.get("language") or "").lower()
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        topics = repo.get("topics") or []
        meta = []
        if stars: meta.append(f"★ {stars:,}")
        if lang:  meta.append(lang)
        if topics: meta.append(", ".join(topics[:4]))
        snippet = (" · ".join(meta) + ("\n" + desc if desc else "")).strip()
        out.append(SourceResult(
            source="github",
            title=full_name or "(unknown repo)",
            url=url,
            snippet=truncate(snippet, 380),
            lang="",
            kind="code",
            size_hint=repo.get("size") or 0,
            extra={
                "full_name":  full_name,
                "stars":      stars,
                "language":   lang,
                "topics":     topics,
                "description": desc,
                "default_branch": repo.get("default_branch") or "main",
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """Pull the repository's README and write it as the raw markdown."""
    full_name = (result.extra or {}).get("full_name") or ""
    name = "gh-" + re.sub(r"[^a-z0-9]+", "-", full_name.lower()).strip("-")[:60]
    if "/" not in full_name:
        return _stub(result, name, error="Could not parse owner/repo")

    owner, repo = full_name.split("/", 1)
    with http_client(headers=_auth_headers()) as c:
        try:
            r = c.get(README_API.format(owner=owner, name=repo))
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return _stub(result, name, error=f"README fetch failed: {exc}")

    raw = data.get("content") or ""
    encoding = (data.get("encoding") or "").lower()
    if encoding == "base64":
        try:
            readme_md = base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:
            readme_md = ""
    else:
        readme_md = raw
    readme_md = (readme_md or "").strip()
    if not readme_md:
        return _stub(result, name, error="README empty")

    header_parts = [f"# {full_name}\n"]
    e = result.extra or {}
    if e.get("description"):
        header_parts.append(f"> {e['description']}")
    meta_bits = []
    if e.get("stars"):    meta_bits.append(f"★ {e['stars']:,}")
    if e.get("language"): meta_bits.append(f"language: {e['language']}")
    if e.get("topics"):   meta_bits.append("topics: " + ", ".join(e["topics"][:6]))
    if meta_bits:
        header_parts.append("**Repo metadata:** " + " · ".join(meta_bits))
    header_parts.append(f"\n_Source: {result.url} (GitHub README)_\n")
    return "\n".join(header_parts) + "\n" + readme_md, name


def _stub(result: SourceResult, name: str, error: str) -> tuple[str, str]:
    e = result.extra or {}
    parts = [f"# {result.title}\n"]
    if e.get("description"):
        parts.append(f"> {e['description']}")
    parts.append(f"\n_Source: {result.url} (GitHub)_")
    parts.append(f"\n_{error}_")
    return "\n".join(parts), name
