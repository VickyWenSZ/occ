---
title: Retrieval and Conversational Memory
slug: retrieval-and-conversational-memory
source: occ
confidence: high
tags: [retrieval, memory, llm, occ, routing]
---

# Retrieval and Conversational Memory

This page describes how OCC implements retrieval over curated expert packs and how conversational memory is maintained and applied during inference. It covers the triggering logic (classification), local and distributed routing, search mechanics, memory limits, and UX controls.

## Knowledge Substrate: Expert Pack LLM Wiki (vs. classic RAG)

- Source model: OCC uses “expert packs” that are LLM-written, structured wiki corpora, inspired by Karpathy’s LLM Wiki pattern.
- Difference from classic RAG:
  - Classic RAG: raw sources are chunked at query-time; no accumulation or cross-references.
  - LLM Wiki: ingestion transforms sources into dense, cross-referenced wiki pages; knowledge accumulates, contradictions are flagged ahead of time, and the index is maintained.
- Structure relevant to retrieval:
  - expert-packs/<domain>/wiki/
    - concepts/*.md — dense factual pages optimized for LLM consumption
    - index.md — catalog of pages (regenerated on ingest)
    - log.md — append-only ingest log with timestamp and source
    - schema.md — pack conventions
  - manifest.yaml — metadata and provenance (name, version, domains, sources with url/date/hash, signature)
- Quality loop:
  - Forge INGEST builds/updates wiki pages (with conflict flags).
  - LINT catches contradictions, orphans, missing cross-references, and obsolete claims, improving retrieval precision over time.

## Mode Selection: When Retrieval Is Triggered

- Pre-query classifier (LLM):
  - Output: 0 (CHAT) or 1 (DELIBERATE).
  - Policy: “When in doubt, prefer 0.” Never trigger retrieval for generic small talk.
  - Config: binary output, num_predict=3, temperature=0 for speed and stability.
- User override:
  - Prefixing a query with “!” forces DELIBERATE, bypassing the classifier.
- Prompting:
  - CHAT: conversational system prompt, zero wiki context.
  - DELIBERATE: technical system prompt + retrieved wiki context.

## Retrieval Mechanics (Local)

- Corpus: local pack markdown files under expert-packs/<domain>/wiki/concepts.
- Search:
  - Keyword search across markdown pages.
  - Stop words: Italian and English, to reduce false positives on common words.
- Relevance threshold:
  - A pack is considered “relevant” if at least 300 characters of content are retrieved for the query.
  - This threshold governs routing decisions (local vs. delegate vs. hybrid).
- Anti-GEO compliance:
  - No web crawling by default; retrieval is strictly against curated expert packs.
  - web_search tool exists but is run only upon explicit tool invocation by the agent, not during default retrieval.

Pseudo-code (local retrieval gating):

```python
def classify(query) -> int:  # 0 or 1
    return llm_classifier(query, temperature=0)

def retrieve_local(query):
    results = keyword_search_wiki(query, stopwords_langs=["it", "en"])
    char_count = sum(len(r.snippet) for r in results)
    return results, char_count

def deliberate_pipeline(query, history):
    # 1) classify
    mode = classify(query)
    if mode == 0 and not query.startswith("!"):
        return respond_chat(query, history)

    # 2) force deliberate or classified deliberate
    local_results, local_chars = retrieve_local(query)
    local_relevant = (local_chars >= 300)

    # 3) distributed routing decision handled below
    return route_and_answer(query, history, local_results, local_relevant)
```

## Distributed Routing and Retrieval

- Three-mode routing:
  - local: local pack relevant (≥300 chars) and no peer with matching domain(s) → answer from local pack only.
  - delegate: local pack not relevant, but peers with matching domain(s) exist → forward to relevant peers; locally synthesize from peer answers.
  - hybrid: local pack relevant and peers have the same domain(s) → combine local answer with peer answers; synthesize.
- Level 1 role assignment (manifest-based):
  - Each node exposes GET /manifest listing domains.
  - Routing steps:
    1. Parallel fetch manifests from connected peers via the broker.
    2. Tokenize query; compute overlap with peer domains.
    3. 1 relevant peer → assign expert.
    4. 2 relevant peers, different domains → both expert; additive synthesis.
    5. 2 relevant peers, same domains → expert + contrarian; adversarial synthesis to resolve disagreements.
- Locality guarantees:
  - The broker only forwards messages; it is not a knowledge or inference server.
  - Retrieval, inference, and final synthesis always occur on each node locally. Peers independently perform their local retrieval over their local packs.
- Pack relevance and routing interplay:
  - The 300-character local relevance threshold directly selects among local/delegate/hybrid.
  - In hybrid mode, local retrieved context is combined with peer-provided reasoning for the final synthesis.

Pseudo-code (routing sketch):

```python
def route_and_answer(query, history, local_results, local_relevant):
    peers = fetch_peer_manifests()                  # via WebSocket broker
    relevant_peers = select_by_domain_overlap(query, peers)

    if local_relevant and not relevant_peers:
        return answer_with_local_wiki(query, history, local_results)

    elif not local_relevant and relevant_peers:
        peer_answers = ask_peers(query, relevant_peers)   # each peer does its own local retrieval
        return synthesize_peer_only(query, history, peer_answers)

    elif local_relevant and relevant_peers:
        local_answer = answer_with_local_wiki(query, history, local_results)
        peer_answers = ask_peers(query, relevant_peers)
        return synthesize_hybrid(query, history, local_answer, peer_answers)

    else:
        # fallback to CHAT if neither local nor peers seem relevant
        return respond_chat(query, history)
```

## Conversational Memory

- Data structure:
  - self._history: in-memory list of messages for the active session.
  - Format: typical chat turns, e.g., [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}, ...].
- Capacity and context:
  - Max 1000 messages stored per session.
  - All OCC models run with a large context (262K tokens), minimizing truncation risk.
- Lifecycle:
  - Every LLM call (CHAT or DELIBERATE) receives the current history plus mode-specific system prompt and, if deliberate, the retrieved wiki context.
  - /clear command resets the conversational history and context usage counter.
- UX visibility:
  - After each response, a context usage indicator is displayed, e.g., ctx [████░░░░] 3,241 / 32,768 tokens (9.9%) with color coding (green/yellow/red).
- Persistence:
  - Session-scoped by default (in-memory). Clearing or restarting the node drops the transient memory unless separately persisted by the application (not part of the base spec).

Pseudo-code (memory management):

```python
class Session:
    def __init__(self, max_messages=1000):
        self.history = []
        self.max_messages = max_messages

    def append(self, role, content):
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_messages:
            # FIFO truncation
            overflow = len(self.history) - self.max_messages
            self.history = self.history[overflow:]

    def clear(self):
        self.history = []

def respond(query, session):
    session.append("user", query)
    reply = deliberate_pipeline(query, session.history)
    session.append("assistant", reply)
    return reply
```

## Interaction Between Retrieval and Memory

- Memory informs retrieval indirectly:
  - The classifier and answer generation see the full conversation history, enabling better intent detection and disambiguation.
  - Retrieval itself is executed over wiki content using the latest user turn, not the entire history text, to keep search precise and cost-effective.
- Mode sensitivity:
  - CHAT mode uses history only; zero wiki context is injected.
  - DELIBERATE mode uses history + retrieved wiki snippets; the retrieved snippets are selected based on the latest query content.
- Forcing deliberate:
  - Prefix “!” ensures retrieval even if the classifier would pick CHAT (useful when the user knows the query requires documentation-backed knowledge).
- Tools and memory:
  - Agentic tools (web_search, fetch_url, read_file, write_file, list_files, run_code) may be invoked during either mode by the LLM. They do not alter retrieval rules but can augment answers. Web search runs only on explicit tool invocation, preserving anti-GEO defaults.

## Operational Notes and Safeguards

- Precision over recall:
  - The 300-character threshold avoids spurious retrieval for conversational queries.
  - IT+EN stop words reduce noise from common function words.
- Local-first and privacy:
  - Knowledge packs, retrieval, and inference remain on-device. Distributed operation shares only queries and synthesized answers via the broker; raw wiki content is not uploaded.
- CLI controls:
  - /clear resets memory and context counters.
  - ! <query> forces DELIBERATE retrieval.
  - /peers shows currently registered nodes (useful to anticipate delegate/hybrid behavior).

## Key Points

- OCC triggers retrieval only in DELIBERATE mode; a fast 0/1 classifier gates this, and “!” overrides to force it.
- Retrieval is keyword-based over local LLM Wiki pages with IT+EN stop words; ≥300 retrieved characters marks a pack as relevant.
- Routing is local/delegate/hybrid based on local relevance and peer domain manifests; each peer performs its own local retrieval.
- Conversational memory stores up to 1000 messages per session and is included in every LLM call; /clear resets it.
- All retrieval, inference, and synthesis occur locally on each node; the broker only forwards messages and aggregates responses.