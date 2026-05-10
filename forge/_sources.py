"""
Source readers for OCC Forge.
Handles .txt, .md, .pdf files and URLs.
Returns (text, source_name, source_url) tuples.
"""
import re
import hashlib
from pathlib import Path


def read_file(path: Path) -> tuple[str, str, str]:
    """Read a .txt / .md / .pdf file. Returns (text, name, url)."""
    if path.suffix.lower() == ".pdf":
        text = _read_pdf(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    source_name = re.sub(r'[^a-z0-9-]', '-', path.stem.lower()).strip('-')
    return text, source_name, path.resolve().as_uri()


def _read_pdf(path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf")
    reader = pypdf.PdfReader(str(path))
    pages = [p.extract_text() or "" for p in reader.pages]
    return "\n\n".join(pages)


def fetch_url(url: str) -> tuple[str, str, str]:
    """Fetch a URL, extract clean text. Returns (text, name, url)."""
    if _is_wikipedia(url):
        text = _fetch_wikipedia(url)
    else:
        text = _fetch_generic(url)
    text = _clean_text(text)
    source_name = _name_from_url(url)
    return text, source_name, url


# ── Wikipedia ──────────────────────────────────────────────────────────────────

def _is_wikipedia(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    return "wikipedia.org" in host


def _fetch_wikipedia(url: str) -> str:
    """Use the Wikipedia API to get clean plain text — no HTML, no citations, no infobox."""
    import httpx
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    lang = parsed.netloc.split(".")[0]  # en, it, fr, de, ...
    path_parts = [p for p in parsed.path.split("/") if p]
    if len(path_parts) < 2 or path_parts[0] != "wiki":
        raise ValueError(f"Cannot parse Wikipedia URL: {url}")
    title = unquote(path_parts[1])

    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "explaintext": "1",
        "format": "json",
        "redirects": "1",
    }
    resp = httpx.get(api_url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        extract = page.get("extract", "")
        if extract:
            return extract
    raise ValueError(f"Wikipedia API returned no content for: {title}")


# ── Generic URL ────────────────────────────────────────────────────────────────

def _fetch_generic(url: str) -> str:
    """Fetch a generic URL. Tries trafilatura first, falls back to BeautifulSoup."""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # Try trafilatura — best for extracting main article content
    text = _extract_trafilatura(html)
    if text:
        return text

    # Fallback: BeautifulSoup
    return _extract_beautifulsoup(html)


def _extract_trafilatura(html: str) -> str | None:
    try:
        import trafilatura
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if text and len(text) > 200:
            return text
    except ImportError:
        pass
    return None


def _extract_beautifulsoup(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# ── Post-processing ────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Remove citation markers and normalize whitespace."""
    # Wikipedia-style citations: [1], [42], [a], [note 1], [nb 1]
    text = re.sub(r'\[\s*(?:\w+\s*)*\d+\s*\]', '', text)
    # Single-letter markers: [a], [b]
    text = re.sub(r'\[\s*[a-z]\s*\]', '', text)
    # Normalize whitespace
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _name_from_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    raw = parts[-1] if parts else parsed.netloc
    name = re.sub(r'[^a-z0-9-]', '-', raw.lower()).strip('-')
    return name or re.sub(r'[^a-z0-9-]', '-', parsed.netloc.lower())


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
