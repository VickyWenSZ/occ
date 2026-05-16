"""
OCC Broker Agent — connects to broker.opencognitivecommons.org via WebSocket,
registers this node, and handles incoming Critic query messages.
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
from node.hardware import get_vram_used_mb, select_tier, detect_vram_gb
from node.crypto import load_or_generate_keypair, pubkey_b64, encrypt as _encrypt, decrypt as _decrypt

try:
    from node.apps.gui import log_bus as _log_bus
    _log = _log_bus.write
except ImportError:
    _log = print

_MODEL = os.getenv("OCC_MODEL", "qwen3.5:9b")
_BROKER_WS = os.getenv("OCC_BROKER_URL", "wss://broker.opencognitivecommons.org/ws")

_PRIVATE_KEY, _PUBLIC_KEY = load_or_generate_keypair()
_VRAM_MB = get_vram_used_mb()
_TIER_NAME = select_tier(detect_vram_gb())["name"]


def _handle_query(payload_str: str, requester_pubkey: str, query_id: str) -> str:
    """
    Execute Critic role on received payload.
    Decrypts payload if requester_pubkey provided (E2E), else plain JSON fallback.

    `query_id` is fed as AAD to AES-GCM so replay attacks (feeding an old
    captured ciphertext into a new exchange) fail the auth tag check.
    """
    aad = (query_id or "").encode()
    if requester_pubkey:
        raw = _decrypt(payload_str, _PRIVATE_KEY, aad=aad)
        data = json.loads(raw.decode())
    else:
        data = json.loads(payload_str)

    context = data.get("context", "")
    expert_answer = data.get("expert_answer", "")

    if context:
        prompt = (
            f"[Knowledge context]\n{context}\n\n"
            f"[Proposed answer]\n{expert_answer}\n\n"
            "Review this answer critically. Find gaps, errors, missing cases."
        )
    else:
        prompt = (
            f"[Proposed answer]\n{expert_answer}\n\n"
            "Review this answer critically. Find gaps, errors, missing cases."
        )

    response = ollama.chat(
        model=_MODEL,
        messages=[
            {"role": "system", "content": ROLES["critic"]["system"]},
            {"role": "user", "content": prompt},
        ],
        think=False,
        keep_alive=-1,
        options={"temperature": 0.3, "num_ctx": 8192},
        stream=False,
    )
    critique = response.message.content or ""
    response_payload = json.dumps({"critique": critique}).encode()

    if requester_pubkey:
        return _encrypt(response_payload, requester_pubkey, aad=aad)
    return response_payload.decode()


async def run():
    _log(f"[OCC Node] ID         : {_NODE_ID}")
    _log(f"[OCC Node] Tier       : {_TIER_NAME}")
    _log(f"[OCC Node] VRAM used  : {_VRAM_MB} MB")
    _log(f"[OCC Node] Broker     : {_BROKER_WS}")

    while True:
        try:
            async with websockets.connect(_BROKER_WS, ping_timeout=None) as ws:
                await ws.send(json.dumps({
                    "type": "register",
                    "node_id": _NODE_ID,
                    "tier_name": _TIER_NAME,
                    "vram_used_mb": _VRAM_MB,
                    "public_key": pubkey_b64(_PUBLIC_KEY),
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") == "registered":
                    _log(f"[OCC Node] Registered. Tier={_TIER_NAME}, VRAM={_VRAM_MB}MB. Ready.")

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
                        from_node = msg.get("from_node", "")
                        payload = msg.get("payload", "")
                        requester_pubkey = msg.get("requester_pubkey", "")
                        _log(f"[OCC Node] Critic request from {from_node[:8]}...")
                        loop = asyncio.get_event_loop()
                        answer = await loop.run_in_executor(
                            None, _handle_query, payload, requester_pubkey, query_id
                        )
                        await ws.send(json.dumps({
                            "type": "response",
                            "query_id": query_id,
                            "to": from_node,
                            "payload": answer,
                        }))
                        _log(f"[OCC Node] Critic response sent ({len(answer)} chars)")
                    elif msg.get("type") == "pong":
                        pass

        except Exception as e:
            _log(f"[OCC Node] Disconnected: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
