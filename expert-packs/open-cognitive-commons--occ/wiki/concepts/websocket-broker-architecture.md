---
title: WebSocket Broker Architecture
slug: websocket-broker-architecture
source: occ
confidence: high
tags: [websocket, broker, distributed-systems, occ, routing]
---

# WebSocket Broker Architecture

The WebSocket Broker in OCC (Open Cognitive Commons) is a minimal, federable relay layer that connects user-run OCC Nodes over outbound WebSocket connections. It replaces full P2P (abandoned due to NAT traversal complexity) and avoids centralized knowledge/inference (which would undermine OCC’s value). The broker is “just a postman”: it registers connected nodes with their manifests, routes queries to nodes advertising matching domains, and aggregates their responses. All knowledge, retrieval, inference, and final synthesis remain local to nodes.

## Design Goals and Rationale

- Outbound-only connectivity: every node dials out via WebSocket, eliminating NAT/firewall traversal issues (browser-like model).
- No central knowledge/inference: packs and LLM inference never leave user machines.
- Lightweight relay: ~200–300 lines of Python; simple, auditable; low operational cost.
- Federable: any party can run a compatible broker; nodes select the broker via OCC_BROKER_URL (email/Mastodon-like federation).
- Predictable scaling: cost ~€5.71/month on Hetzner for the first ~1,000 nodes, scaling linearly.

## Responsibilities and Trust Boundaries

- Always local (on each OCC Node):
  - Knowledge base: expert packs (markdown wiki), manifest.yaml
  - Retrieval: keyword search with IT+EN stop words; relevance threshold 300 chars
  - Inference: local LLM via Ollama (Qwen family; 262K context)
  - Deliberation and synthesis: local role routing (expert/contrarian), final answer synthesis

- Broker responsibilities:
  - Maintain a live registry of connected nodes and their manifests (domains advertised)
  - Route user queries to relevant nodes based on domain matching
  - Aggregate and forward peer responses back to the origin node

- Explicit non-goals for broker:
  - No content storage/indexing of packs
  - No LLM inference or knowledge hosting
  - No intrusive state beyond active connections and minimal routing metadata

## Reference Topology and Flow

ASCII flow (from source):

[Nodo A — utente]       [broker.opencognitivecommons.org]    [Nodo B]    [Nodo C]
      |                               |                           |            |
      |--- WebSocket open (outbound)->|                           |            |
      |                               |<-- WebSocket open --------|            |
      |                               |<-- WebSocket open ------------------- |
      |--- "query: docker+mcp" ------>|                           |            |
      |                               |--- forward query -------->|            |
      |                               |--- forward query ----------------------|
      |                               |  [Retrieval locale + LLM su ogni nodo] |
      |<-- risposte aggregate --------|                           |            |
      | [sintesi finale locale]       |                           |            |

Key properties:
- All connections are outbound WebSockets from nodes to the broker.
- The origin node sends a routed query (e.g., “docker+mcp”).
- The broker forwards to nodes whose manifests advertise matching domains.
- Each recipient node performs local retrieval + local LLM inference and returns an answer.
- The origin node performs final local synthesis over broker-aggregated peer answers.

## Routing Model

- Node manifests: each node exposes GET /manifest with its advertised domains; broker maintains a registry keyed by connection with manifest metadata.
- Manifest-based matching: token overlap between the user query and domains in manifests selects target peers.
- Role assignment at the node (Level 1 Routing):
  - 1 relevant peer → expert
  - 2 relevant peers, different domains → both experts; additive synthesis (“Integrate both expert perspectives — each covers a different domain”)
  - 2+ relevant peers, same domain(s) → expert + contrarian; adversarial synthesis (“Resolve disagreements; keep strongest points”)
- Three-Mode Routing (driven by the origin node’s deliberation engine):
  - local: only local pack is relevant
  - delegate: local pack not relevant, peers match
  - hybrid: local pack relevant and peers also match → mix local + peer answers before synthesis

Note: The classifier LLM precedes routing, selecting CHAT (0) vs DELIBERATE (1). “When in doubt, prefer 0” to avoid unnecessary retrieval.

## Protocol Mechanics (Practical Shape)

While intentionally minimal, a typical exchange uses JSON frames over a single WebSocket per node:

- register: sent by node on connect, includes node_id and manifest summary (domains, version)
- query: origin node posts a query with request_id, domains/tokens, and payload
- forward: broker multicasts to target node connections determined by manifest match
- response: peer nodes reply with request_id, node_id, and answer payload (plus timing/ctx stats)
- aggregate: broker streams or batches back to the origin node

Example frames (illustrative):

```json
// register
{ "type": "register", "node_id": "node-123", "manifest": { "domains": ["docker", "mcp"], "version": "1.2.0" } }

// query from origin -> broker
{ "type": "query", "request_id": "rq-7f9", "from": "node-123", "tokens": ["docker","mcp"], "payload": { "prompt": "Compare bind mounts vs volumes in Docker Compose." } }

// forward broker -> peer
{ "type": "forward", "request_id": "rq-7f9", "to": "node-456", "tokens": ["docker","mcp"], "payload": { "prompt": "Compare bind mounts vs volumes in Docker Compose." } }

// response peer -> broker
{ "type": "response", "request_id": "rq-7f9", "from": "node-456", "answer": "...", "meta": { "retrieved": 1127, "model": "qwen3.5:9b Q4_K_M" } }

// aggregate broker -> origin
{ "type": "aggregate", "request_id": "rq-7f9", "answers": [ /* streamed or batched peer responses */ ] }
```

