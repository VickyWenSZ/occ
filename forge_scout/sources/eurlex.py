"""
EUR-Lex source — EU law.

Status: **NOT FUNCTIONAL without a headless browser.**

EUR-Lex (eur-lex.europa.eu) is fully behind an AWS WAF JavaScript challenge:
every direct HTTP request — including with Mozilla User-Agents — returns
a 202 challenge page asking for JS-evaluated tokens. External meta-search
engines that previously bridged this (DuckDuckGo HTML) are now also behind
WAFs, so we have no reliable discovery path.

Honest fallback: search() always returns an empty list. If you want EU law
in a pack, paste the EUR-Lex URL into Forge's URL field from a browser
session — Forge's fetch_url will hit the same WAF and likely fail too, so
the most practical path is opening the document, copy-pasting the body into
Forge's "Text" field.

Left in the registry as a placeholder so the GUI shows an honest stub if a
user picks 'law' as a domain — they see EUR-Lex exists conceptually, and the
empty result tells them what to do instead.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..types import SourceResult


def search(query: str, limit: int = 6, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    # Intentionally returns no results. See module docstring.
    return []


def fetch(result: SourceResult) -> tuple[str, str]:
    """
    EUR-Lex blocks programmatic access with an AWS WAF JS challenge — even
    a Mozilla User-Agent gets a 202 with a challenge page. We can't pull
    the body without running a headless browser, which Scout doesn't ship.

    We write a small metadata stub instead. The user can open the URL in a
    browser, copy the text, and paste it into Forge's "Text" field if they
    need the full document body in the pack.
    """
    celex = (result.extra or {}).get("celex") or ""
    name = "eurlex-" + (celex.lower() or
                       re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60])
    parts = [f"# {result.title}\n"]
    if celex:
        parts.append(f"**CELEX:** {celex}")
    parts.append(f"\n_Source: {result.url} (EUR-Lex)_\n")
    parts.append(
        "_EUR-Lex blocks automated fetches with a JS challenge — only this "
        "metadata reference is in the pack. Open the URL in a browser to read "
        "the full document; paste relevant excerpts manually if needed._"
    )
    return "\n".join(parts), name
