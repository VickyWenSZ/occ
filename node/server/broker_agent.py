"""
OCC Broker Agent — connects to broker.opencognitivecommons.org via WebSocket,
registers this node, and handles incoming Critic query messages.
"""
import asyncio
import base64
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
from node.crypto import (
    load_or_generate_keypair,
    load_or_generate_node_signing_keypair,
    pubkey_b64,
    sign_with_node_key,
    encrypt as _encrypt,
    decrypt as _decrypt,
)

try:
    from node.apps.gui import log_bus as _log_bus
    _log = _log_bus.write
except ImportError:
    _log = print

_MODEL = os.getenv("OCC_MODEL", "qwen3.5:9b")
_BROKER_WS = os.getenv("OCC_BROKER_URL", "wss://broker.opencognitivecommons.org/ws")

_PRIVATE_KEY, _PUBLIC_KEY = load_or_generate_keypair()
# Ed25519 identity keypair — proves to the broker that this node is the
# legitimate holder of NODE_ID. The broker remembers (NODE_ID → signing
# pubkey) via TOFU and refuses any later registration under a different
# key for the same id.
_SIGNING_PRIV, _SIGNING_PUB = load_or_generate_node_signing_keypair()
_SIGNING_PUB_B64 = base64.b64encode(_SIGNING_PUB).decode()
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
                # The broker sends a one-time challenge nonce right after
                # ws.accept(). We sign (nonce || node_id) with our Ed25519
                # identity key to prove ownership of NODE_ID on the broker's
                # TOFU table. Binding node_id into the signed bytes prevents
                # replaying a captured signature under a different id.
                first_msg = json.loads(await ws.recv())
                if first_msg.get("type") != "challenge":
                    _log(f"[OCC Node] Expected challenge, got {first_msg!r}. Reconnecting...")
                    await asyncio.sleep(5)
                    continue
                challenge = base64.b64decode(first_msg.get("nonce", ""))
                signature = sign_with_node_key(
                    _SIGNING_PRIV, challenge + _NODE_ID.encode(),
                )
                await ws.send(json.dumps({
                    "type": "register",
                    "node_id": _NODE_ID,
                    "tier_name": _TIER_NAME,
                    "vram_used_mb": _VRAM_MB,
                    "public_key": pubkey_b64(_PUBLIC_KEY),
                    "signing_pubkey": _SIGNING_PUB_B64,
                    "signature": base64.b64encode(signature).decode(),
                }))
                msg = json.loads(await ws.recv())
                if msg.get("type") == "registered":
                    _log(f"[OCC Node] Registered. Tier={_TIER_NAME}, VRAM={_VRAM_MB}MB. Ready.")
                elif msg.get("type") == "error":
                    _log(f"[OCC Node] Broker rejected register: {msg.get('error')}. Reconnecting in 5s.")
                    await asyncio.sleep(5)
                    continue

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
