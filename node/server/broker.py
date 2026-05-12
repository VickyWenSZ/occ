"""
OCC Broker — WebSocket broker + HTTP file serving + pack search

Deploy: /opt/occ-broker/broker.py
Run:    uvicorn broker:app --host 0.0.0.0 --port 8000
Env:    OCC_REINDEX_TOKEN  (required for /admin/reindex)

Security status — alpha. See SECURITY.md at the repo root for full threat model.
- Public-by-design endpoints (unauthenticated): /tree, /packs/*, /search, /nodes.
  Pack content is community-approved and meant to be world-readable.
- Token-protected: /admin/reindex (X-OCC-Token header, OCC_REINDEX_TOKEN env).
- Defensive measures in place:
    * /search rate-limited per client IP (sliding window, see _check_rate_limit).
    * `nodes` and `pending_queries` dicts have hard caps to bound memory.
- Known gaps pending Sprint 4 PKI hardening:
    * /ws `register` accepts any node_id and self-declared VRAM without signing.
    * /admin/reindex token is a single static value (no rotation).
  Do NOT run this broker in production without the hardening track.
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()

PACKS_DIR = Path("/opt/occ-packs")
SEARCH_DB = Path("/opt/occ-broker/pack_search.db")
_NODE_TIMEOUT = 90  # seconds
_REINDEX_TOKEN = os.environ.get("OCC_REINDEX_TOKEN", "")

# FTS5 schema version — bump when columns or tokenizer change to force a rebuild.
# Migration runs in _init_db() via PRAGMA user_version (DROP+CREATE if outdated).
_SCHEMA_VERSION = 3

# How many characters of each page's body to index. Title+summary cover the
# topic shape; the body adds vocabulary the summary doesn't repeat (verbs,
# proper names, dates), which is what catches paraphrased queries like
# "how did X die" against a page whose summary says "killed".
_BODY_INDEX_CHARS = 2000

# Rate limit for /search: per-client sliding window. Defense vs DoS on the public
# search endpoint. Behind a reverse proxy, request.client.host is the proxy IP —
# X-Forwarded-For handling is a deployment concern (see SECURITY.md).
_RATE_LIMIT_MAX = 60          # requests per window
_RATE_LIMIT_WINDOW = 60       # seconds
_RATE_LIMIT_STATE_CAP = 10_000  # hard cap on distinct IPs tracked

# Caps on in-memory registries to prevent memory exhaustion attacks.
_NODES_CAP = 5_000
_PENDING_QUERIES_CAP = 10_000

# node_id → {ws, tier_name, vram_used_mb, public_key, last_seen, last_seen_ts}
nodes: dict[str, dict] = {}

# query_id → WebSocket of the requesting client (for routing responses back)
pending_queries: dict[str, WebSocket] = {}

# client_ip → list[timestamp] for rate limiting /search
_rate_limit_state: dict[str, list[float]] = {}
_rate_limit_last_cleanup: float = 0.0


def _is_alive(info: dict) -> bool:
    return (time.time() - info.get("last_seen_ts", 0)) < _NODE_TIMEOUT


def _check_rate_limit(client_ip: str) -> bool:
    """
    Sliding-window per-IP rate limit. Returns True if allowed, False if exceeded.
    Self-prunes stale state once per window to keep memory bounded.
    """
    global _rate_limit_last_cleanup
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW

    if now - _rate_limit_last_cleanup > _RATE_LIMIT_WINDOW:
        for k in list(_rate_limit_state.keys()):
            ts = _rate_limit_state[k]
            while ts and ts[0] < cutoff:
                ts.pop(0)
            if not ts:
                del _rate_limit_state[k]
        _rate_limit_last_cleanup = now

    if len(_rate_limit_state) >= _RATE_LIMIT_STATE_CAP and client_ip not in _rate_limit_state:
        # State table full of active IPs — allow the request rather than tracking
        # a new entry (fail-open under extreme load; SECURITY.md flags this).
        return True

    timestamps = _rate_limit_state.setdefault(client_ip, [])
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)
    if len(timestamps) >= _RATE_LIMIT_MAX:
        return False
    timestamps.append(now)
    return True


def _evict_dead_nodes_if_full() -> bool:
    """
    If `nodes` is at cap, evict the oldest dead node. Returns True if there is
    room for a new registration, False if every slot is alive (registration
    must be rejected).
    """
    if len(nodes) < _NODES_CAP:
        return True
    now = time.time()
    dead = sorted(
        (info.get("last_seen_ts", 0), nid)
        for nid, info in nodes.items()
        if (now - info.get("last_seen_ts", 0)) >= _NODE_TIMEOUT
    )
    if dead:
        nodes.pop(dead[0][1], None)
        return True
    return False


def _select_target(requester_vram_mb: int, requester_id: str) -> str | None:
    """Find the single best peer: highest vram_used_mb strictly above requester."""
    candidates = [
        (info["vram_used_mb"], nid)
        for nid, info in nodes.items()
        if nid != requester_id
        and _is_alive(info)
        and info.get("vram_used_mb", 0) > requester_vram_mb
    ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ─── HTTP: Tree navigation ────────────────────────────────────────────────

@app.get("/tree")
async def tree_root():
    """Top-level children of the knowledge tree."""
    if not PACKS_DIR.exists():
        return []
    return sorted(d.name for d in PACKS_DIR.iterdir() if d.is_dir())


@app.get("/tree/{path:path}")
async def tree_node(path: str):
    """Children and pack status of a tree node."""
    node_dir = (PACKS_DIR / path).resolve()
    if not str(node_dir).startswith(str(PACKS_DIR.resolve())):
        raise HTTPException(403)
    if not node_dir.exists() or not node_dir.is_dir():
        raise HTTPException(404)
    children = sorted(d.name for d in node_dir.iterdir() if d.is_dir() and d.name != "wiki")
    has_pack = (node_dir / "wiki" / "index.md").exists()
    return {"children": children, "has_pack": has_pack}


# ─── HTTP: Pack file serving ───────────────────────────────────────────────

@app.get("/packs")
async def list_packs():
    if not PACKS_DIR.exists():
        return []
    return sorted(d.name for d in PACKS_DIR.iterdir() if d.is_dir())


@app.get("/packs/{pack}/index.md")
async def get_index(pack: str):
    f = PACKS_DIR / pack / "wiki" / "index.md"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/packs/{path:path}/wiki/{file:path}")
async def get_page(path: str, file: str):
    f = (PACKS_DIR / path / "wiki" / file).resolve()
    if not str(f).startswith(str(PACKS_DIR.resolve())):
        raise HTTPException(403)
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding="utf-8"), media_type="text/markdown")


# ─── HTTP: Node registry ───────────────────────────────────────────────────

@app.get("/nodes")
async def get_nodes():
    return {
        nid: {
            "tier_name": info.get("tier_name", "micro"),
            "vram_used_mb": info.get("vram_used_mb", 0),
            "public_key": info.get("public_key", ""),
            "last_seen": info.get("last_seen", ""),
        }
        for nid, info in nodes.items()
        if _is_alive(info)
    }


# ─── Pack search (SQLite FTS5) ─────────────────────────────────────────────
#
# Builds a full-text index of every page in every pack from each pack's
# wiki/index.md (title + summary per page). Queries return the most relevant
# pages across all packs, ranked by BM25.

def _open_db() -> sqlite3.Connection:
    SEARCH_DB.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(SEARCH_DB))


def _init_db():
    """
    Create or upgrade the FTS5 index. Uses PRAGMA user_version: if the stored
    version is below _SCHEMA_VERSION, DROP+CREATE with the current schema and
    bump the pragma. Reindex happens at startup (_on_startup), so a fresh table
    after migration gets repopulated automatically.
    """
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


def _read_pack_summary(pack_dir: Path) -> str:
    """Read manifest.yaml summary field; empty string if missing or malformed."""
    mf_path = pack_dir / "manifest.yaml"
    if not mf_path.exists():
        return ""
    try:
        data = yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
        return str(data.get("summary", "") or "")
    except Exception:
        return ""


def _read_page_body(page_path: Path, max_chars: int = _BODY_INDEX_CHARS) -> str:
    """Read a wiki page MD file, strip YAML frontmatter, return up to max_chars
    of body text. Empty string on any failure or missing file."""
    try:
        text = page_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return text[:max_chars]


_INDEX_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$")


def _parse_index_md(text: str) -> list[dict]:
    """Extract (page_file, title, summary) rows from a wiki/index.md table."""
    rows = []
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
        # Skip header rows ("File | Title | Summary") and separator rows ("---")
        if page_file.lower() == "file" or page_file.startswith("-"):
            continue
        if not page_file or not title:
            continue
        rows.append({"page_file": page_file, "title": title, "summary": summary})
    return rows


def _enumerate_packs(packs_root: Path) -> list[tuple[str, Path]]:
    """Walk PACKS_DIR and yield (pack_path, index_md_path) for every pack."""
    out = []
    if not packs_root.exists():
        return out
    for index_path in packs_root.rglob("wiki/index.md"):
        pack_dir = index_path.parent.parent
        try:
            rel = pack_dir.resolve().relative_to(packs_root.resolve())
        except ValueError:
            continue
        pack_path = str(rel).replace("\\", "/")
        out.append((pack_path, index_path))
    return out


def _reindex_all(only_pack: str | None = None) -> dict:
    """
    Rebuild the FTS index. If `only_pack` is given, replace just that pack's
    rows; otherwise wipe and rebuild everything.
    """
    _init_db()
    conn = _open_db()
    try:
        if only_pack:
            conn.execute("DELETE FROM pack_pages WHERE pack_path = ?", (only_pack,))
            packs = [(p, ip) for (p, ip) in _enumerate_packs(PACKS_DIR) if p == only_pack]
        else:
            conn.execute("DELETE FROM pack_pages")
            packs = _enumerate_packs(PACKS_DIR)

        rows_inserted = 0
        for pack_path, index_path in packs:
            try:
                text = index_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            pack_dir = index_path.parent.parent
            pack_summary = _read_pack_summary(pack_dir)
            wiki_dir = index_path.parent
            for row in _parse_index_md(text):
                page_body = _read_page_body(wiki_dir / row["page_file"])
                conn.execute(
                    "INSERT INTO pack_pages (pack_path, page_file, title, summary, pack_summary, body) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (pack_path, row["page_file"], row["title"], row["summary"], pack_summary, page_body),
                )
                rows_inserted += 1
        conn.commit()
        return {"packs_indexed": len(packs), "pages_indexed": rows_inserted}
    finally:
        conn.close()


def _search_packs(q: str, k: int = 10, scope: str = "") -> list[dict]:
    """
    Run an FTS5 query and return top-K results ranked by BM25. If `scope` is
    given (already sanitized by the endpoint), restrict matches to packs whose
    pack_path equals `scope` exactly or starts with `scope/` — both shapes are
    needed so a pack at the root of a domain is not missed by a prefix-only filter.
    """
    if not q.strip():
        return []
    conn = _open_db()
    try:
        # FTS5: rank is bm25 score, ascending = better
        if scope:
            cursor = conn.execute(
                """
                SELECT pack_path, page_file, title, summary, pack_summary, rank
                FROM pack_pages
                WHERE pack_pages MATCH ?
                  AND (pack_path = ? OR pack_path LIKE ?)
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_escape(q), scope, f"{scope}/%", k),
            )
        else:
            cursor = conn.execute(
                """
                SELECT pack_path, page_file, title, summary, pack_summary, rank
                FROM pack_pages
                WHERE pack_pages MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_escape(q), k),
            )
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
        # FTS5 query syntax error (e.g., user typed a special char) → empty result
        return []
    finally:
        conn.close()


def _fts_escape(q: str) -> str:
    """
    Convert a free-text query into FTS5 syntax: each word quoted (literal,
    no operator interpretation) and joined with OR so partial matches still
    rank. Avoids syntax errors from user punctuation. BM25 ranking handles
    relevance — pages matching more terms naturally rank higher.
    """
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    if not words:
        return q
    return " OR ".join(f'"{w}"' for w in words)


@app.on_event("startup")
async def _on_startup():
    try:
        result = _reindex_all()
        print(f"[broker] Search index ready: {result}")
    except Exception as e:
        print(f"[broker] Search index init failed: {e}")


class SearchRequest(BaseModel):
    q: str
    k: int = 10
    scope: str = ""


_SCOPE_FORBIDDEN_RE = re.compile(r"[%_\\]|\.\.")


def _sanitize_scope(scope: str) -> str:
    """Lowercase + strip slashes; reject SQL LIKE wildcards and path traversal."""
    scope = scope.strip().strip("/").lower()
    if not scope:
        return ""
    if _SCOPE_FORBIDDEN_RE.search(scope):
        raise HTTPException(400, "invalid scope")
    return scope


@app.post("/search")
async def search(req: SearchRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(429, "rate limit exceeded")
    scope = _sanitize_scope(req.scope)
    return {"results": _search_packs(req.q, k=max(1, min(req.k, 50)), scope=scope)}


class ReindexRequest(BaseModel):
    pack_path: str | None = None  # if None, full rebuild


@app.post("/admin/reindex")
async def admin_reindex(
    req: ReindexRequest,
    x_occ_token: str = Header(default=""),
):
    if not _REINDEX_TOKEN or x_occ_token != _REINDEX_TOKEN:
        raise HTTPException(401, "invalid token")
    try:
        result = _reindex_all(only_pack=req.pack_path)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    node_id: str | None = None
    my_pending: set[str] = set()  # query_ids waiting on this connection

    try:
        async for raw in ws.iter_text():
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "register":
                node_id = msg.get("node_id", "")
                if not node_id:
                    await ws.send_text(json.dumps({"type": "error", "error": "missing_node_id"}))
                    continue
                if node_id not in nodes and not _evict_dead_nodes_if_full():
                    await ws.send_text(json.dumps({"type": "error", "error": "broker_at_capacity"}))
                    continue
                nodes[node_id] = {
                    "ws": ws,
                    "tier_name": msg.get("tier_name", "micro"),
                    "vram_used_mb": msg.get("vram_used_mb", 0),
                    "public_key": msg.get("public_key", ""),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "last_seen_ts": time.time(),
                }
                await ws.send_text(json.dumps({"type": "registered", "node_id": node_id}))

            elif mtype == "ping":
                if node_id and node_id in nodes:
                    nodes[node_id]["last_seen"] = datetime.now(timezone.utc).isoformat()
                    nodes[node_id]["last_seen_ts"] = time.time()
                await ws.send_text(json.dumps({"type": "pong"}))

            elif mtype == "query":
                # Orchestrator → broker → Critic peer
                to_node = msg.get("to")
                query_id = msg.get("query_id", "")
                if len(pending_queries) >= _PENDING_QUERIES_CAP:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "query_id": query_id,
                        "error": "broker_busy",
                    }))
                    continue
                if to_node and to_node in nodes and _is_alive(nodes[to_node]):
                    pending_queries[query_id] = ws
                    my_pending.add(query_id)
                    target_ws = nodes[to_node]["ws"]
                    try:
                        await target_ws.send_text(json.dumps({
                            "type": "query",
                            "query_id": query_id,
                            "from_node": node_id or msg.get("from_node", ""),
                            "requester_pubkey": msg.get("requester_pubkey", ""),
                            "payload": msg.get("payload", ""),
                        }))
                    except Exception:
                        pending_queries.pop(query_id, None)
                        my_pending.discard(query_id)
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "query_id": query_id,
                            "error": "target_unreachable",
                        }))
                else:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "query_id": query_id,
                        "error": "no_target",
                    }))

            elif mtype == "response":
                # Critic peer → broker → Orchestrator
                query_id = msg.get("query_id", "")
                requester_ws = pending_queries.pop(query_id, None)
                if requester_ws:
                    try:
                        await requester_ws.send_text(json.dumps({
                            "type": "response",
                            "query_id": query_id,
                            "from_node": node_id,
                            "payload": msg.get("payload", ""),
                        }))
                    except Exception:
                        pass

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if node_id and node_id in nodes:
            del nodes[node_id]
        for qid in my_pending:
            pending_queries.pop(qid, None)