The origin node then performs the final synthesis locally using its roles/synthesizer.

## Security, Privacy, and Integrity

- Transport security: TLS via Nginx termination with Let’s Encrypt (auto-renewal).
- Network posture: nodes initiate outbound WebSockets only; no inbound ports to open on user machines.
- Data locality: packs and LLM reasoning remain local; broker sees only routed messages (queries/answers).
- Future integrity roadmap (OCC): SHA-256 and cryptographic signatures of packs, reputation system, and source registry (not broker-specific but relevant to end-to-end trust).

## Deployment Stack (Live Reference)

- Infrastructure: Hetzner CX23, Ubuntu 24.04, systemd service
- Domain: broker.opencognitivecommons.org
- Server stack: FastAPI + WebSockets (Uvicorn), Nginx reverse proxy
  - proxy_read_timeout: 600s (to support long-running LLM calls)
  - WebSocket upgrade headers and pass-through

Minimal FastAPI broker sketch:

```python
# broker.py (illustrative, ~200–300 LOC in production)
import json, uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, Any, Set

app = FastAPI()
peers: Set[WebSocket] = set()
manifests: Dict[WebSocket, Dict[str, Any]] = {}

def match_targets(tokens, manifests):
    def score(m): return len(set(tokens) & set(m.get("domains", [])))
    return [ws for ws, m in manifests.items() if score(m) > 0]

@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    await ws.accept()
    peers.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            t = data.get("type")
            if t == "register":
                manifests[ws] = data.get("manifest", {})
            elif t == "query":
                req_id = data.get("request_id") or str(uuid.uuid4())
                tokens = data.get("tokens", [])
                targets = match_targets(tokens, manifests)
                fwd = json.dumps({"type":"forward","request_id":req_id, **data})
                for tws in targets:
                    await tws.send_text(fwd)
            elif t == "response":
                # return to origin (identified in data["request_id"] or explicit "reply_to")
                agg = json.dumps({"type":"aggregate", **data})
                await ws.send_text(agg)  # in production: route back to origin by request map
    except WebSocketDisconnect:
        manifests.pop(ws, None)
        peers.discard(ws)
```

Nginx reverse proxy essentials:

```nginx
server {
  listen 443 ssl http2;
  server_name broker.opencognitivecommons.org;

  ssl_certificate     /etc/letsencrypt/live/broker.opencognitivecommons.org/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/broker.opencognitivecommons.org/privkey.pem;

  location /ws {
    proxy_pass http://127.0.0.1:8000/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 600s;
  }
}
```

## Node Integration

- Components:
  - node/server/broker_agent.py: persistent WebSocket client to the broker (register, send queries, receive aggregates)
  - node/server/client.py: peer calls over broker
  - node/server/server.py: local FastAPI server (HTTP, intra-node)
- CLI:
  - /peers: list broker-registered nodes in real time
  - ! <query>: force DELIBERATE mode (bypass classifier); then route via broker if peers match
- Configuration:
  - OCC_BROKER_URL: runtime-selectable broker endpoint (enables federation and private/community brokers)

## Federation

- Any organization can deploy a compatible broker (same minimal JSON/WebSocket protocol shape).
- Nodes point to different brokers via OCC_BROKER_URL; ecosystems can interoperate similarly to email/Mastodon.
- Brokers do not need to trust each other for knowledge—only for message relay; no global state is required.

## Operational Behavior and Failure Modes

- Timeouts: long-running LLM calls supported via proxy_read_timeout 600s; nodes should stream partials or report progress.
- Partial results: origin node synthesizes over any subset of answers received before timeout; missing peers don’t block finalization.
- Elastic scale: adding broker instances (or independent brokers) scales linearly with connected nodes; state is minimal.
- Health: nodes re-register on reconnect; broker drops manifests on disconnect.
- Observability: simple peer listing (/peers in CLI) confirms live registry status.

## Interplay with Deliberation Engine

- Before sending network queries, node classifier selects CHAT (0) vs DELIBERATE (1).
- In DELIBERATE, retrieval runs locally to decide local/delegate/hybrid mode.
- If delegate or hybrid modes select peers, node emits a broker query including tokens/domains; broker fan-outs per manifest match.
- Returned peer answers are combined with any local answer; local synthesizer produces the final response.

## What the Broker Is Not

- Not a knowledge repository: no ingest, no wiki storage, no global index.
- Not an inference service: never runs LLMs on behalf of nodes.
- Not a P2P overlay: it centralizes transport only, while leaving knowledge and reasoning distributed across user nodes.

## Key Points

- The broker is a minimal WebSocket relay that registers node manifests, routes domain-matched queries, and aggregates responses.
- All packs, retrieval, LLM inference, and final synthesis remain on user nodes; the broker never hosts knowledge or computes answers.
- Outbound-only WebSockets solve NAT traversal cleanly and cheaply; the system scales linearly with low operational cost.
- Federation is built-in: nodes choose a broker via OCC_BROKER_URL; anyone can run a compatible broker.
- Production stack: FastAPI + WebSockets behind Nginx with TLS (Let’s Encrypt), proxy_read_timeout 600s, systemd-managed on Hetzner.