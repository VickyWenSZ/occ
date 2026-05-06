---
title: Open Cognitive Commons (OCC)
slug: open-cognitive-commons-occ
source: occ
confidence: high
tags: [distributed-ai, mixture-of-experts, expert-packs, websocket-broker, llm-wiki]
---

# Open Cognitive Commons (OCC)

Open Cognitive Commons (OCC) is a distributed AI system implementing a decentralized Mixture-of-Experts (MoE) across Internet-connected user machines. Each node runs a small, local LLM specialized by an “expert pack” and collaborates via a lightweight broker to form a deliberative committee. The end-user experience is a simple chat interface; all routing, retrieval, and synthesis are automated and kept local where possible.

Core tenets:
- Decentralized MoE: many small, specialized LLMs collaborate instead of a single centralized model.
- Anti-GEO (Generative Engine Optimization): no web crawling; knowledge originates from curated, community-approved sources compiled into expert packs with public review.
- Privacy by design: knowledge (packs), retrieval, inference, and final synthesis remain on user machines; the broker only forwards messages.

## Architecture Overview

Three primary components:

1) OCC Node (user runtime)
- Python package / CLI.
- Runs a local LLM via Ollama (Qwen family).
- Manages expert pack retrieval and local search.
- Executes deliberation locally and/or across peers.
- Exposes/consumes a manifest of domains for role routing.
- Provides agentic tools (web_search, fetch_url, run_code, filesystem sandbox).
- Connects to a WebSocket broker for distributed deliberation.

2) OCC Forge (knowledge preparation)
- GUI (Gradio) for converting approved sources (URLs/files) into a structured LLM Wiki.
- GPT-5 via OpenAI Responses API to extract concepts and write/update dense wiki pages.
- Maintains an auditable manifest (sources + hashes), index, and ingest log.

3) OCC Hub (future)
- Public catalog and source registry governed by the community.
- Distributes packs and coordinates domain assignment/balancing.
- Lives at opencognitivecommons.org.

## Expert Packs and the LLM Wiki Pattern

OCC adopts a structured “LLM Wiki” pattern (inspired by Karpathy, 2026) rather than classic RAG:

- Classic RAG: raw sources are chunked at query time; minimal accumulation; the LLM “rediscovers” relations per query.
- LLM Wiki (OCC): sources are ingested into dense, cross-referenced wiki pages ahead of time; contradictions are flagged; knowledge compounds and is reusable.

Pack layout:
```
expert-packs/<domain>/
  wiki/
    concepts/*.md     # dense factual pages optimized for LLMs
    index.md          # generated catalog of pages
    log.md            # append-only ingest log with timestamps and sources
    schema.md         # pack conventions and schema
  manifest.yaml       # name, version, domains, sources (url+date+hash), signature
```

Current packs:
- mcp/ — Model Context Protocol (14 wiki pages)
- docker/ — Docker, containerization, Compose, networking (32+ wiki pages)

Lifecycle operations:
1) INGEST
- LLM reads a new source, extracts concepts, writes/updates wiki pages.
- index.md and log.md regenerated/appended; manifest updated.

2) QUERY
- LLM consults index.md, selects relevant pages, composes answers with citations.

3) LINT
- Health checks for contradictions, orphan pages, obsolete claims, missing cross-references.

## OCC Forge: Ingestion Pipeline

Launch:
```
python forge/app.py
```
Pipeline per source:
1) gpt-5-mini → extract_concepts() → JSON array of {slug, title, summary}.
2) For each concept:
   - Existing slug: update_wiki_page() merges new evidence into the page (reads existing + new source, enriches, flags contradictions with lines prefixed by "> ⚠️ Conflict:").
   - New slug: write_wiki_page() creates a fresh page.
3) Update index.md, append to log.md, refresh manifest.yaml.

Forge implementation notes:
- Python + Gradio UI.
- OpenAI Responses API (POST /v1/responses); never Chat Completions.
- load_dotenv(override=True), 3 automatic retries, max_output_tokens: 32000, timeout=None.

## OCC Node: Deliberation Engine

Semantic classifier (pre-router):
- Decides mode per query: 0=CHAT (general conversation) vs 1=DELIBERATE (documented knowledge required).
- Binary output {0,1}, num_predict=3, temperature=0, fast.
- Rule is domain-agnostic; “when in doubt, prefer 0”.
- User override: prefix query with “!” to force DELIBERATE.

Three-mode routing (with peers connected):
- local: local pack relevant (≥300 chars retrieved) and no peer with matching domain → answer from local pack only.
- delegate: local pack not relevant but some peer matches domain → delegate to peer(s), then locally synthesize.
- hybrid: local pack relevant and peers match → combine local and peer answers, then synthesize.

