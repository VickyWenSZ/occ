"""
Wikidata disambiguation.

Uses the public `wbsearchentities` action — no key, no rate limits beyond
the usual etiquette ones. Given a free-text label, returns the candidate
Q-entities so the user (or the LLM) can pick the right "Cesare":
Giulio Cesare / Cesare Beccaria / Cesare Cremonini / ...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..utils import http_client

API = "https://www.wikidata.org/w/api.php"


@dataclass
class WikidataCandidate:
    qid: str
    label: str
    description: str
    url: str
    matched_lang: str

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "label": self.label,
            "description": self.description,
            "url": self.url,
            "matched_lang": self.matched_lang,
        }


def search(query: str, langs: Iterable[str] = ("en", "it"), limit: int = 7
           ) -> list[WikidataCandidate]:
    """
    Search Wikidata for entities matching `query`. We try each language until
    we have at least 3 candidates, then merge — this catches Italian-only
    labels for Italian-speaking topics like "Giulio Cesare".
    """
    seen: dict[str, WikidataCandidate] = {}
    with http_client() as c:
        for lang in langs:
            try:
                r = c.get(API, params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": lang,
                    "uselang": lang,
                    "type": "item",
                    "limit": min(max(limit, 1), 20),
                    "format": "json",
                })
                r.raise_for_status()
                for hit in r.json().get("search", []):
                    qid = hit.get("id", "")
                    if not qid or qid in seen:
                        continue
                    seen[qid] = WikidataCandidate(
                        qid=qid,
                        label=hit.get("label", ""),
                        description=hit.get("description", "") or "",
                        url=hit.get("concepturi") or f"https://www.wikidata.org/wiki/{qid}",
                        matched_lang=lang,
                    )
            except Exception:
                continue
            if len(seen) >= limit:
                break
    return list(seen.values())[:limit]


def sitelinks(qid: str) -> dict[str, str]:
    """
    Get the Wikipedia page title for this entity in each language.
    Returns {"en": "Julius Caesar", "it": "Gaio Giulio Cesare", ...}.
    Useful as a multilingue seed for the Wikipedia walker.
    """
    with http_client() as c:
        try:
            r = c.get(API, params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "sitelinks",
                "format": "json",
            })
            r.raise_for_status()
            ent = r.json().get("entities", {}).get(qid, {})
        except Exception:
            return {}
    out: dict[str, str] = {}
    for site, info in (ent.get("sitelinks") or {}).items():
        if site.endswith("wiki") and not site.startswith(("commons", "meta")):
            lang = site[:-4]  # 'enwiki' → 'en'
            if info.get("title"):
                out[lang] = info["title"]
    return out
