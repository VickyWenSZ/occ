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
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("httpx or beautifulsoup4 not installed. Run: pip install httpx beautifulsoup4")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)

    source_name = _name_from_url(url)
    return text, source_name, url


def _name_from_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    raw = parts[-1] if parts else parsed.netloc
    name = re.sub(r'[^a-z0-9-]', '-', raw.lower()).strip('-')
    return name or re.sub(r'[^a-z0-9-]', '-', parsed.netloc.lower())


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
