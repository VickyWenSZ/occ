"""
OCC Broker — WebSocket broker + HTTP file serving + pack search

Deploy: /opt/occ-broker/broker.py
Run:    uvicorn broker:app --host 0.0.0.0 --port 8000
Env:    OCC_REINDEX_TOKEN  (required for /admin/reindex)
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()

PACKS_DIR = Path("/opt/occ-packs")
SEARCH_DB = Path("/opt/occ-broker/pack_search.db")
_NODE_TIMEOUT = 90  # seconds
_REINDEX_TOKEN = os.environ.get("OCC_REINDEX_TOKEN", "")

# node_id → {ws, tier_name, vram_used_mb, public_key, last_seen, last_seen_ts}
nodes: dict[str, dict] = {}

# query_id → WebSocket of the requesting client (for routing responses back)
pending_queries: dict[str, WebSocket] = {}


def _is_alive(info: dict) -> bool:
    return (time.time() - info.get("last_seen_ts", 0)) < _NODE_TIMEOUT


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
    conn = _open_db()
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS pack_pages USING fts5(
                pack_path,
                page_file,
                title,
                summary,
                tokenize='porter unicode61'
            )
        """)
        conn.commit()
    finally:
        conn.close()


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
            for row in _parse_index_md(text):
                conn.execute(
                    "INSERT INTO pack_pages (pack_path, page_file, title, summary) VALUES (?, ?, ?, ?)",
                    (pack_path, row["page_file"], row["title"], row["summary"]),
                )
                rows_inserted += 1
        conn.commit()
        return {"packs_indexed": len(packs), "pages_indexed": rows_inserted}
    finally:
        conn.close()


def _search_packs(q: str, k: int = 10) -> list[dict]:
    """Run an FTS5 query and return top-K results ranked by BM25."""
    if not q.strip():
        return []
    conn = _open_db()
    try:
        # FTS5: rank is bm25 score, ascending = better
        cursor = conn.execute(
            """
            SELECT pack_path, page_file, title, summary, rank
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
                "score": row[4],
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


@app.post("/search")
async def search(req: SearchRequest):
    return {"results": _search_packs(req.q, k=max(1, min(req.k, 50)))}


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
