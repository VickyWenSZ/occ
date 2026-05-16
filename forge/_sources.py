"""
Source readers for OCC Forge.
Handles .txt, .md, .pdf files and URLs.
Returns (text, source_name, source_url) tuples.
"""
import re
import hashlib
from pathlib import Path


def _is_public_url(url: str) -> tuple[bool, str]:
    """SSRF guard: only allow http(s) hosts that resolve to public IPs.

    Forge fetches URLs supplied by the user (or by prompt-injected content
    on a page Forge is already crawling), so without this check a request
    like `http://127.0.0.1:7891/api/local/pack-state` would reach the local
    Node and bake its response into a pack.
    """
    from urllib.parse import urlparse
    import socket
    import ipaddress
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"invalid URL: {e}"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' not allowed"
    host = (parsed.hostname or "").strip()
    if not host:
        return False, "missing host"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        return False, f"cannot resolve host: {e}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False, f"host resolves to non-public address {addr}"
    return True, ""


def read_file(path: Path, vision_model: str | None = None) -> tuple[str, str, str]:
    """
    Read a .txt / .md / .pdf file. Returns (text, name, url).

    For PDFs, uses PyMuPDF (better extraction than pypdf — preserves columns,
    captures more layout). When `vision_model` is provided, pages with
    very low text density (likely scanned, image-only, or formula-heavy) are
    rasterized and sent to that vision model for transcription.
    """
    if path.suffix.lower() == ".pdf":
        text = _read_pdf(path, vision_model=vision_model)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    source_name = re.sub(r'[^a-z0-9-]', '-', path.stem.lower()).strip('-')
    return text, source_name, path.resolve().as_uri()


_PDF_LOW_TEXT_THRESHOLD = 200  # chars per page below which we consider vision fallback


def _read_pdf(path: Path, vision_model: str | None = None) -> str:
    """
    Extract text from a PDF using PyMuPDF.

    Strategy per page:
      1. Try `page.get_text("text")` (preserves reading order, multi-column aware)
      2. If extracted text < _PDF_LOW_TEXT_THRESHOLD chars AND vision_model is set,
         rasterize the page at 2× zoom and send to vision LLM for transcription.
         The transcription is appended below whatever pypymdf got.
      3. Concatenate all pages with `\n\n`.
    """
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError("pymupdf not installed. Run: pip install pymupdf")

    doc = pymupdf.open(str(path))
    parts: list[str] = []
    vision_pages_used = 0
    try:
        for page_idx, page in enumerate(doc):
            text = (page.get_text("text") or "").strip()

            if vision_model and len(text) < _PDF_LOW_TEXT_THRESHOLD:
                vision_text = _vision_transcribe_pdf_page(page, vision_model, page_idx + 1)
                if vision_text:
                    vision_pages_used += 1
                    if text:
                        text = f"{text}\n\n[Page {page_idx+1} vision transcription]\n{vision_text}"
                    else:
                        text = f"[Page {page_idx+1} (vision-only — low extracted text)]\n{vision_text}"

            if text:
                parts.append(text)
    finally:
        doc.close()

    return "\n\n".join(parts)


def _vision_transcribe_pdf_page(page, vision_model: str, page_number: int) -> str:
    """
    Rasterize a PyMuPDF page to PNG and send to a vision model for transcription.
    Returns transcribed text or '' on any failure (best-effort).
    """
    import tempfile
    try:
        import pymupdf
        # 2× zoom for legibility; balance between quality and payload size
        matrix = pymupdf.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        out_path = Path(tmp.name)
        pix.save(str(out_path))
    except Exception:
        return ""

    try:
        # Local import: avoid circular dep at module load
        from forge._llm import _call_vision_for_pdf_transcription
        text = _call_vision_for_pdf_transcription(out_path, page_number, model=vision_model)
        return text
    except Exception:
        return ""
    finally:
        try:
            out_path.unlink()
        except Exception:
            pass


