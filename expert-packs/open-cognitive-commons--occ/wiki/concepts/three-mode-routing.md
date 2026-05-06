---
title: Three-Mode Routing (local / delegate / hybrid)
slug: three-mode-routing
source: occ
confidence: high
tags: [routing, distributed, deliberation, peers, retrieval]
---

# Three-Mode Routing (local / delegate / hybrid)

Three-Mode Routing is the distributed deliberation policy used by the OCC Node to decide where and how to answer a user query when connected to a network of peers via the OCC WebSocket broker. It combines a minimal semantic classifier, local wiki retrieval, and manifest-based peer role assignment to route queries in one of three modes: local, delegate, or hybrid.

## Overview

- Scope: OCC Node runtime (Python) within the OCC distributed Mixture-of-Experts architecture.
- Modes:
  - local — Answer only from the local expert pack.
  - delegate — Forward to peer experts and synthesize locally.
  - hybrid — Combine a local answer with peer answers and synthesize locally.
- Triggers:
  - Determined by (a) the semantic CHAT/DELIBERATE classifier, (b) local pack relevance, and (c) manifest-based domain matches among connected peers.

All inference, retrieval, and final synthesis remain on the user’s machine. The OCC broker only routes messages.

## Preconditions and Inputs

- Local expert packs: markdown wiki pages under expert-packs/<domain>/wiki/ with searchable content.
- Retrieval: keyword search over markdown pages with IT+EN stop words; a pack is “relevant” if ≥ 300 characters of content are retrieved for the query.
- Peers: discovered via the OCC WebSocket broker; each peer exposes GET /manifest with advertised domains.
- Classifier: fast local LLM gate deciding CHAT (0) vs DELIBERATE (1).
- Override: prefixing the query with ! forces DELIBERATE.

## CHAT vs DELIBERATE Classifier

- Purpose: Avoid unnecessary retrieval and networking for generic conversation.
- Spec:
  - Binary output: 0 (CHAT) or 1 (DELIBERATE).
  - Domain-agnostic rule: “Are we conversing, or is documented knowledge required?”
  - When in doubt, prefer 0 (never trigger retrieval for generic chat).
  - Parameters: num_predict=3, temperature=0, optimized for speed.
- Behavior:
  - CHAT (0): conversational system prompt; no wiki context; no routing.
  - DELIBERATE (1): enables wiki retrieval plus technical system prompt and activates Three-Mode Routing.

User override: ! <query> → force DELIBERATE and bypass the classifier.

## Retrieval and Pack Relevance

- Search: keyword-based over local wiki markdown with bilingual stop-word filtering (IT+EN).
- Relevance threshold: a local pack is considered relevant if retrieved context length ≥ 300 characters.
- Context assembly: retrieved snippets are attached to LLM prompts for answer generation when in local or hybrid modes.

## Mode Definitions and Triggers

- local
  - Trigger: Local pack relevant (≥ 300 chars) AND no peer advertises a matching domain.
  - Behavior: Answer solely from the local pack.

- delegate
  - Trigger: Local pack not relevant AND at least one peer advertises a matching domain.
  - Behavior: Query is delegated to relevant peers; node aggregates peer answers and performs local synthesis.

- hybrid
  - Trigger: Local pack relevant AND peers advertise the same domain(s).
  - Behavior: Produce a local answer; concurrently request peer answers; perform synthesis over local + peer outputs.

Notes
- “Matching domain” comes from Level 1 manifest-based routing (see below).
- All modes execute the final synthesis step locally when multiple partial answers exist (e.g., multiple peers, or hybrid).

## Level 1 Routing — Manifest-Based Role Assignment

Each node exposes GET /manifest advertising its expert domains.

- Discovery:
  1. Fetch manifests from all connected peers in parallel.
  2. Tokenize the query and compute overlap with each peer’s advertised domains.
- Role assignment:
  - 1 relevant peer → assign role: expert.
  - 2 relevant peers, different domains → both are experts; synthesis is additive (“Integrate both expert perspectives — each covers a different domain.”)
  - 2 relevant peers, same domains → assign expert + contrarian; synthesis is adversarial (“Synthesize resolving disagreements, keep strongest points.”)

Example manifest:
```
GET /manifest
{
  "name": "node-123",
  "domains": ["docker", "mcp"]
}
```

## Network Execution Path (Broker)

- Topology: All nodes open outbound WebSocket connections to the broker (no inbound/NAT issues).
- Broker responsibilities:
  - Maintain registry of connected nodes and their manifests.
  - Forward queries to nodes that advertise relevant domains.
  - Aggregate and return peer responses to the requester.
