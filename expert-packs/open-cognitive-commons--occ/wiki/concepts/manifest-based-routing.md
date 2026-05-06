---
title: Level 1 Routing — Manifest-Based Role Assignment
slug: manifest-based-routing
source: occ
confidence: high
tags: [routing, manifest, roles, distributed-ai, broker]
---

# Level 1 Routing — Manifest-Based Role Assignment

Level 1 Routing is the first-stage distributed role assignment mechanism used by the OCC Node to coordinate multi-peer deliberation. It assigns expert/contrarian roles to peers based on their advertised domain coverage, as declared in per-node manifests, and enforces synthesis strategies (additive vs adversarial) depending on domain overlap. It operates after the local query classifier has selected DELIBERATE mode (or the user forces it with a leading "!") and in conjunction with Three-Mode Routing (local, delegate, hybrid).

## Context and Position in the Pipeline

- Precondition: Query classifier decides:
  - 0 (CHAT): no routing; no wiki retrieval.
  - 1 (DELIBERATE): knowledge-backed; proceed with retrieval + Level 1 Routing.
  - User override: prefix "!" to force DELIBERATE.

- Three-Mode Routing interaction:
  - local: Only local expert pack responds (no relevant peers by domain).
  - delegate: Local pack not relevant; delegate to peer experts selected by Level 1 Routing.
  - hybrid: Local pack relevant and relevant peers exist; local + peers respond; local synthesizer merges.

- Role implementations (node/deliberation/roles.py):
  - answerer: local, single-source answerer (local-only path).
  - expert: peer (or local, in hybrid) producing domain-grounded answer with citations.
  - contrarian: peer tasked to challenge/contrast an expert in the same domain.
  - synthesizer: runs on the querying node; merges answers with an explicit strategy prompt.

## Peer Manifest: Discovery and Shape

Each OCC Node exposes an HTTP endpoint:

- GET /manifest → declares the node’s capability domains.

Minimum schema (JSON illustrative; actual manifest is hub-ready and derived from the pack manifest.yaml):

```json
{
  "node": {
    "id": "peer-8321",
    "version": "0.4.x"
  },
  "domains": ["docker", "mcp"],
  "packs": [
    {
      "name": "docker",
      "version": "2026.04.12",
      "domains": ["docker", "compose", "container-networking"],
      "sources": [{"url": "...", "date": "2026-04-10"}],
      "signature": "sha256:..."
    },
    {
      "name": "mcp",
      "version": "2026.04.05",
      "domains": ["mcp", "model-context-protocol"],
      "sources": [{"url": "...", "date": "2026-04-04"}],
      "signature": "sha256:..."
    }
  ]
}
```

Notes:
- domains is the authoritative set for routing. packs is optional metadata but useful for debugging and synthesis hints.
- Do not include credentials or private keys in manifests.
- The OCC broker maintains a registry of connected peers and their manifests; nodes may cache manifests for the session and refresh opportunistically.

## Algorithm: Manifest-Based Role Assignment

Objective: Given a query q and a set of peers P with manifests, select roles per peer and the synthesis mode.

High-level steps:
1) Fetch manifests in parallel for all peers (timeout-tolerant).
2) Tokenize q and compute overlap with each peer’s domains.
3) Select relevant peers and assign roles:
   - If exactly one relevant peer → role: expert.
   - If two relevant peers with different domains → both role: expert; synthesis: ADDITIVE with the instruction:
     - "Integrate both expert perspectives — each covers a different domain"
   - If two relevant peers with the same domain(s) → one expert + one contrarian; synthesis: ADVERSARIAL with the instruction:
     - "Synthesize resolving disagreements, keep strongest points"

Pseudocode:

```python
def route_level1(query: str, peers: list[Peer]) -> RoutingPlan:
    # 1) Fetch manifests concurrently
    manifests = parallel_get([peer.url + "/manifest" for peer in peers], timeout=2.5)

    # 2) Preprocess
    q_tokens = normalize_and_tokenize(query)  # lower, strip punctuation; optionally drop EN/IT stopwords

    # Score overlap for each peer
    scored = []
    for peer, m in manifests.items():
        dom_tokens = set(flatten([normalize(d) for d in m["domains"]]))
        score = jaccard(q_tokens, dom_tokens) or keyword_hit(q_tokens, dom_tokens)
        if score > 0:
            scored.append((peer, score, dom_tokens))

    # Sort by score desc, deterministic tie-break by peer.id
    scored.sort(key=lambda x: (-x[1], x[0].id))

    relevant = [s[0] for s in scored]
    if len(relevant) == 0:
        return RoutingPlan(mode="local", roles=[], synthesis=None)

    # 3) Role assignment for top peers
    if len(relevant) == 1:
        return RoutingPlan(mode="delegate_or_hybrid", roles=[Role(peer=relevant[0], kind="expert")],
                           synthesis="additive")  # single-source synthesis is degenerate-additive

    # Take top-2 for Level 1 (extendable if needed)
    p1, p2 = relevant[0], relevant[1]
    d1, d2 = set(manifests[p1]["domains"]), set(manifests[p2]["domains"])
    if d1.isdisjoint(d2):
        roles = [Role(peer=p1, kind="expert"), Role(peer=p2, kind="expert")]
        synth = "additive"
    else:
        roles = [Role(peer=p1, kind="expert"), Role(peer=p2, kind="contrarian")]
        synth = "adversarial"
    return RoutingPlan(mode="delegate_or_hybrid", roles=roles, synthesis=synth)
```

