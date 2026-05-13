"""
Scout source registry.

Every module under this package implements one source. The module-level
`search(query, limit, langs)` returns `list[SourceResult]` and
`fetch(result)` returns `(markdown_text, source_name)`. Sources never
require API keys unless explicitly opt-in (e.g. brave, tavily).

The registry below drives both the GUI source-checkbox UI and the
domain → sources routing used by multi-source mode.
"""
from __future__ import annotations

from . import (
    wikipedia,
    wikisource,
    wikidata,
    archive_org,
    openalex,
    arxiv,
    crossref,
    gutendex,
    github,
    stackexchange,
    pubmed,
    hackernews,
    sep,
    mathworld,
    eurlex,
)

# kind: encyclopedia | primary | academic | book | general
# domains: which domains this source is relevant to. "*" = always.
REGISTRY: dict[str, dict] = {
    "wikipedia": {
        "module": wikipedia,
        "label": "Wikipedia",
        "kind": "encyclopedia",
        "needs_key": False,
        "domains": ["*"],
    },
    "wikisource": {
        "module": wikisource,
        "label": "Wikisource",
        "kind": "primary",
        "needs_key": False,
        "domains": ["history", "literature", "philosophy", "law"],
    },
    "archive_org": {
        "module": archive_org,
        "label": "Internet Archive",
        "kind": "book",
        "needs_key": False,
        "domains": ["history", "literature", "philosophy", "art", "*"],
    },
    "openalex": {
        "module": openalex,
        "label": "OpenAlex",
        "kind": "academic",
        "needs_key": False,
        "domains": ["science", "tech", "medicine", "social_science", "*"],
    },
    "arxiv": {
        "module": arxiv,
        "label": "arXiv",
        "kind": "academic",
        "needs_key": False,
        "domains": ["science", "tech"],
    },
    "crossref": {
        "module": crossref,
        "label": "Crossref",
        "kind": "academic",
        "needs_key": False,
        "domains": ["science", "tech", "medicine", "social_science"],
    },
    "gutendex": {
        "module": gutendex,
        "label": "Project Gutenberg",
        "kind": "book",
        "needs_key": False,
        "domains": ["literature", "philosophy", "history"],
    },
    "github": {
        "module": github,
        "label": "GitHub",
        "kind": "code",
        "needs_key": False,     # optional GITHUB_TOKEN lifts the rate limit
        "domains": ["tech"],
    },
    "stackexchange": {
        "module": stackexchange,
        "label": "StackOverflow",
        "kind": "code",
        "needs_key": False,
        "domains": ["tech"],
    },
    "pubmed": {
        "module": pubmed,
        "label": "PubMed",
        "kind": "academic",
        "needs_key": False,
        "domains": ["medicine", "science"],
    },
    "hackernews": {
        "module": hackernews,
        "label": "Hacker News",
        "kind": "general",
        "needs_key": False,
        "domains": ["tech"],
    },
    "sep": {
        "module": sep,
        "label": "Stanford Encyclopedia of Philosophy",
        "kind": "encyclopedia",
        "needs_key": False,
        "domains": ["philosophy", "social_science"],
    },
    "mathworld": {
        "module": mathworld,
        "label": "Wolfram MathWorld",
        "kind": "encyclopedia",
        "needs_key": False,
        "domains": ["science", "tech"],
    },
    "eurlex": {
        "module": eurlex,
        "label": "EUR-Lex",
        "kind": "primary",
        "needs_key": False,
        "domains": ["law"],
    },
}


def sources_for_domain(domain: str) -> list[str]:
    """Return the source IDs relevant to the given domain, in registry order."""
    out: list[str] = []
    for sid, meta in REGISTRY.items():
        doms = meta.get("domains", [])
        if "*" in doms or domain in doms:
            out.append(sid)
    return out


__all__ = ["REGISTRY", "sources_for_domain", "wikidata"]
