"""
Local FTS5 search index over expert-packs/. Sibling (NOT replacement) of the
broker in node/server/broker.py — same SQL shape, same query semantics, but
reads directly from disk so the local retrieval pipeline doesn't need an HTTP
server.

Pack layout supported (both, mixed):
  - Flat:        expert-packs/<pack>/{manifest.yaml, wiki/index.md, ...}
  - Hierarchical: expert-packs/<category>/.../<pack>/{manifest.yaml, ...}
  - Mixed:       both at the same time

A directory is a "pack" iff it contains BOTH manifest.yaml AND wiki/index.md.
Anything else along the path is a "category" (purely organizational).

The index DB lives at INDEX_DB_PATH (a single SQLite file). reindex_all
rebuilds it from scratch; ensure_index_ready blocks the caller until the
first build is done. The broker's schema is mirrored exactly so the same
queries return rows with the same shape.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

import yaml

# ── Configuration ─────────────────────────────────────────────────────────────

INDEX_DB_PATH = Path.home() / ".occ_local_index" / "index.db"

# Schema version mirrors the broker's. Bump together with broker._SCHEMA_VERSION
# only if the table shape changes — the column order here MUST match broker.
_SCHEMA_VERSION = 3

# Body-indexing budget: same as broker._BODY_INDEX_CHARS so BM25 ranks behave
# identically locally and remotely.
_BODY_INDEX_CHARS = 2000

# ── Concurrency state ─────────────────────────────────────────────────────────

_INDEX_LOCK = threading.Lock()
_INDEX_READY = threading.Event()
_INDEX_BUILDING = False
_INDEX_PACKS_ROOT: Path | None = None  # remember last-indexed root for ensure_index_ready


# ── DB plumbing (mirrors broker._open_db / _init_db) ──────────────────────────

def _open_db() -> sqlite3.Connection:
    INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(INDEX_DB_PATH))


def _init_db() -> None:
    """Create the FTS5 table if missing, or rebuild it when the stored schema
    version is older than _SCHEMA_VERSION (DROP + CREATE)."""
    conn = _open_db()
    try:
        cur = conn.execute("PRAGMA user_version")
        current = cur.fetchone()[0]
        if current < _SCHEMA_VERSION:
            conn.execute("DROP TABLE IF EXISTS pack_pages")
            conn.execute("""
                CREATE VIRTUAL TABLE pack_pages USING fts5(
                    pack_path,
                    page_file,
                    title,
                    summary,
                    pack_summary,
                    body,
                    tokenize='trigram'
                )
            """)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


# ── Pack discovery ────────────────────────────────────────────────────────────

def _walk_packs(packs_root: Path) -> list[tuple[str, Path]]:
    """Find every (pack_path, pack_dir) under packs_root.

    A pack is any directory that contains BOTH `manifest.yaml` and
    `wiki/index.md`. pack_path is the slash-form path relative to packs_root
    (e.g. "caesar" for flat, "history/ancient-rome" for nested).
    """
    out: list[tuple[str, Path]] = []
    if not packs_root.exists():
        return out
    for index_path in packs_root.rglob("wiki/index.md"):
        pack_dir = index_path.parent.parent
        if not (pack_dir / "manifest.yaml").exists():
            continue
        try:
            rel = pack_dir.resolve().relative_to(packs_root.resolve())
        except ValueError:
            continue
        pack_path = str(rel).replace("\\", "/")
        out.append((pack_path, pack_dir))
    return out


# ── index.md parsing (mirrors broker._parse_index_md) ─────────────────────────

_INDEX_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$")


def _parse_index_md(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.startswith("|"):
            continue
        m = _INDEX_ROW_RE.match(line)
        if not m:
            continue
        page_file = m.group(1).strip()
        title = m.group(2).strip()
        summary = m.group(3).strip()
        if page_file.lower() == "file" or page_file.startswith("-"):
            continue
        if not page_file or not title:
            continue
        rows.append({"page_file": page_file, "title": title, "summary": summary})
    return rows


def _read_pack_summary(pack_dir: Path) -> str:
    mf_path = pack_dir / "manifest.yaml"
    if not mf_path.exists():
        return ""
    try:
        data = yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
        return str(data.get("summary", "") or "")
    except Exception:
        return ""


def _read_page_body(page_path: Path, max_chars: int = _BODY_INDEX_CHARS) -> str:
    """Read a page .md and strip frontmatter; return up to max_chars of body."""
    try:
        text = page_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return text[:max_chars]


# ── Indexing (mirrors broker._reindex_all, single-pack variant kept simple) ───

def reindex_all(packs_root: Path, only_pack: str | None = None) -> dict:
    """Rebuild the local FTS5 index. Idempotent.

    When `only_pack` is given, replace just that pack's rows (incremental).
    Otherwise wipe and rebuild everything (full rebuild).
    """
    _init_db()
    conn = _open_db()
    try:
        if only_pack:
            conn.execute("DELETE FROM pack_pages WHERE pack_path = ?", (only_pack,))
            packs = [
                (p, d) for (p, d) in _walk_packs(packs_root) if p == only_pack
            ]
        else:
            conn.execute("DELETE FROM pack_pages")
            packs = _walk_packs(packs_root)
        rows_inserted = 0
        for pack_path, pack_dir in packs:
            wiki_dir = pack_dir / "wiki"
            index_path = wiki_dir / "index.md"
            try:
                text = index_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            pack_summary = _read_pack_summary(pack_dir)
            for row in _parse_index_md(text):
                page_body = _read_page_body(wiki_dir / row["page_file"])
                conn.execute(
                    "INSERT INTO pack_pages (pack_path, page_file, title, summary, pack_summary, body) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        pack_path,
                        row["page_file"],
                        row["title"],
                        row["summary"],
                        pack_summary,
                        page_body,
                    ),
                )
                rows_inserted += 1
        conn.commit()
        return {"packs_indexed": len(packs), "pages_indexed": rows_inserted}
    finally:
        conn.close()


def reindex_pack(packs_root: Path, pack_path: str) -> dict:
    """Convenience wrapper around reindex_all(only_pack=...) for hooks fired
    at the end of Forge / Lint runs. Errors are swallowed and reported via
    the return dict so a failing reindex never crashes the host run."""
    try:
        return reindex_all(packs_root, only_pack=pack_path)
    except Exception as e:
        return {"packs_indexed": 0, "pages_indexed": 0, "error": str(e)}


# ── Search (mirrors broker._search_packs / _fts_escape) ───────────────────────

def _fts_escape(q: str) -> str:
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    if not words:
        return q
    return " OR ".join(f'"{w}"' for w in words)


def search(
    q: str,
    k: int = 10,
    scope: str = "",
    disabled_packs: list[str] | None = None,
) -> list[dict]:
    """Run an FTS5 query and return top-K results ranked by BM25 — same shape
    as broker /search response. Empty list on any error or empty query.

    `disabled_packs` is an optional list of pack_paths to exclude from the
    results (UI toggle "Unload" some packs). The index stays full; filtering
    happens at query time via SQL, so toggling is instantaneous.
    """
    if not q.strip():
        return []
    try:
        conn = _open_db()
    except Exception:
        return []
    try:
        clauses = ["pack_pages MATCH ?"]
        params: list = [_fts_escape(q)]
        if scope:
            clauses.append("(pack_path = ? OR pack_path LIKE ?)")
            params.extend([scope, f"{scope}/%"])
        if disabled_packs:
            placeholders = ",".join("?" for _ in disabled_packs)
            clauses.append(f"pack_path NOT IN ({placeholders})")
            params.extend(disabled_packs)
        sql = (
            "SELECT pack_path, page_file, title, summary, pack_summary, rank "
            "FROM pack_pages "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY rank LIMIT ?"
        )
        params.append(k)
        cursor = conn.execute(sql, params)
        return [
            {
                "pack_path": row[0],
                "page_file": row[1],
                "title": row[2],
                "summary": row[3],
                "pack_summary": row[4],
                "score": row[5],
            }
            for row in cursor.fetchall()
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def list_pack_paths(packs_root: Path) -> list[str]:
    """Return every pack_path on disk (sorted). Used by the UI and the engine
    to compute which domains contain at least one enabled pack."""
    return sorted(p for (p, _d) in _walk_packs(packs_root))


def list_pack_summaries(packs_root: Path) -> dict[str, str]:
    """Return {pack_path: summary} for every pack on disk. Summary comes from
    each pack's manifest.yaml `summary` field (empty string if missing or
    unreadable). Used by the engine's decompose step to disambiguate domain
    selection — without summaries Qwen picks packs by literal name overlap
    (e.g. 'open-cognitive-commons' bleeds into psychology queries because the
    name contains 'cognitive')."""
    out: dict[str, str] = {}
    for pack_path, pack_dir in _walk_packs(packs_root):
        summary = _read_pack_summary(pack_dir)
        if summary:
            out[pack_path] = summary
    return out


# ── Tree (mirrors broker /tree and /tree/{path}) ──────────────────────────────

_TREE_SKIP_NAMES = {"wiki", "raw", "_refs"}


def tree(packs_root: Path, path: str = ""):
    """Mirror the broker's tree endpoints.

    - At the root (path=""): returns `list[str]` of top-level child names.
    - At a sub-path: returns `{"children": list[str], "has_pack": bool}`.

    Hidden dirs and pack-internal dirs (wiki/, raw/, _refs/) are excluded
    from `children` so the tree mirrors the broker's domain/category view.
    """
    if not packs_root.exists():
        return [] if not path else {"children": [], "has_pack": False}

    target = packs_root if not path else packs_root / path
    if not target.exists() or not target.is_dir():
        if not path:
            return []
        return {"children": [], "has_pack": False}

    children = sorted(
        d.name
        for d in target.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in _TREE_SKIP_NAMES
    )

    if not path:
        return children

    has_pack = (target / "manifest.yaml").exists() and (target / "wiki" / "index.md").exists()
    return {"children": children, "has_pack": has_pack}


# ── Direct file reads (replacing broker's /packs/.../wiki/... endpoints) ──────

def read_index(packs_root: Path, pack_path: str) -> str:
    p = packs_root / pack_path / "wiki" / "index.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_page(packs_root: Path, pack_path: str, page_file: str) -> str:
    p = packs_root / pack_path / "wiki" / page_file
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# ── Lifecycle: lazy build + background warm-up ────────────────────────────────

def ensure_index_ready(packs_root: Path) -> None:
    """Block until the index has been built at least once for this packs_root.

    Cheap fast-path when the index is already warm. Re-entrant: many threads
    can call this; only the first runs the actual reindex, the others wait
    on the ready Event.
    """
    global _INDEX_BUILDING, _INDEX_PACKS_ROOT

    # Fast path
    if _INDEX_READY.is_set() and _INDEX_PACKS_ROOT == packs_root:
        return

    must_build = False
    with _INDEX_LOCK:
        if _INDEX_READY.is_set() and _INDEX_PACKS_ROOT == packs_root:
            return
        if not _INDEX_BUILDING:
            _INDEX_BUILDING = True
            _INDEX_READY.clear()
            _INDEX_PACKS_ROOT = packs_root
            must_build = True

    if must_build:
        try:
            reindex_all(packs_root)
        finally:
            with _INDEX_LOCK:
                _INDEX_BUILDING = False
            _INDEX_READY.set()
    else:
        _INDEX_READY.wait()


def start_background_reindex(packs_root: Path) -> None:
    """Kick off an index build in a daemon thread, non-blocking. The first
    local-mode query will either find the index already built, or block on
    ensure_index_ready until the build completes."""
    def _run():
        try:
            ensure_index_ready(packs_root)
        except Exception:
            pass

    threading.Thread(
        target=_run,
        daemon=True,
        name="occ-local-reindex",
    ).start()