- Local responsibilities (always):
  - Knowledge storage (packs), retrieval, LLM inference, and final synthesis.

## Roles and Synthesis

- Roles:
  - expert — primary domain answerer.
  - contrarian — stress-tests/hedges against the expert when overlapping domains exist.
  - synthesizer — composes the final answer from multiple partials (local + peer).
- Synthesis modes:
  - Additive: merge complementary domain answers.
  - Adversarial: reconcile disagreements within the same domain; keep strongest arguments and discard weaker ones.

These roles live in the OCC Node deliberation engine (deliberation/roles.py) and are triggered by manifest-based routing outcomes.

## Tools Availability (Mode-Agnostic)

The following tools are available to LLM calls in all modes (not restricted to DELIBERATE-only phases):
- web_search — DuckDuckGo (ddgs), only when explicitly requested.
- fetch_url — HTTP fetch + BeautifulSoup4 parsing.
- read_file / write_file — sandboxed to workspace/.
- list_files — enumerate workspace.
- run_code — Python subprocess in workspace/, timeout 30s, path traversal blocked.

## Memory and Context

- Per-session conversational memory: self._history (max 1000 messages).
- All OCC models: 262K context window, reducing truncation risk during hybrid syntheses.
- /clear resets history and context counters. Post-answer visual indicator shows token usage.

## Algorithmic Flow

Pseudocode for end-to-end routing:

```
def handle_query(user_input, peers, local_pack):
    forced = user_input.startswith("!")
    mode_gate = 1 if forced else classify_chat_vs_deliberate(user_input)  # 0/1

    if mode_gate == 0:
        return llm_chat(user_input)  # conversational, no retrieval/routing

    # DELIBERATE path
    local_hits = retrieve_local(local_pack, user_input)  # keyword search w/ stop-words
    local_relevant = (len(local_hits.text) >= 300)

    peer_manifests = parallel_fetch_manifests(peers)  # GET /manifest
    relevant_peers = match_domains(peer_manifests, tokenize(user_input))

    if local_relevant and not relevant_peers:
        # local mode
        return answer_from_local(local_hits)

    if not local_relevant and relevant_peers:
        # delegate mode
        peer_answers = parallel_query_peers(relevant_peers, user_input)
        roles = assign_roles(relevant_peers)  # expert[, contrarian]
        return synthesize(None, peer_answers, roles)

    if local_relevant and relevant_peers:
        # hybrid mode
        local_answer = answer_from_local(local_hits)
        peer_answers = parallel_query_peers(relevant_peers, user_input)
        roles = assign_roles(relevant_peers)
        return synthesize(local_answer, peer_answers, roles)

    # No local relevance and no relevant peers → fall back to conversational answer or minimal local attempt
    return llm_chat(user_input)
```

Notes
- classify_chat_vs_deliberate: num_predict=3, temperature=0.
- retrieve_local: applies IT+EN stop words; builds context for answer_from_local.
- assign_roles: Level 1 policy (expert vs expert+contrarian; additive vs adversarial synthesis).

## Operational Characteristics

- Latency behavior:
  - local: single-node retrieval + generation.
  - delegate: network round-trip to peer experts + local synthesis.
  - hybrid: local answer in parallel with peer answers; synthesis over multiple partials.
- Resource usage:
  - Model tiers auto-selected by detected VRAM; models kept resident (keep_alive=-1) for session performance consistency.
- Observability:
  - deliberation_log.md append-only record of routed decisions and roles.

## CLI Controls

- ! <query> — force DELIBERATE mode.
- /peers — list currently registered broker peers with their manifests.
- /clear — reset conversation history and context counters.
- /unload — evict model from VRAM.
- /load — reload model into VRAM.

## Security and Data Flow

- Local-only:
  - Pack content (markdown), retrieval/index, LLM inference, final synthesis.
- Broker-only:
  - Connection multiplexing, manifest registry, query forwarding, response aggregation.
- Federated deployment:
  - OCC_BROKER_URL configurable; any compatible broker can be used (university/community/self-hosted).

## Key Points

- Three-mode routing chooses among local, delegate, and hybrid based on classifier output, local pack relevance (≥ 300 chars), and peer domain matches.
- Level 1 routing uses peer manifests to assign expert/contrarian roles and select additive vs adversarial synthesis.
- All knowledge, retrieval, inference, and final synthesis stay local; the broker is a stateless router.
- Tools (web_search, fetch_url, filesystem, run_code) are available in all modes; they are not tied to routing decisions.
- The CHAT/DELIBERATE classifier is minimal, deterministic (temperature=0), and defaults to CHAT to avoid unnecessary retrieval/networking.