"""
OCC Broker Agent — connects to broker.opencognitivecommons.org via WebSocket,
registers this node, and handles incoming query messages.

Usage:
    OCC_PACK=mcp python -m node.server.broker_agent
    OCC_PACK=docker OCC_MODEL=qwen3.5:9b python -m node.server.broker_agent
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import ollama
import websockets

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from node.server.node_id import NODE_ID as _NODE_ID
from node.deliberation.roles import ROLES
from node.expert_runtime.pack import load_all_packs
from node.retrieval.search import load_embeddings

try:
    from node.apps.gui import log_bus as _log_bus
    _log = _log_bus.write
except ImportError:
    _log = print

_MODEL = os.getenv("OCC_MODEL", "qwen3.5:9b")
_BROKER_WS = os.getenv("OCC_BROKER_URL", "wss://broker.opencognitivecommons.org/ws")
_retriever = load_all_packs(ROOT / "expert-packs")


def _load_manifest() -> dict:
    return {
        "pack": _retriever.name,
        "domains": _retriever.domains,
    }


def _compute_pack_centroid() -> list[float] | None:
    """Average of all page embedding vectors across all loaded packs."""
    all_vectors: list[list[float]] = []
    for pack in _retriever.packs:
        emb = load_embeddings(pack.wiki_dir)
        if emb and emb.get("entries"):
            for entry in emb["entries"]:
                all_vectors.append(entry["vector"])
    if not all_vectors:
        return None
    dim = len(all_vectors[0])
    return [sum(v[i] for v in all_vectors) / len(all_vectors) for i in range(dim)]


def _handle_query(query_text: str) -> str:
    context = _retriever.retrieve(query_text) if _retriever.packs else ""
    role_cfg = ROLES["expert"]
    context_block = f"[Knowledge base context]\n{context}\n\n" if context else ""
    prompt = (
        f"{context_block}"
        f"Question: {query_text}\n\n"
        "Answer using the knowledge base context above. "
        "Be proportional: a precise question deserves a precise answer, "
        "a broad question can have a broader answer. No padding, no repetition."
    )
    response = ollama.chat(
        model=_MODEL,
        messages=[
            {"role": "system", "content": role_cfg["system"]},
            {"role": "user", "content": prompt},
        ],
        think=False,
        keep_alive=-1,
        options={
            "temperature": role_cfg["temperature"],
            "num_ctx": 6144,
            "stop": ["<|endoftext|>", "<|im_start|>", "<|im_end|>"],
        },
        stream=False,
    )
    return response.message.content or ""


async def run():
    manifest = _load_manifest()
    pack_embedding = _compute_pack_centroid()
    _log(f"[OCC Node] ID        : {_NODE_ID}")
    _log(f"[OCC Node] Packs     : {_retriever.name}")
    _log(f"[OCC Node] Domains   : {manifest['domains']}")
    _log(f"[OCC Node] Embedding : {'yes' if pack_embedding else 'no (nomic unavailable)'}")
    _log(f"[OCC Node] Broker    : {_BROKER_WS}")

    while True:
        try:
            async with websockets.connect(_BROKER_WS, ping_timeout=None) as ws:
                await ws.send(json.dumps({
                    "type": "register",
                    "node_id": _NODE_ID,
                    "manifest": manifest,
                    "pack_embedding": pack_embedding,
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") == "registered":
                    _log(f"[OCC Node] Registered with broker. Ready.")

                async def heartbeat():
                    while True:
                        await asyncio.sleep(30)
                        try:
                            await ws.send(json.dumps({"type": "ping"}))
                        except Exception:
                            break

                asyncio.create_task(heartbeat())

                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "query":
                        query_id = msg["query_id"]
                        query_text = msg.get("text", "")
                        _log(f"[OCC Node] Query: {query_text[:80]}...")
                        loop = asyncio.get_event_loop()
                        answer = await loop.run_in_executor(None, _handle_query, query_text)
                        await ws.send(json.dumps({
                            "type": "response",
                            "query_id": query_id,
                            "pack": _retriever.name,
                            "text": answer,
                        }))
                        _log(f"[OCC Node] Response sent ({len(answer)} chars)")
                    elif msg.get("type") == "pong":
                        pass

        except Exception as e:
            _log(f"[OCC Node] Disconnected: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
