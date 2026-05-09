"""
Local cache for OCC server pack indices.

Cache layout: ~/.occ_cache/{pack_path}/wiki/index.md
For nested packs (e.g., history/prehistory), the cache mirrors the tree:
  ~/.occ_cache/history/prehistory/wiki/index.md

Page files are NOT stored locally — fetched on demand from the server.
"""
import asyncio
import json
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import httpx

CACHE_DIR = Path.home() / ".occ_cache"
SERVER_URL = "https://broker.opencognitivecommons.org"
_TIMESTAMP_FILE = CACHE_DIR / ".last_updated"
_REFRESH_INTERVAL_HOURS = 24


# ─── Tree traversal ───────────────────────────────────────────────────────────

def _walk_tree(parent_path: str, children: list, packs: list, depth: int = 0) -> None:
    if depth > 6:
        return
    for child in children:
        path = f"{parent_path}/{child}" if parent_path else child
        try:
            with urlopen(f"{SERVER_URL}/tree/{path}", timeout=5) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        if data.get("has_pack"):
            packs.append(path)
        sub_children = data.get("children", [])
        if sub_children:
            _walk_tree(path, sub_children, packs, depth + 1)


def _enumerate_packs_from_tree() -> list[str]:
    """Walk the broker tree and return all pack paths that have a wiki/index.md."""
    try:
        with urlopen(f"{SERVER_URL}/tree", timeout=10) as r:
            top_level: list[str] = json.loads(r.read())
    except Exception:
        return []
    packs: list[str] = []
    _walk_tree("", top_level, packs)
    return packs


# ─── Index download ───────────────────────────────────────────────────────────

def download_all_indices() -> bool:
    """Download index.md for every pack from the server (tree-based).
    Returns True if at least one pack was cached successfully.
    """
    pack_paths = _enumerate_packs_from_tree()

    # Fallback: flat /packs list for servers without /tree
    if not pack_paths:
        try:
            with urlopen(f"{SERVER_URL}/packs", timeout=10) as r:
                pack_paths = json.loads(r.read())
        except Exception:
            return False

    ok = False
    for pack_path in pack_paths:
        wiki_dir = CACHE_DIR / pack_path / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        url = f"{SERVER_URL}/packs/{pack_path}/wiki/index.md"
        dest = wiki_dir / "index.md"
        try:
            with urlopen(url, timeout=10) as r:
                dest.write_bytes(r.read())
            ok = True
        except Exception:
            continue

    if ok:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _TIMESTAMP_FILE.write_text(str(time.time()))
    return ok


def ensure_pack_cached(pack_path: str) -> bool:
    """Download index.md for a specific pack path if not already cached.
    Returns True if index is available (cached or just downloaded).
    """
    wiki_dir = CACHE_DIR / pack_path / "wiki"
    dest = wiki_dir / "index.md"
    if dest.exists():
        age_secs = time.time() - dest.stat().st_mtime
        if age_secs < _REFRESH_INTERVAL_HOURS * 3600:
            return True
    wiki_dir.mkdir(parents=True, exist_ok=True)
    url = f"{SERVER_URL}/packs/{pack_path}/wiki/index.md"
    try:
        with urlopen(url, timeout=10) as r:
            dest.write_bytes(r.read())
        return True
    except Exception:
        return dest.exists()  # stale copy is better than nothing


# ─── Cache inspection ─────────────────────────────────────────────────────────

def _find_wiki_dirs(directory: Path, result: list) -> None:
    for p in sorted(directory.iterdir()):
        if p.name.startswith(".") or not p.is_dir():
            continue
        if p.name == "wiki":
            if (p / "index.md").exists():
                result.append(p)
        else:
            _find_wiki_dirs(p, result)


def get_cached_wiki_dirs() -> list[Path]:
    """Return all ~/.occ_cache/.../wiki/ dirs that have a valid index.md (recursive)."""
    if not CACHE_DIR.exists():
        return []
    result: list[Path] = []
    _find_wiki_dirs(CACHE_DIR, result)
    return result


def is_stale(pack_name: str, max_age_hours: int = _REFRESH_INTERVAL_HOURS) -> bool:
    """Return True if the cached index for pack_name is missing or older than max_age_hours."""
    index_file = CACHE_DIR / pack_name / "wiki" / "index.md"
    if not index_file.exists():
        return True
    age_secs = time.time() - index_file.stat().st_mtime
    return age_secs > max_age_hours * 3600


def start_refresh_thread() -> None:
    """Start a daemon thread that refreshes all indices every 24h."""
    def _loop() -> None:
        while True:
            try:
                stale = (
                    not _TIMESTAMP_FILE.exists()
                    or time.time() - float(_TIMESTAMP_FILE.read_text()) > _REFRESH_INTERVAL_HOURS * 3600
                )
                if stale:
                    download_all_indices()
            except Exception:
                pass
            time.sleep(3600)
    threading.Thread(target=_loop, daemon=True, name="occ-cache-refresh").start()


# ─── Page fetching ────────────────────────────────────────────────────────────

async def fetch_pages(page_refs: list[dict]) -> dict[str, str] | None:
    """
    Fetch page content from the server in parallel.
    page_refs: list of {pack, file}  — pack may be a nested path like "history/prehistory"
    Returns {file: content} or None if the server is unreachable.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [
            client.get(f"{SERVER_URL}/packs/{ref['pack']}/wiki/{ref['file']}")
            for ref in page_refs
        ]
        try:
            responses = await asyncio.gather(*tasks)
            return {
                ref["file"]: resp.text
                for ref, resp in zip(page_refs, responses)
                if resp.status_code == 200
            }
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
