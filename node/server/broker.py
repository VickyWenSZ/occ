"""
OCC Broker — WebSocket broker + HTTP file serving
broker.opencognitivecommons.org

Deploy: /opt/occ-broker/broker.py
Run:    uvicorn broker:app --host 0.0.0.0 --port 8000
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

app = FastAPI()

PACKS_DIR = Path("/opt/occ-packs")
_NODE_TIMEOUT = 90  # seconds

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


# ─── HTTP: Pack file serving ───────────────────────────────────────────────

@app.get("/packs")
async def list_packs():
    if not PACKS_DIR.exists():
        return []
    return [d.name for d in PACKS_DIR.iterdir() if d.is_dir()]


@app.get("/packs/{pack}/index.md")
async def get_index(pack: str):
    f = PACKS_DIR / pack / "index.md"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/packs/{pack}/wiki/{filename:path}")
async def get_page(pack: str, filename: str):
    f = (PACKS_DIR / pack / "wiki" / filename).resolve()
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
