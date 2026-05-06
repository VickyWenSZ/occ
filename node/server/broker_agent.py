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
import socket
import sys
import uuid
from pathlib import Path

import ollama
import websockets

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from node.deliberation.roles import ROLES
from node.expert_runtime.pack import load_all_packs

_MODEL = os.getenv("OCC_MODEL", "qwen3.5:9b")
_BROKER_WS = os.getenv("OCC_BROKER_URL", "wss://broker.opencognitivecommons.org/ws")
_retriever = load_all_packs(ROOT / "expert-packs")
_NODE_ID = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"


def _load_manifest() -> dict:
    return {
        "pack": _retriever.name,
        "domains": _retriever.domains,
    }


def _handle_query(query_text: str) -> str:
    context = _retriever.retrieve(query_text) if _retriever.packs else ""
    role_cfg = ROLES["expert"]
    context_block = f"[Knowledge base context]\n{context}\n\n" if context else ""
    prompt = (
        f"{context_block}"
        f"Question: {query_text}\n\n"
        "Answer thoroughly using the knowledge base context."
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
    print(f"[OCC Node] ID     : {_NODE_ID}")
    print(f"[OCC Node] Packs  : {_retriever.name}")
    print(f"[OCC Node] Domains: {manifest['domains']}")
    print(f"[OCC Node] Broker : {_BROKER_WS}")

    while True:
        try:
            async with websockets.connect(_BROKER_WS, ping_timeout=None) as ws:
                await ws.send(json.dumps({
                    "type": "register",
                    "node_id": _NODE_ID,
                    "manifest": manifest,
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") == "registered":
                    print(f"[OCC Node] Registered with broker. Ready.")

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
                        print(f"[OCC Node] Query: {query_text[:80]}...")
                        loop = asyncio.get_event_loop()
                        answer = await loop.run_in_executor(None, _handle_query, query_text)
                        await ws.send(json.dumps({
                            "type": "response",
                            "query_id": query_id,
                            "pack": _retriever.name,
                            "text": answer,
                        }))
                        print(f"[OCC Node] Response sent ({len(answer)} chars)")
                    elif msg.get("type") == "pong":
                        pass

        except Exception as e:
            print(f"[OCC Node] Disconnected: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
