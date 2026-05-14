"""
OCC tool registry — explicit user-triggered tools only.
Tools are never called autonomously; they require explicit user intent.
File operations are sandboxed to the workspace/ directory inside the OCC repo.
"""

import re
from pathlib import Path

_WORKSPACE: Path | None = None
_UPLOAD: Path | None = None


def set_workspace(path: Path):
    global _WORKSPACE
    _WORKSPACE = path


def set_upload(path: Path):
    global _UPLOAD
    _UPLOAD = path


def _safe_path(filename: str) -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("Workspace not initialized.")
    resolved = (_WORKSPACE / filename).resolve()
    if not str(resolved).startswith(str(_WORKSPACE.resolve())):
        raise ValueError(f"Path '{filename}' escapes the workspace.")
    return resolved


def _safe_upload_path(filename: str) -> Path:
    if _UPLOAD is None:
        raise RuntimeError("Upload folder not initialized.")
    resolved = (_UPLOAD / filename).resolve()
    if not str(resolved).startswith(str(_UPLOAD.resolve())):
        raise ValueError(f"Path '{filename}' escapes the upload folder.")
    return resolved


def list_upload_files() -> list[str]:
    """Return filenames currently in the upload folder, excluding dotfiles
    and .gitkeep. Used by skills that need to enumerate user-uploaded files."""
    if _UPLOAD is None or not _UPLOAD.exists():
        return []
    return sorted(
        f.name for f in _UPLOAD.iterdir()
        if f.is_file() and not f.name.startswith(".")
    )

_URL_RE = re.compile(r'https?://\S+')

# Language-agnostic single keywords
_TOOL_KEYWORDS = {"web", "online", "internet", "workspace", "url", "file"}

# Phrases that clearly signal tool intent
_TOOL_PHRASES = {
    # web search
    "search the web", "search online", "look up online",
    "find online", "web search", "browse the web",
    "latest news", "current news", "news about",
    # file operations
    "write file", "write a file", "create file", "create a file",
    "save file", "save to file", "save as",
    "read file", "open file", "load file",
    "list files", "show files", "list the files",
    "in workspace", "to workspace", "into workspace",
    # code execution
    "run code", "execute code", "run this code", "run the code",
    "run script", "execute script",
}


def is_tool_request(query: str) -> bool:
    """True if the query explicitly requests a tool (web, file, or code execution)."""
    q = query.lower()
    if _URL_RE.search(query):
        return True
    if any(p in q for p in _TOOL_PHRASES):
        return True
    words = set(re.findall(r'\b\w+\b', q))
    return bool(words & _TOOL_KEYWORDS)


# ── Web-tool gating ────────────────────────────────────────────────────────────
# OCC's design rule: knowledge must come from community-approved expert packs.
# Web tools (web_search, fetch_url) bypass that guarantee, so they are exposed
# to the model ONLY when the user explicitly invokes the web.

WEB_TOOL_NAMES = frozenset({"web_search", "fetch_url"})

_WEB_KEYWORDS = {"web", "online", "internet"}
_WEB_PHRASES = {
    "search the web", "search online", "look up online", "find online",
    "web search", "browse the web", "browse online",
    "latest news", "current news", "news about",
    "cerca sul web", "cerca online", "cerca su internet",
    "su internet", "sul web",
}


def is_web_request(query: str) -> bool:
    """True iff the user explicitly invokes the web. URL in the message counts as explicit consent."""
    q = (query or "").lower()
    if _URL_RE.search(query or ""):
        return True
    if any(p in q for p in _WEB_PHRASES):
        return True
    words = set(re.findall(r'\b\w+\b', q))
    return bool(words & _WEB_KEYWORDS)


