"""
Shared helpers for Scout: HTTP client with sensible defaults, slug helpers,
language utilities. Kept tiny on purpose — everything specific to a source
lives in its own module.
"""
from __future__ import annotations

import re
import httpx

USER_AGENT = (
    "OCC-Forge-Scout/0.1 (https://opencognitivecommons.org; sources@opencognitivecommons.org)"
)

# Polite single-tap timeouts: APIs are mostly fast; the user is waiting.
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def http_client(headers: dict | None = None) -> httpx.Client:
    """Sync client for Scout sources. Caller is responsible for closing it (use `with`)."""
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    return httpx.Client(timeout=_HTTP_TIMEOUT, headers=h, follow_redirects=True)


def async_client(headers: dict | None = None) -> httpx.AsyncClient:
    """Async client for parallel fan-out."""
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=h, follow_redirects=True)


def slugify(text: str, max_len: int = 60) -> str:
    """Conservative slugifier: lowercase, hyphens, ASCII only."""
    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len] or "untitled").strip("-")


def truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"
