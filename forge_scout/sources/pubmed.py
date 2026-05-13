"""
PubMed source — biomedical literature via NCBI E-utilities.

Free, no key. Polite usage limit: 3 req/s without key, 10 req/s with key.
Two calls per search: esearch (PMIDs) + efetch (titles, abstracts, metadata).
"""
from __future__ import annotations

import re
from typing import Iterable
from xml.etree import ElementTree as ET

from ..types import SourceResult
from ..utils import http_client, truncate

API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def search(query: str, limit: int = 8, langs: Iterable[str] = ("en",)) -> list[SourceResult]:
    """PubMed is language-agnostic at the API level (most abstracts are English)."""
    out: list[SourceResult] = []
    with http_client() as c:
        # 1) esearch → list of PMIDs
        try:
            r = c.get(f"{API}/esearch.fcgi", params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": min(max(limit, 1), 25),
                "sort": "relevance",
            })
            r.raise_for_status()
            pmids = (r.json().get("esearchresult", {}) or {}).get("idlist") or []
        except Exception:
            return out
        if not pmids:
            return out
        # 2) efetch → XML with abstracts. Plain-text efetch is uglier; XML is structured.
        try:
            r = c.get(f"{API}/efetch.fcgi", params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
            })
            r.raise_for_status()
            root = ET.fromstring(r.text)
        except Exception:
            return out

    for art in root.findall(".//PubmedArticle"):
        med = art.find("MedlineCitation") or ET.Element("x")
        article = med.find("Article") or ET.Element("x")
        pmid_el = med.find("PMID")
        pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""
        title = _txt(article.find("ArticleTitle"))
        if not title:
            continue
        journal = _txt(article.find(".//Journal/Title"))
        year = _txt(article.find(".//PubDate/Year")) or _txt(article.find(".//PubDate/MedlineDate"))[:4]
        # Abstract pieces may be split into labelled sections
        abstract_parts = []
        for ab in article.findall(".//Abstract/AbstractText"):
            label = (ab.get("Label") or "").strip()
            txt = (ab.text or "").strip()
            if txt:
                abstract_parts.append(f"**{label}.** {txt}" if label else txt)
        abstract = "\n\n".join(abstract_parts).strip()
        # First few authors
        authors = []
        for a in article.findall(".//AuthorList/Author")[:3]:
            ln = _txt(a.find("LastName"))
            ini = _txt(a.find("Initials"))
            if ln:
                authors.append((ln + (" " + ini if ini else "")).strip())
        # IDs: DOI + PMC (presence of PMC means an open-access full text is
        # available — we surface it so the user can toggle "full text" on the card).
        doi = ""
        pmc_id = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            kind = (aid.get("IdType") or "").lower()
            val = (aid.text or "").strip()
            if kind == "doi" and not doi:
                doi = val
            elif kind == "pmc" and not pmc_id:
                pmc_id = val   # normally formatted "PMC1234567"
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        # Mark availability with a small badge in the snippet so it's visible
        # in the candidates list without inspecting extras.
        meta_bits = [", ".join(authors), year, journal]
        if pmc_id:
            meta_bits.append("📄 PMC open")
        meta = " · ".join([x for x in meta_bits if x])
        snippet = (meta + ("\n" + abstract if abstract else "")).strip() or meta
        out.append(SourceResult(
            source="pubmed",
            title=title,
            url=url,
            snippet=truncate(snippet, 380),
            lang="en",
            kind="academic",
            size_hint=len(abstract),
            extra={
                "pmid":    pmid,
                "doi":     doi or None,
                "pmc_id":  pmc_id or None,
                "authors": authors,
                "year":    year,
                "journal": journal,
                "abstract": abstract,
            },
        ))
    return out


def fetch(result: SourceResult) -> tuple[str, str]:
    """Metadata + abstract — PubMed never serves full-text directly."""
    e = result.extra or {}
    parts = [f"# {result.title}\n"]
    if e.get("authors"):
        parts.append("**Authors:** " + ", ".join(e["authors"]))
    if e.get("year"):
        parts.append(f"**Year:** {e['year']}")
    if e.get("journal"):
        parts.append(f"**Journal:** {e['journal']}")
    if e.get("pmid"):
        parts.append(f"**PMID:** {e['pmid']}")
    if e.get("doi"):
        parts.append(f"**DOI:** [{e['doi']}](https://doi.org/{e['doi']})")
    parts.append(f"\n_Source: {result.url}_\n")
    if e.get("abstract"):
        parts.append("\n## Abstract\n\n" + e["abstract"])
    name = "pubmed-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    return "\n".join(parts), name