def get_allowed_tools(query: str) -> tuple[list, frozenset]:
    """
    Return (schema, allowed_function_names) for the given user query.
    Web tools (web_search, fetch_url) are stripped unless the query explicitly
    invokes the web. Other tools are always available.
    """
    if is_web_request(query):
        return TOOL_SCHEMA, frozenset(TOOL_FUNCTIONS.keys())
    schema = [t for t in TOOL_SCHEMA if t["function"]["name"] not in WEB_TOOL_NAMES]
    allowed = frozenset(TOOL_FUNCTIONS.keys()) - WEB_TOOL_NAMES
    return schema, allowed


def web_search(query: str, max_results: int = 5) -> str:
    from ddgs import DDGS
    results = DDGS().text(query, max_results=max_results)
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r['title']}**\n{r['body']}\nSource: {r['href']}\n")
    return "\n".join(lines)


def fetch_url(url: str) -> str:
    """Fetch a URL and return its main text content.

    Two-stage extraction:
      1. trafilatura (best-quality main-content extraction).
      2. If trafilatura returns nothing (JS-heavy SPA, paywall stub, etc.),
         fall back to a crude HTML strip so we at least return *some* text
         instead of an empty result.
    """
    import re
    import httpx
    import trafilatura
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OCC/1.0)",
                "Accept-Language": "it,en;q=0.9",
            },
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code} on {url}"
    except httpx.TimeoutException:
        return f"Timeout fetching {url} (15s)"
    except Exception as e:
        return f"Could not fetch URL ({type(e).__name__}): {e}"

    html = resp.text
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    if text.strip():
        return text[:8000] if len(text) > 8000 else text

    # Fallback: trafilatura returned empty (paywall, SPA, anti-bot stub).
    # Strip script/style blocks then strip remaining tags.
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return f"Could not extract readable text from {url} (page returned empty after both extractors)."
    # Tag the fallback so Qwen knows this is rough
    return ("[fallback extraction — main-content extractor returned empty]\n"
            + (cleaned[:8000] if len(cleaned) > 8000 else cleaned))


def read_file(filename: str) -> str:
    try:
        path = _safe_upload_path(filename)
        if not path.exists():
            return f"File '{filename}' not found in upload folder."
        return path.read_text(encoding="utf-8")
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(filename: str, content: str) -> str:
    try:
        path = _safe_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"File '{filename}' written successfully."
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error writing file: {e}"


def list_files(subdir: str = "") -> str:
    try:
        base = _safe_path(subdir) if subdir else _WORKSPACE
        if not base.exists():
            return f"Directory '{subdir}' not found in workspace."
        entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))
        if not entries:
            return "Workspace is empty."
        lines = []
        for p in entries:
            if p.name == ".gitkeep":
                continue
            marker = "/" if p.is_dir() else ""
            lines.append(f"  {p.name}{marker}")
        return "Workspace contents:\n" + "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error listing files: {e}"


def run_code(code: str) -> str:
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_WORKSPACE),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: code execution timed out (30s limit)."
    except Exception as e:
        return f"Error running code: {e}"


# ── Document readers (PDF / DOCX / XLSX) ───────────────────────────────────────

_DOC_READ_LIMIT = 6000  # max chars returned to keep tool result inside chat ctx


def read_pdf(filename: str) -> str:
    try:
        path = _safe_upload_path(filename)
        if not path.exists():
            return f"File '{filename}' not found in upload folder."
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        try:
            parts = []
            total = 0
            for page in doc:
                t = page.get_text()
                if not t:
                    continue
                parts.append(t)
                total += len(t)
                if total >= _DOC_READ_LIMIT:
                    break
            text = "\n\n".join(parts)
        finally:
            doc.close()
        if not text.strip():
            return f"PDF '{filename}' has no extractable text (possibly scanned)."
        if len(text) > _DOC_READ_LIMIT:
            text = text[:_DOC_READ_LIMIT] + "\n\n[...truncated]"
        return text
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error reading PDF: {e}"


