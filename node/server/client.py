import asyncio
import json
import uuid
from dataclasses import dataclass
from node.server.node_id import NODE_ID as _LOCAL_NODE_ID

import httpx
from node.retrieval.search import _embed as _embed_text

BROKER_HTTP = "https://broker.opencognitivecommons.org"
BROKER_WS = "wss://broker.opencognitivecommons.org/ws"

_manifests_cache: dict[str, dict] = {}


@dataclass
class PeerResponse:
    role: str
    answer: str
    pack: str
    node_id: str = ""
    error: str | None = None


def fetch_peer_manifests(peer_urls=None) -> dict[str, dict]:
    """Returns {node_id: {pack, domains}} for all nodes registered with the broker."""
    global _manifests_cache
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{BROKER_HTTP}/nodes")
            resp.raise_for_status()
            data = resp.json()
            _manifests_cache = {
                nid: {"pack": info.get("pack", ""), "domains": info.get("domains", [])}
                for nid, info in data.items()
            }
            return _manifests_cache
    except Exception:
        return {}


async def _query_via_broker(
    target_ids: list[str],
    roles: dict[str, str],
    query: str,
    domains: list[str],
    query_embedding: list[float] | None = None,
) -> list[PeerResponse]:
    import websockets

    query_id = str(uuid.uuid4())
    try:
        async with websockets.connect(BROKER_WS, ping_timeout=None) as ws:
            await ws.send(json.dumps({
                "type": "query",
                "query_id": query_id,
                "text": query,
                "domains": domains,
                "query_embedding": query_embedding,
                "from_node": _LOCAL_NODE_ID,
            }))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "responses" and msg.get("query_id") == query_id:
                    responses = []
                    for r in msg.get("responses", []):
                        node_id = r.get("node_id", "")
                        responses.append(PeerResponse(
                            role=roles.get(node_id, "expert"),
                            answer=r.get("text", ""),
                            pack=r.get("pack", ""),
                            node_id=node_id,
                        ))
                    return responses
                elif msg.get("type") == "responses" and msg.get("error"):
                    return []
    except Exception as exc:
        return [PeerResponse(role="expert", answer="", pack="", error=str(exc))]
    return []


def call_peers_parallel(
    peer_assignments: list[tuple[str, str]],
    query: str,
    context: str = "",
) -> list[PeerResponse]:
    """Queries peer nodes via broker. peer_assignments: list of (node_id, role)."""
    target_ids = [nid for nid, _ in peer_assignments]
    roles = {nid: role for nid, role in peer_assignments}
    domains = []
    for nid in target_ids:
        domains.extend(_manifests_cache.get(nid, {}).get("domains", []))
    query_embedding = _embed_text(query)
    return asyncio.run(_query_via_broker(target_ids, roles, query, domains, query_embedding))
