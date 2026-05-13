"""
arXiv — preprint server. Free Atom-feed API, no key.
"""
from __future__ import annotations

import re
from typing import Iterable
from xml.etree import ElementTree as ET

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}


def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    out: list[SourceResult] = []
    with http_client() as c:
        try:
            r = c.get(API, params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(max(limit, 1), 25),
                "sortBy": "relevance",
            })
            r.raise_for_status()
            root = ET.fromstring(r.text)
        except Exception:
            return out
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        if not title:
            continue
        summary = (entry.findtext("a:summary", default="", namespaces=NS) or "").strip()
        url = ""
        pdf = ""
        for link in entry.findall("a:link", NS):
            href = link.get("href", "")
            if link.get("title") == "pdf":
                pdf = href
            elif link.get("rel") == "alternate":
                url = href
        published = entry.findtext("a:published", default="", namespaces=NS) or ""
        authors = [a.findtext("a:name", default="", namespaces=NS) or ""
                   for a in entry.findall("a:author", NS)][:3]
        meta = " · ".join([x for x in [", ".join(authors), published[:4]] if x])
        snippet = (meta + "\n" + summary).strip() if meta else summary
        out.append(SourceResult(
            source="arxiv",
            title=re.sub(r"\s+", " ", title),
            url=url or pdf,
            snippet=truncate(snippet, 380),
            lang="en",
            kind="academic",
            size_hint=len(summary),
            extra={"pdf_url": pdf, "abstract": summary, "authors": authors, "published": published},
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """Default: metadata + abstract only (cheap, plenty for concept extraction)."""
    e = result.extra or {}
    parts = [f"# {result.title}\n"]
    if e.get("authors"):
        parts.append("**Authors:** " + ", ".join(e["authors"]))
    if e.get("published"):
        parts.append(f"**Published:** {e['published'][:10]}")
    if e.get("pdf_url"):
        parts.append(f"**PDF:** {e['pdf_url']}")
    parts.append(f"\n_Source: {result.url}_\n")
    if e.get("abstract"):
        parts.append("\n## Abstract\n\n" + e["abstract"])
    name = "arxiv-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    return "\n".join(parts), name


def fetch_full_text(result: SourceResult) -> tuple[str, str]:
    """
    Download the paper's PDF and extract text via pymupdf (same dependency
    Forge already uses for PDF ingestion). LaTeX equations rendered in the PDF
    come out as best-effort glyph text — not perfect, but the abstract section
    + introduction + conclusions are usually readable.

    Falls back to the abstract-only stub on any failure.
    """
    e = result.extra or {}
    pdf_url = e.get("pdf_url") or ""
    if not pdf_url:
        return fetch(result)
    try:
        import pymupdf
    except ImportError:
        return fetch(result)

    name = "arxiv-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    try:
        from ..utils import http_client
        with http_client(headers={"Accept": "application/pdf"}) as c:
            r = c.get(pdf_url)
            r.raise_for_status()
            pdf_bytes = r.content
    except Exception:
        return fetch(result)

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        parts: list[str] = []
        for page in doc:
            t = (page.get_text("text") or "").strip()
            if t:
                parts.append(t)
        doc.close()
        body = "\n\n".join(parts).strip()
    except Exception:
        return fetch(result)

    if not body:
        return fetch(result)

    header = [f"# {result.title}\n"]
    if e.get("authors"):
        header.append("**Authors:** " + ", ".join(e["authors"]))
    if e.get("published"):
        header.append(f"**Published:** {e['published'][:10]}")
    header.append(f"\n_Source: {pdf_url} (arXiv, full PDF)_\n")
    return "\n".join(header) + "\n" + body, name