def fetch_url(url: str, include_math: bool = False) -> tuple[str, str, str]:
    """
    Fetch a URL, extract clean text. Returns (text, name, url).

    When `include_math=True`:
      - Wikipedia: switches from API `extracts` (plain text, no formulas) to API
        `parse` (full HTML), then extracts LaTeX from `<math>` annotations and
        `<img class="mwe-math-fallback-image-inline" alt="LaTeX">`.
      - Generic URLs: also pre-processes `<math>` MathML and math fallback images
        in the HTML, replacing them with `$LaTeX$` / `$$LaTeX$$` text before
        running trafilatura. Result: formulas appear inline in the raw text.
    """
    ok, why = _is_public_url(url)
    if not ok:
        raise ValueError(f"refusing to fetch {url}: {why}")
    if _is_wikipedia(url):
        if include_math:
            text = _fetch_wikipedia_html_with_math(url)
        else:
            text = _fetch_wikipedia(url)
    else:
        text = _fetch_generic(url, include_math=include_math)
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
    resp = httpx.get(api_url, params=params, headers={"User-Agent": _WIKIPEDIA_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        extract = page.get("extract", "")
        if extract:
            return extract
    raise ValueError(f"Wikipedia API returned no content for: {title}")


def _fetch_wikipedia_html_with_math(url: str) -> str:
    """
    Fetch Wikipedia article via the `parse` API (returns HTML), rewrite math
    elements to inline LaTeX, then extract clean text. Used when the user
    enables math extraction.
    """
    import httpx
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    lang = parsed.netloc.split(".")[0]
    path_parts = [p for p in parsed.path.split("/") if p]
    if len(path_parts) < 2 or path_parts[0] != "wiki":
        raise ValueError(f"Cannot parse Wikipedia URL: {url}")
    title = unquote(path_parts[1])

    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "page":   title,
        "prop":   "text",
        "format": "json",
        "redirects": "1",
        "disableeditsection": "1",
        "disabletoc": "1",
    }
    resp = httpx.get(api_url, params=params, headers={"User-Agent": _WIKIPEDIA_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    html = data.get("parse", {}).get("text", {}).get("*", "")
    if not html:
        raise ValueError(f"Wikipedia parse API returned no HTML for: {title}")

    html = _rewrite_math_in_html(html)
    return _extract_beautifulsoup(html)


# ── Math extraction ────────────────────────────────────────────────────────────

_MATH_DISPLAY_HINT_CLASSES = ("mwe-math-fallback-image-display",)
_MATH_INLINE_HINT_CLASSES  = ("mwe-math-fallback-image-inline",)


def _rewrite_math_in_html(html: str) -> str:
    """
    In-place rewrite of math elements in an HTML string to inline LaTeX text:
      - <math>...<annotation encoding="application/x-tex">LaTeX</annotation></math>
        → ` $LaTeX$ ` (or `$$LaTeX$$` if display="block")
      - <img class="mwe-math-fallback-image-inline" alt="LaTeX">       → ` $LaTeX$ `
      - <img class="mwe-math-fallback-image-display" alt="LaTeX">      → ` $$LaTeX$$ `

    Returns the modified HTML. If BeautifulSoup is unavailable, returns html unchanged.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html
    if not html or "<" not in html:
        return html

    soup = BeautifulSoup(html, "html.parser")

    # MathML <math> elements with LaTeX annotation
    for math_el in soup.find_all("math"):
        latex = None
        ann = math_el.find("annotation", attrs={"encoding": "application/x-tex"})
        if ann and ann.get_text(strip=True):
            latex = ann.get_text(strip=True)
        else:
            # Some pages put the LaTeX in an `alttext` attribute on the <math> root
            alt = math_el.get("alttext")
            if alt:
                latex = alt.strip()
        if not latex:
            math_el.decompose()
            continue
        is_display = (math_el.get("display") == "block")
        wrapped = f" $$ {latex} $$ " if is_display else f" $ {latex} $ "
        math_el.replace_with(wrapped)

    # Wikipedia math fallback images (alt contains the LaTeX source)
    for img in soup.find_all("img"):
        cls = img.get("class") or []
        alt = (img.get("alt") or "").strip()
        if not alt:
            continue
        if any(c in cls for c in _MATH_DISPLAY_HINT_CLASSES):
            img.replace_with(f" $$ {alt} $$ ")
        elif any(c in cls for c in _MATH_INLINE_HINT_CLASSES):
            img.replace_with(f" $ {alt} $ ")

    return str(soup)


# ── Generic URL ────────────────────────────────────────────────────────────────

def _fetch_generic(url: str, include_math: bool = False) -> str:
    """Fetch a generic URL. Uses trafilatura's fetcher (realistic headers),
    falls back to httpx + BeautifulSoup if trafilatura is unavailable or blocked.

    When include_math=True, math elements in the HTML are rewritten to inline
    `$LaTeX$` / `$$LaTeX$$` text BEFORE extraction, so formulas survive."""

    # Primary: trafilatura fetch + extract (best headers, best content extraction)
    try:
        import trafilatura
        html = trafilatura.fetch_url(url)
        if html:
            html_in = _rewrite_math_in_html(html) if include_math else html
            text = trafilatura.extract(
                html_in,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if text and len(text) > 200:
                return text
    except ImportError:
        pass

    # Fallback: httpx + BeautifulSoup
    import httpx
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    html = _rewrite_math_in_html(resp.text) if include_math else resp.text
    return _extract_beautifulsoup(html)


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


# ── Image fetching (Phase 1 — URL ingestion only) ─────────────────────────────

_IMG_MIN_BYTES = 5 * 1024            # 5 KB — filter icons/spacers/tracking pixels
_IMG_MAX_PER_SOURCE = 20             # cap LLM calls per source
_IMG_ACCEPTED_EXT = {".jpg", ".jpeg", ".png", ".webp"}  # raster, vision-friendly
_USER_AGENT = (
    "OCC-Forge/0.1 (+https://github.com/VickyWenSZ/occ; vickywensz@gmail.com)"
)

# Wikipedia / WMF endpoints reject generic UAs (403). Identify the tool per
# https://meta.wikimedia.org/wiki/User-Agent_policy
_WIKIPEDIA_USER_AGENT = (
    "OCC-Forge/0.1 (https://github.com/VickyWenSZ/occ; vickywensz@gmail.com) httpx"
)


def fetch_images_from_url(url: str, dest_dir: Path) -> list[dict]:
    """
    Fetch an HTML page, extract <img> elements, download images larger than
    _IMG_MIN_BYTES into dest_dir as img-1.ext, img-2.ext, ...

    Returns list of {filename, path, alt, src_url, ext}.
    Returns [] for Wikipedia URLs (the API path doesn't expose images cleanly)
    and on any fetch failure (best-effort, never raises).

    Caller is responsible for invoking this only for URL sources.
    """
    ok, _why = _is_public_url(url)
    if not ok:
        return []
    if _is_wikipedia(url):
        return []

    import httpx
    from urllib.parse import urljoin
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    try:
        resp = httpx.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return []

    candidates: list[tuple[str, str]] = []  # (absolute_url, alt_text)
    seen_urls: set[str] = set()
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
        if not src:
            continue
        absolute = urljoin(url, src.strip())
        if absolute in seen_urls or absolute.startswith("data:"):
            continue
        seen_urls.add(absolute)
        alt = (tag.get("alt") or "").strip()
        candidates.append((absolute, alt))

    if not candidates:
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    n = 0
    for abs_url, alt in candidates:
        if n >= _IMG_MAX_PER_SOURCE:
            break
        result = _download_image(abs_url, alt, dest_dir, n + 1)
        if result is not None:
            saved.append(result)
            n += 1
    return saved


def _download_image(url: str, alt: str, dest_dir: Path, idx: int) -> dict | None:
    """Download a single image. Skip if <5KB or wrong content type. Return entry or None."""
    import httpx
    from urllib.parse import urlparse
    ok, _why = _is_public_url(url)
    if not ok:
        return None

    # Determine extension from URL path
    parsed = urlparse(url)
    url_path = parsed.path.lower()
    ext = None
    for accepted in _IMG_ACCEPTED_EXT:
        if url_path.endswith(accepted):
            ext = accepted
            break
    # Some URLs hide extension behind query params or use jpeg without extension
    if ext is None and not any(url_path.endswith(e) for e in (".gif", ".svg", ".bmp", ".ico", ".tif", ".tiff")):
        # Allow it through; we'll re-check via Content-Type after fetching
        ext = ""

    if ext is None:
        return None  # known unsupported (svg, gif, etc.)

    try:
        r = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "image/*"},
            follow_redirects=True,
            timeout=30,
        )
        r.raise_for_status()
    except Exception:
        return None

    data = r.content
    if len(data) < _IMG_MIN_BYTES:
        return None

    # If we couldn't determine extension from URL, infer from Content-Type
    if not ext:
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ct_map = {
            "image/jpeg": ".jpg",
            "image/jpg":  ".jpg",
            "image/png":  ".png",
            "image/webp": ".webp",
        }
        ext = ct_map.get(ct)
        if not ext:
            return None

    filename = f"img-{idx}{ext}"
    out_path = dest_dir / filename
    try:
        out_path.write_bytes(data)
    except Exception:
        return None

    return {
        "filename": filename,
        "path":     out_path,
        "alt":      alt,
        "src_url":  url,
        "ext":      ext,
        "size":     len(data),
    }
