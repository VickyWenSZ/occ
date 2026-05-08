"""
Local cache for OCC server pack indices.

Cache layout: ~/.occ_cache/{pack}/wiki/index.md
The wiki/ dir mirrors the structure search.py expects as wiki_dir.
Page files are NOT stored locally — fetched on demand from the server.
"""
import asyncio
import json
import os
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import httpx

CACHE_DIR = Path.home() / ".occ_cache"
SERVER_URL = "https://broker.opencognitivecommons.org"
_TIMESTAMP_FILE = CACHE_DIR / ".last_updated"
_REFRESH_INTERVAL_HOURS = 24


def download_all_indices() -> bool:
    """Download index.md for every pack from the server.
    Returns True if at least one pack was cached successfully.
    """
    try:
        with urlopen(f"{SERVER_URL}/packs", timeout=10) as r:
            pack_names: list[str] = json.loads(r.read())
    except Exception:
        return False

    ok = False
    for pack in pack_names:
        wiki_dir = CACHE_DIR / pack / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        url = f"{SERVER_URL}/packs/{pack}/wiki/index.md"
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


def get_cached_wiki_dirs() -> list[Path]:
    """Return ~/.occ_cache/{pack}/wiki/ dirs that have a valid index.md."""
    if not CACHE_DIR.exists():
        return []
    return [
        p / "wiki"
        for p in sorted(CACHE_DIR.iterdir())
        if p.is_dir() and not p.name.startswith(".") and (p / "wiki" / "index.md").exists()
    ]


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


async def fetch_pages(page_refs: list[dict]) -> dict[str, str] | None:
    """
    Fetch page content from the server in parallel.
    page_refs: list of {pack, file}
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