Level 1 routing — manifest-based role assignment:
- Each node serves GET /manifest listing its covered domains.
- Steps:
  1) Fetch all peer manifests in parallel.
  2) Tokenize query; compute overlap with peer domains.
  3) If 1 peer relevant → assign role: expert.
  4) If 2 peers relevant, different domains → both expert; perform additive synthesis (“Integrate both expert perspectives — each covers a different domain”).
  5) If 2 peers relevant, same domains → assign expert + contrarian; perform adversarial synthesis (“Synthesize resolving disagreements, keep strongest points”).

Agentic tools (always available; opt-in, never silent):
- web_search — via DuckDuckGo (ddgs); used only on explicit request.
- fetch_url — HTTP fetch + BeautifulSoup4 parse.
- read_file / write_file — within workspace/ sandbox.
- list_files — enumerates workspace content.
- run_code — executes Python in subprocess (cwd=workspace/, timeout=30s, path traversal blocked).

Retrieval:
- Keyword search across pack markdown.
- Stop-words for IT+EN to reduce false matches.
- Relevance threshold: ≥300 characters retrieved to consider the pack “relevant”.

Conversational memory:
- self._history accumulates up to 1000 messages; passed to each LLM call.
- All OCC models run with 262K context; /clear resets history and context counters.
- Visual context usage indicator after responses, e.g.: “ctx [████░░░░] 3,241 / 32,768 tokens (9.9%)” (scaled to current model).

## Models and Hardware Tiers

All tiers use Qwen family via Ollama, with:
- Native vision (early fusion).
- 262K context across tiers.
- Uniform “thinking mode” toggled via top-level parameter think=False in ollama.chat().
- keep_alive=-1 keeps models in VRAM throughout the session.

Tiers:
- Micro (CPU): qwen3.5:2b Q4_K_M — CPU-only; slower.
- Small (4GB VRAM): qwen3.5:4b Q4_K_M.
- Mid (8GB): qwen3.5:9b Q4_K_M — default tested.
- Large (16GB): qwen3.6:27b Q4_K_M — suitable for 24GB GPUs (e.g., 3090/4090).
- XL-32 (32GB): qwen3.5-122b-a10b IQ2_M — MoE: 122B total, ~10B active.
- XL-48 (48GB): qwen3.5-122b-a10b IQ3_S.
- Server (64GB+): qwen3.5-122b-a10b Q4_K_M — near full-precision quality.

Automatic VRAM detection selects the appropriate tier and pulls the model if missing.

## Network Architecture: WebSocket Broker

The broker provides message routing only; it is not a knowledge or inference server.

Data flow:
- Local-only: packs, retrieval, LLM inference, and final synthesis never leave the node.
- Broker duties: maintain a registry of connected nodes + their manifests; forward queries to relevant peers; aggregate peer responses for the requester.

Why a broker (vs P2P or centralized knowledge):
- All connections outbound (like a browser) → no NAT traversal issues.
- Low cost: ~€5.71/month on Hetzner for the first ~1,000 nodes; scales linearly.
- Federated: anyone can run a compatible broker (universities, communities, self-hosted). Nodes accept OCC_BROKER_URL configuration, similar to email/Mastodon federation.

Reference broker (live):
- Domain: broker.opencognitivecommons.org (SSL via Let’s Encrypt, auto-renew).
- Stack: FastAPI + WebSockets + Nginx (proxy_read_timeout 600s) + Systemd.
- Infra: Hetzner CX23, Ubuntu 24.04.
- Implementation: ~200–300 lines of Python.

Example routing sequence:
- Node A opens outbound WS to broker; broker maintains manifests for Node B, C, ...
- Node A submits a query tagged with desired domains (e.g., “docker+mcp”).
- Broker forwards to domain-matching peers; peers run local retrieval + LLM; broker aggregates peer responses; Node A synthesizes final answer locally.

## CLI and Operations

Commands:
- /peers — list currently registered peers on the broker.
- /clear — reset conversational history and context counters.
- /unload — free VRAM (unload model from Ollama).
- /load — reload model into VRAM.
- ! <query> — force DELIBERATE mode (bypass classifier).

Quickstart:
```
git clone https://github.com/VikFinlay/occ.git
cd occ
pip install -r node/requirements.txt
python node/apps/cli/main.py
```

Forge launch:
```
python forge/app.py
```

## Directory Structure (monorepo)

```
OCC/
  forge/
    app.py                 # Gradio GUI
    _llm.py                # OpenAI Responses API client
    _sources.py            # file/URL readers, PDF parser
    _wiki.py               # wiki file ops
    _manifest.py           # manifest.yaml management
    OPENAI_RESPONSES_API_GUIDE.md
  node/
    deliberation/
      engine.py            # local + distributed deliberation + role routing
      classifier.py        # CHAT(0) vs DELIBERATE(1) router
      roles.py             # answerer, expert, contrarian, synthesizer
      tools.py             # web_search, fetch_url, read/write/list files, run_code
    expert_runtime/
      pack.py              # ExpertPack loader
    hardware.py            # VRAM detection → model tier selection
    server/
      server.py            # FastAPI (local HTTP server)
      broker_agent.py      # WebSocket agent to connect to broker
      client.py            # async client for peer calls via broker
    retrieval/
      search.py            # keyword search over wiki markdown
    apps/cli/
      main.py              # CLI entry point
      config.py            # Node configuration
  expert-packs/
    mcp/
    docker/
  workspace/               # sandbox for agent tools (gitignored)
  deliberation_log.md      # append-only log of deliberations
```