def read_docx(filename: str) -> str:
    try:
        path = _safe_upload_path(filename)
        if not path.exists():
            return f"File '{filename}' not found in upload folder."
        from docx import Document
        doc = Document(str(path))
        parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                parts.append(" | ".join(cells))
        text = "\n".join(parts)
        if not text.strip():
            return f"Document '{filename}' is empty."
        if len(text) > _DOC_READ_LIMIT:
            text = text[:_DOC_READ_LIMIT] + "\n\n[...truncated]"
        return text
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error reading docx: {e}"


def read_xlsx(filename: str) -> str:
    try:
        path = _safe_upload_path(filename)
        if not path.exists():
            return f"File '{filename}' not found in upload folder."
        from openpyxl import load_workbook
        wb = load_workbook(str(path), data_only=True, read_only=True)
        try:
            parts = []
            running = 0
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                header = f"--- Sheet: {sheet_name} ---"
                parts.append(header)
                running += len(header)
                for row in sheet.iter_rows(values_only=True):
                    row_str = "\t".join("" if v is None else str(v) for v in row)
                    if not row_str.strip():
                        continue
                    parts.append(row_str)
                    running += len(row_str)
                    if running >= _DOC_READ_LIMIT:
                        break
                if running >= _DOC_READ_LIMIT:
                    break
        finally:
            wb.close()
        text = "\n".join(parts)
        if not text.strip():
            return f"Workbook '{filename}' is empty."
        if len(text) > _DOC_READ_LIMIT:
            text = text[:_DOC_READ_LIMIT] + "\n\n[...truncated]"
        return text
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error reading xlsx: {e}"


# ── Audio transcription (Whisper) ──────────────────────────────────────────────

_WHISPER_MODEL = None


def _get_whisper_model():
    """Lazy-load the Whisper model; downloaded once on first use."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        import os
        from faster_whisper import WhisperModel
        model_size = os.environ.get("OCC_WHISPER_MODEL", "base")
        device = os.environ.get("OCC_WHISPER_DEVICE", "cpu")
        compute_type = "int8" if device == "cpu" else "float16"
        _WHISPER_MODEL = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _WHISPER_MODEL


def transcribe_audio(filename: str) -> str:
    try:
        path = _safe_upload_path(filename)
        if not path.exists():
            return f"Audio file '{filename}' not found in upload folder."
        model = _get_whisper_model()
        segments, info = model.transcribe(str(path), beam_size=5)
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        if not parts:
            return f"No speech detected in '{filename}'."
        text = " ".join(parts)
        return f"[language: {info.language}, duration: {info.duration:.1f}s]\n\n{text}"
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error transcribing audio: {e}"


TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Use when the user asks to search online.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the content of a specific web page. Use when the user provides a URL or asks to read a page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_SCHEMA += [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename or relative path within workspace"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or create a file in the workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename or relative path within workspace"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]

TOOL_SCHEMA += [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in the workspace. Use when the user asks what files exist or before reading a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {"type": "string", "description": "Optional subdirectory within workspace (leave empty for root)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": "Execute a Python code snippet and return its output. The working directory is the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                },
                "required": ["code"],
            },
        },
    },
]

TOOL_SCHEMA += [
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Read text content from a PDF file in the upload folder. Use when the user asks to read, summarize, or answer questions about a PDF document they attached.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename of the uploaded PDF (e.g. 'report.pdf')"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_docx",
            "description": "Read text content from a Microsoft Word .docx file in the upload folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename of the uploaded .docx (e.g. 'document.docx')"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_xlsx",
            "description": "Read cell contents from a Microsoft Excel .xlsx file in the upload folder. Returns all sheets with rows as tab-separated values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename of the uploaded .xlsx (e.g. 'data.xlsx')"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transcribe_audio",
            "description": "Transcribe an audio file in the upload folder to text using Whisper. Supports common formats (mp3, wav, m4a, ogg, flac).",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename of the uploaded audio (e.g. 'recording.mp3')"},
                },
                "required": ["filename"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "run_code": run_code,
    "read_pdf": read_pdf,
    "read_docx": read_docx,
    "read_xlsx": read_xlsx,
    "transcribe_audio": transcribe_audio,
}
