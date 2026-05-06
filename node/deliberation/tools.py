"""
OCC tool registry — explicit user-triggered tools only.
Tools are never called autonomously; they require explicit user intent.
File operations are sandboxed to the workspace/ directory inside the OCC repo.
"""

import re
from pathlib import Path

_WORKSPACE: Path | None = None


def set_workspace(path: Path):
    global _WORKSPACE
    _WORKSPACE = path


def _safe_path(filename: str) -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("Workspace not initialized.")
    resolved = (_WORKSPACE / filename).resolve()
    if not str(resolved).startswith(str(_WORKSPACE.resolve())):
        raise ValueError(f"Path '{filename}' escapes the workspace.")
    return resolved

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
    import requests
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Trim to avoid flooding context
        return text[:8000] if len(text) > 8000 else text
    except Exception as e:
        return f"Could not fetch URL: {e}"


def read_file(filename: str) -> str:
    try:
        path = _safe_path(filename)
        if not path.exists():
            return f"File '{filename}' not found in workspace."
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

TOOL_FUNCTIONS = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "run_code": run_code,
}