## Technology Stack

- Local LLM: Ollama + Qwen 3.5/3.6 family (vision-capable; 262K context).
- Local inference API: ollama Python SDK.
- Knowledge preparation: OpenAI GPT-5 via Responses API (POST /v1/responses).
- Node server: FastAPI + Uvicorn.
- Node networking: httpx (async) + websockets.
- GUI (Forge): Gradio.
- Web search tool: duckduckgo_search (ddgs).
- HTML parsing: BeautifulSoup4.
- PDF parsing: integrated in forge/_sources.py.
- Broker: FastAPI + WebSockets + Nginx; infra on Hetzner CX23; Ubuntu 24.04; Systemd; Let’s Encrypt.
- Packaging: pip + requirements.txt.
- VCS: Git + GitHub (public, MIT license).
- Repo: https://github.com/VikFinlay/occ

## Governance, Integrity, and Anti-GEO

- Anti-GEO policy: nodes never crawl the open web. Only expert packs, built from community-approved sources with public review, feed the system.
- Provenance and integrity:
  - manifest.yaml records source URLs, dates, and content hashes (SHA-256).
  - log.md is append-only with ingest history.
  - Future: cryptographic signatures by OCC.org; reputation system; public benchmarks.
- OCC Hub (after 5–6 packs): community source registry, public pack catalog, and domain balancing.

## Status and Roadmap

- Phase 1: Local single-node, wiki retrieval, single LLM call — complete.
- Phase 2: P2P lite (FastAPI HTTP, 2 nodes, parallel roles, synthesis) — complete.
- Phase 3: OCC Forge + Docker pack + intelligent role routing — complete.
- Phase 4: WebSocket broker live at broker.opencognitivecommons.org — complete.
- Phase 5: Desktop GUI — Tauri + React — planned.
- Phase 6: Reputation, source registry, pack integrity (SHA-256 + OCC.org signature), public benchmarks — planned.
- OCC Hub: public pack catalog post 5–6 packs — planned.

## Example Manifest (conceptual)

```yaml
name: occ-docker-pack
version: 0.3.1
domains:
  - docker
  - containers
  - compose
sources:
  - url: https://docs.docker.com/engine/
    date: 2026-04-22
    sha256: <content-hash>
signature:
  alg: ed25519
  signer: occ.org
  sig: <base64-signature>
```

## Pseudocode: Query Flow

```python
def handle_query(q):
    mode = classify(q)  # 0=CHAT, 1=DELIBERATE
    if user_forced_deliberate(q):
        mode = 1

    if mode == 0:
        return llm_chat(q, history)

    local_hits = retrieve_local_wiki(q)
    peers = broker.list_peers_with_manifest()
    relevant_peers = match_peers(peers, q)

    if local_hits.retrieved_chars >= 300 and not relevant_peers:
        return answer_from_local(local_hits, q)

    if not local_hits.relevant and relevant_peers:
        peer_answers = ask_peers(relevant_peers, q)
        return synthesize(peer_answers, q)

    if local_hits.relevant and relevant_peers:
        local_answer = answer_from_local(local_hits, q)
        peer_answers = ask_peers(relevant_peers, q)
        return synthesize([local_answer] + peer_answers, q)
```

## Security Notes

- No secrets transmitted to broker; payloads are limited to queries and model-produced answers.
- Tools operate within workspace/ sandbox; Python execution via run_code is time- and path-restricted.
- Web search is opt-in; never performed silently.
- Pack integrity planned with cryptographic signing; current manifests include source hashes.

## Key Points

- OCC decentralizes MoE: many small, specialized local LLMs collaborate via a lightweight broker; knowledge and inference stay local.
- Expert packs implement an LLM Wiki (ingest/query/lint), enabling cumulative, cross-referenced knowledge without web crawling (Anti-GEO).
- Deliberation engine uses a fast CHAT vs DELIBERATE classifier, three-mode routing (local/delegate/hybrid), and role-based synthesis (expert/contrarian).
- Forge builds and maintains packs using the OpenAI Responses API, Gradio UI, manifests with source hashes, and an append-only ingest log.
- Production-ready WS broker (FastAPI+Nginx) is live and federable; nodes auto-select Qwen tier by VRAM and keep models warm in VRAM (keep_alive=-1).