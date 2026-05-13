"""
Common types for Scout sources.

Every source module exposes a `search()` function that returns
a list of `SourceResult`. Downstream code (ranking, GUI, Forge handoff)
only sees this uniform shape — never the source-specific raw JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SourceResult:
    source: str                      # provider id: "wikipedia", "openalex", ...
    title: str
    url: str
    snippet: str = ""                # short description, ≤ ~400 chars
    lang: str = ""                   # ISO code: "en", "it", "la", ...
    kind: str = "general"            # encyclopedia | academic | primary | book | general
    score: float = 0.0               # filled by ranker; higher = better
    size_hint: int = 0               # approximate text size in chars, if known
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def dedup_key(self) -> str:
        """
        Stable key for deduplication.
        Prefer DOI when present, otherwise normalised URL.
        """
        doi = (self.extra or {}).get("doi")
        if doi:
            return f"doi:{str(doi).lower().strip()}"
        url = (self.url or "").strip().lower()
        for prefix in ("https://", "http://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return f"url:{url.rstrip('/')}"