def _txt(elem) -> str:
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def fetch_full_text(result: SourceResult) -> tuple[str, str]:
    """
    Download the full open-access article body from PubMed Central.

    PMC ships full articles as JATS-XML via efetch.fcgi. We extract the
    <body> sections, preserve hierarchy as markdown headings, and keep
    paragraph text. Tables and figures are noted but not rendered.

    Falls back to the abstract-only stub if no PMC ID is set or PMC fetch
    fails (e.g. paper is closed-access, network issue).
    """
    e = result.extra or {}
    pmc_id = (e.get("pmc_id") or "").strip()
    name = "pubmed-" + re.sub(r"[^a-z0-9]+", "-", result.title.lower()).strip("-")[:60]
    if not pmc_id:
        return fetch(result)

    # PMC accepts both "PMC1234567" and "1234567"; normalise.
    pmc_short = pmc_id[3:] if pmc_id.upper().startswith("PMC") else pmc_id
    try:
        with http_client() as c:
            r = c.get(f"{API}/efetch.fcgi", params={
                "db": "pmc",
                "id": pmc_short,
                "rettype": "xml",
            })
            r.raise_for_status()
            root = ET.fromstring(r.text)
    except Exception:
        return fetch(result)

    body_md = _jats_body_to_markdown(root)
    if not body_md.strip():
        return fetch(result)

    header = [f"# {result.title}\n"]
    if e.get("authors"):
        header.append("**Authors:** " + ", ".join(e["authors"]))
    if e.get("year"):
        header.append(f"**Year:** {e['year']}")
    if e.get("journal"):
        header.append(f"**Journal:** {e['journal']}")
    if e.get("pmid"):
        header.append(f"**PMID:** {e['pmid']}")
    if pmc_id:
        header.append(f"**PMC:** {pmc_id}")
    if e.get("doi"):
        header.append(f"**DOI:** [{e['doi']}](https://doi.org/{e['doi']})")
    pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
    header.append(f"\n_Source: {pmc_url} (PubMed Central, full text)_\n")
    return "\n".join(header) + "\n" + body_md, name


def _jats_body_to_markdown(root) -> str:
    """
    Walk JATS-XML and emit a focused markdown rendering of the article body.

    We only render: <abstract>, <body>, <sec> (recursive), <title>, <p>.
    Figures / tables / display-formulas are flattened to their caption text
    or stripped — sufficient for LLM concept extraction, not for re-publishing.
    """
    parts: list[str] = []
    abstract = root.find(".//abstract")
    if abstract is not None:
        parts.append("## Abstract\n")
        parts.append(_jats_section_text(abstract, depth=3))
    body = root.find(".//body")
    if body is not None:
        for child in body:
            tag = (child.tag or "").lower()
            if tag == "sec":
                parts.append(_jats_section_text(child, depth=2))
            elif tag == "p":
                txt = _jats_inline(child)
                if txt.strip():
                    parts.append(txt + "\n")
    return "\n".join(p for p in parts if p.strip())


def _jats_section_text(sec, depth: int = 2) -> str:
    """Render one JATS <sec> or <abstract> with nested sections."""
    out: list[str] = []
    title = sec.find("title")
    if title is not None:
        title_text = _jats_inline(title).strip()
        if title_text:
            out.append("#" * max(2, min(depth, 6)) + " " + title_text + "\n")
    for child in sec:
        tag = (child.tag or "").lower()
        if tag == "title":
            continue   # already emitted
        if tag == "p":
            t = _jats_inline(child)
            if t.strip():
                out.append(t + "\n")
        elif tag == "sec":
            out.append(_jats_section_text(child, depth=depth + 1))
        # tables / figures / display-formula: emit a small placeholder
        elif tag in ("fig", "table-wrap", "disp-formula", "table-wrap-foot"):
            cap = child.find(".//caption")
            cap_text = _jats_inline(cap).strip() if cap is not None else ""
            label = (child.find("label").text if child.find("label") is not None else "")
            label = (label or "").strip()
            marker = "[" + (label or tag) + "]"
            out.append(f"_{marker} {cap_text}_\n" if cap_text else f"_{marker}_\n")
    return "\n".join(out)


def _jats_inline(elem) -> str:
    """Flatten inline JATS text — drop xref/contrib refs, keep emphasis."""
    if elem is None:
        return ""
    # Walk and accumulate text, recognising italic/bold tags
    parts: list[str] = []
    def walk(node):
        tag = (node.tag or "").lower()
        if node.text:
            parts.append(node.text)
        for c in node:
            ctag = (c.tag or "").lower()
            if ctag in ("xref", "ext-link"):
                if c.text:
                    parts.append(c.text)
            elif ctag in ("italic",):
                inner = _jats_inline(c).strip()
                if inner:
                    parts.append(f"*{inner}*")
            elif ctag in ("bold",):
                inner = _jats_inline(c).strip()
                if inner:
                    parts.append(f"**{inner}**")
            else:
                walk(c)
            if c.tail:
                parts.append(c.tail)
    walk(elem)
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()
