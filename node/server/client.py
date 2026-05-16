import asyncio
import json
import uuid
from dataclasses import dataclass

import httpx

from node.server.node_id import NODE_ID as _LOCAL_NODE_ID
from node.crypto import encrypt as _encrypt, decrypt as _decrypt, pubkey_from_private_b64

BROKER_HTTP = "https://broker.opencognitivecommons.org"
BROKER_WS = "wss://broker.opencognitivecommons.org/ws"

_QUERY_TIMEOUT = 60  # seconds


@dataclass
class PeerInfo:
    node_id: str
    tier_name: str
    vram_used_mb: int
    public_key: str


def fetch_peer_list() -> list[PeerInfo]:
    """Return live peers from broker /nodes, excluding self."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{BROKER_HTTP}/nodes")
            resp.raise_for_status()
            return [
                PeerInfo(
                    node_id=nid,
                    tier_name=info.get("tier_name", "micro"),
                    vram_used_mb=info.get("vram_used_mb", 0),
                    public_key=info.get("public_key", ""),
                )
                for nid, info in resp.json().items()
                if nid != _LOCAL_NODE_ID
            ]
    except Exception:
        return []


def call_peer_critic(
    context: str,
    expert_answer: str,
    peer: PeerInfo,
    my_private_key: bytes,
) -> str | None:
    """Send Expert output to a peer for Critic review. Returns critique str or None on failure."""
    try:
        return asyncio.run(_call_peer_critic_async(context, expert_answer, peer, my_private_key))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            fut = pool.submit(
                asyncio.run,
                _call_peer_critic_async(context, expert_answer, peer, my_private_key),
            )
            return fut.result(timeout=_QUERY_TIMEOUT + 5)


async def _call_peer_critic_async(
    context: str,
    expert_answer: str,
    peer: PeerInfo,
    my_private_key: bytes,
) -> str | None:
    import websockets

    query_id = str(uuid.uuid4())
    raw_payload = json.dumps({"context": context, "expert_answer": expert_answer})
    use_crypto = bool(peer.public_key)
    # Bind the AEAD tag to query_id — prevents cross-query replay if a peer
    # tries to feed an old captured ciphertext into a fresh exchange.
    aad = query_id.encode()

    if use_crypto:
        payload = _encrypt(raw_payload.encode(), peer.public_key, aad=aad)
        my_pubkey_b64 = pubkey_from_private_b64(my_private_key)
    else:
        payload = raw_payload
        my_pubkey_b64 = ""

    try:
        async with websockets.connect(BROKER_WS, ping_timeout=None) as ws:
            await ws.send(json.dumps({
                "type": "query",
                "query_id": query_id,
                "to": peer.node_id,
                "from_node": _LOCAL_NODE_ID,
                "requester_pubkey": my_pubkey_b64,
                "payload": payload,
            }))

            async def _wait() -> str | None:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("query_id") != query_id:
                        continue
                    if msg.get("type") == "response":
                        resp_payload = msg.get("payload", "")
                        if use_crypto:
                            data = json.loads(_decrypt(resp_payload, my_private_key, aad=aad).decode())
                        else:
                            data = json.loads(resp_payload)
                        return data.get("critique")
                    if msg.get("type") == "error":
                        return None
                return None

            return await asyncio.wait_for(_wait(), timeout=_QUERY_TIMEOUT)

    except (asyncio.TimeoutError, Exception):
        return None