Implementation notes:
- parallel_get should be resilient (timeouts, retries) and non-blocking for slow/missing peers.
- normalize_and_tokenize: simple lowercasing + splitting is sufficient; using EN/IT stopword removal reduces false matches.
- Scoring: Jaccard on tokens is adequate; exact string inclusion also works for short domain keys (e.g., "mcp", "docker").

## Synthesis Strategies

- Additive synthesis (different domains):
  - Prompt cue: "Integrate both expert perspectives — each covers a different domain"
  - Behavior: preserve complementary coverage; avoid forced unification; maintain explicit sections or bullet integration.

- Adversarial synthesis (same domain):
  - Prompt cue: "Synthesize resolving disagreements, keep strongest points"
  - Behavior: compare claims, surface conflicts, prefer claims with stronger evidence/citations; may include brief rationale.

The synthesizer runs locally on the querying node, ingesting all peer answers (and possibly the local answer in hybrid mode).

## Local Retrieval and Relevance Thresholds

- Local pack retrieval uses keyword search across markdown pages (stop words IT+EN).
- Threshold: ≥300 characters retrieved to mark the local pack as "relevant".
- Hybrid mode: If local is relevant and Level 1 selects peers, the node contributes a local expert answer alongside peer answers; the local synthesizer merges all.

## Network and Broker Interaction

- Topology: Nodes maintain outbound WebSocket connections to a broker (broker.opencognitivecommons.org). The broker:
  - Registers nodes with their manifests.
  - Forwards queries to peers with matching domains (based on their registered manifests).
  - Aggregates peer responses and returns them to the requester.
- Privacy: Knowledge, retrieval, inference, and final synthesis remain local to each node. The broker relays metadata and messages only.

## Failure Modes and Fallbacks

- Missing/slow manifests: Skip unavailable peers; proceed with available ones. If none, fall back to local mode.
- Conflicting or stale manifests: Adversarial synthesis path mitigates inconsistent answers in the same domain; future roadmap includes reputation and pack integrity checks (SHA-256 + OCC.org signatures).
- No domain overlap: Remain local; avoid spurious delegation.
- Excess relevant peers: Implementation may cap to top-2 by score for Level 1; additional peers can be sampled or deferred to higher-level routing policies.

## Security and Integrity Considerations

- Anti-GEO principle: Peers derive knowledge solely from curated expert packs; manifests should list community-approved sources with hashes and signatures.
- Man-in-the-middle risk is reduced by using broker TLS; manifests should include integrity metadata (signatures) and be verifiable against OCC Hub in future phases.
- Nodes must not expose sensitive data in manifests or responses; all tool execution remains sandboxed (workspace/).

## Performance Considerations

- Parallel manifest fetch and scoring adds negligible overhead relative to LLM inference.
- Streaming peer responses allows early synthesis start; synthesizer should tolerate partial inputs with timeouts.
- Deterministic tie-breaking ensures reproducibility across runs with equal scores.

## Example Scenarios

1) Two domains (additive):
   - Query: "How do I configure Docker Compose networks for an MCP server?"
   - Peers: A(domains=["docker"]), B(domains=["mcp"])
   - Roles: A=expert, B=expert → Additive synthesis: integrate container networking and MCP server requirements.

2) Same domain (adversarial):
   - Query: "Best practices for Docker image layering?"
   - Peers: A(domains=["docker"]), B(domains=["docker","compose"])
   - Roles: A=expert, B=contrarian → Adversarial synthesis: resolve disagreements; keep strongest evidence-backed points.

## Minimal HTTP Manifest Endpoint (FastAPI sketch)

```python
from fastapi import FastAPI
app = FastAPI()

LOCAL_MANIFEST = {
    "node": {"id": "node-abc", "version": "0.4.0"},
    "domains": ["docker", "mcp"],
    "packs": [
        {"name": "docker", "version": "2026.04.12", "domains": ["docker", "compose", "container-networking"],
         "signature": "sha256:..."},
        {"name": "mcp", "version": "2026.04.05", "domains": ["mcp", "model-context-protocol"],
         "signature": "sha256:..."}
    ]
}

@app.get("/manifest")
def manifest():
    return LOCAL_MANIFEST
```

## Implementation Pointers (OCC Repo)

- node/deliberation/engine.py — Level 1 routing logic and orchestration with local/delegate/hybrid modes.
- node/deliberation/roles.py — role prompts and behaviors (expert, contrarian, synthesizer).
- node/server/broker_agent.py — WebSocket agent for broker registration and message forwarding.
- node/server/client.py — peer calls via broker.
- retrieval/search.py — local wiki keyword search (≥300 chars relevance threshold).

## Operational CLI Aids

- /peers — Inspect currently registered peers (via broker).
- ! <query> — Force DELIBERATE, bypassing the classifier.
- /clear — Reset conversational history and context counter.

## Key Points

- Level 1 Routing assigns expert/contrarian roles using peer manifests that declare domains; selection is overlap-based.
- Two synthesis regimes exist: additive (different domains) and adversarial (same domain), with explicit prompt cues.
- It integrates with Three-Mode Routing: local, delegate, hybrid; synthesis always executes locally.
- Manifests are fetched in parallel; routing is resilient to timeouts and missing peers; fall back to local when needed.
- Security relies on curated packs and future integrity checks; the broker only forwards messages, keeping inference local.