---
title: Expert Pack — LLM Wiki Pattern
slug: expert-pack-llm-wiki
source: occ
confidence: high
tags: [mixture-of-experts, llm-wiki, expert-packs, occ, rag]
---

# Expert Pack — LLM Wiki Pattern

The Expert Pack — LLM Wiki pattern is a curated-knowledge architecture for LLMs that replaces on-the-fly chunked RAG with a persistent, structured wiki authored by LLMs and reviewed by a community. It is the core knowledge unit in Open Cognitive Commons (OCC), a decentralized Mixture-of-Experts (MoE) network where users run small, specialized local LLMs that deliberate collectively over a brokered WebSocket fabric.

Unlike web-crawling systems, OCC adheres to an anti-GEO (Generative Engine Optimization) philosophy: nodes never crawl the open web. Expert Packs are built only from approved sources via community processes with public review, protecting against manipulation and polluted inputs.

## Concept and Motivation

- Distributed MoE: Many user nodes each run a small, domain-expert LLM; together they form a deliberative committee that behaves like a distributed MoE across the internet.
- UX parity: End-user experience is a simple chat; the distributed retrieval and deliberation remain invisible.
- Anti-GEO: Knowledge comes exclusively from curated Expert Packs. No opportunistic web crawling.
- LLM Wiki versus classic RAG:
  - Classic RAG: Raw sources chunked at query time; no durable accumulation; the LLM re-derives connections every query.
  - LLM Wiki: Sources are ingested into a persistent, cross-referenced wiki; contradictions are tracked; knowledge composes and improves over time.

## Expert Pack Structure

Each pack is a self-contained, LLM-optimized wiki plus a manifest for distribution.

Directory layout:
```
expert-packs/<domain>/
  wiki/
    concepts/*.md   # dense, factual pages optimized for LLM consumption
    index.md        # auto-regenerated index of all pages
    log.md          # append-only ingest log (timestamp + source)
    schema.md       # conventions and formatting rules for the pack
  manifest.yaml     # name, version, domains, sources (url+date+hash), signature
```

Current examples:
- mcp/ — Model Context Protocol (14 pages)
- docker/ — Docker, containerization, Compose, networking (32+ pages; produced with Forge)

Manifest fields (Hub-ready):
- name, version
- domains: list of domain tags
- sources: array of {url, date, sha256}
- signature: cryptographic signature (planned OCC.org signing)
- integrity policies: used by future OCC Hub (catalog and distribution)

Example manifest.yaml (illustrative):
```yaml
name: docker
version: 0.3.2
domains: [containers, docker, networking]
sources:
  - url: https://docs.docker.com/engine/
    date: 2026-04-20
    sha256: 6f7d...c1
  - url: https://github.com/docker/compose
    date: 2026-04-20
    sha256: b2a3...9d
signature: <OCC-signature-placeholder>
```

## Core Operations

The pattern defines three LLM-mediated operations over packs:

1) INGEST
- Input: new source (URL or file).
- Steps:
  - extract_concepts(): gpt-5-mini produces JSON [{slug, title, summary}].
  - For each concept:
    - If slug exists: update_wiki_page(): read existing page + new source; enrich while preserving content; flag contradictions with:
      > ⚠️ Conflict: <brief conflicting claims + citations>
    - If slug new: write_wiki_page(): create de-novo dense, factual page.
  - Regenerate wiki/index.md; append wiki/log.md; update manifest.yaml.

2) QUERY
- LLM scans wiki/index.md to identify relevant concept pages.
- Synthesizes an answer with citations to pages used.
- Used by OCC Node in DELIBERATE mode.

3) LINT
- Health checks:
  - Flag contradictions accumulated across sources.
  - Detect orphan pages (unreferenced).
  - Identify obsolete claims.
  - Recommend missing cross-references.

## OCC Forge (Knowledge Preparation)

Forge is the pack-authoring tool used by admins/community to build and maintain Expert Packs.

- Launch: python forge/app.py (Gradio GUI).
- Pipeline per source:
  - gpt-5-mini → extract_concepts() → JSON array.
  - Per concept:
    - Existing page: update_wiki_page() with conflict flagging.
    - New page: write_wiki_page().
  - Update index.md, log.md, manifest.yaml.
- LLM/API:
  - OpenAI Responses API (POST /v1/responses), not Chat Completions.
  - 3 automatic retries, max_output_tokens=32000, timeout=None.
  - load_dotenv(override=True) for config/secrets.
- Tech: Python, Gradio, OpenAI Responses API, internal file/URL/PDF readers.

## OCC Node (Deliberation Engine)

The Node is the end-user runtime: local LLM via Ollama, pack retrieval, local/distributed deliberation, CLI chat, tools, and broker connectivity.

### Semantic Classifier (Mode Router)
- Pre-query classifier decides:
  - 0 (CHAT): general conversation → no wiki context; conversational system prompt.
  - 1 (DELIBERATE): documented knowledge required → wiki retrieval + technical system prompt.
- User override: prefix ! to force DELIBERATE.
- Parameters: binary 0/1; num_predict=3; temperature=0; very fast.
- Policy: When in doubt, prefer 0 — never trigger wiki retrieval for casual chat.

### Three-Mode Routing (with connected peers)
- local: Local pack relevant (≥300 chars retrieved) and no peers matching domain → answer solely from local pack.
- delegate: Local pack not relevant; peers match domain → delegate to peers; locally synthesize returned answers.
- hybrid: Local pack relevant and peers match domain → combine local and peer answers; synthesize.

Level-1 role assignment (manifest-based):
1) Fetch all peers’ GET /manifest in parallel.
2) Tokenize the query and score overlap with each peer’s domains.
3) Routing:
   - 1 relevant peer → expert role.
   - 2 peers, different domains → both expert; additive synthesis (“integrate both expert perspectives”).
   - 2 peers, same domain → expert + contrarian; adversarial synthesis (“resolve disagreements; keep strongest points”).

### Tools (always available)
- web_search: DuckDuckGo (ddgs). Only on explicit request.
- fetch_url: requests + BeautifulSoup4.
- read_file / write_file: filesystem in workspace/ sandbox.
- list_files: enumerate workspace.
- run_code: execute Python in subprocess; cwd=workspace; timeout=30s; no path traversal.

### Conversational Memory
- self._history: rolling message list passed to all LLM calls; up to 1000 messages.
- All OCC models: 262K context.
- /clear resets history and a context counter.
- Visual context usage indicator after each reply (e.g., ctx [████░░░░] 3,241 / 32,768 tokens).

### Retrieval
- Keyword search over pack markdown with IT+EN stop words to reduce false matches.
- Relevance threshold: ≥300 characters retrieved to consider a pack “relevant”.

## Network Architecture (WebSocket Broker)

OCC employs a brokered WebSocket network (not P2P and not centralized knowledge).

- Broker role: Routing only. Not a knowledge or inference server.
- Flow:
  - All nodes open outbound WebSockets to broker.opencognitivecommons.org.
  - A node submits a query annotated with desired domains (e.g., “docker+mcp”).
  - Broker forwards to peer nodes advertising matching domains (via their manifests).
  - Peers perform local retrieval + local LLM inference and return answers.
  - Broker aggregates, requester synthesizes the final answer locally.

Advantages:
- Outbound-only connections: no NAT traversal complexity.
- Cost-efficient: ~€5.71/month on Hetzner for first ~1,000 nodes; scales linearly.
- Federable: Anyone can host a compatible broker (university, community, self-hosted). Nodes accept OCC_BROKER_URL in config (federation akin to email/Mastodon).

Live broker stack:
- Server: Hetzner CX23, Ubuntu 24.04; IP 116.203.61.136
- Domain: broker.opencognitivecommons.org; SSL via Let’s Encrypt (auto-renewal)
- Software: FastAPI + WebSockets + Nginx (proxy_read_timeout=600s) + Systemd
- Size: ~200–300 lines of Python

Local versus broker responsibilities:
- Always local: pack storage (markdown), retrieval, inference, final synthesis.
- Broker: presence registry (manifests), domain-aware query routing, answer collection.

## Model Tier System (Ollama + Qwen family)

Unified model family and UX across hardware tiers; all support:
- Vision natively (early fusion).
- 262K context.
- Thinking mode on/off via top-level think=False in ollama.chat().

Tiers:
- Micro (CPU): qwen3.5:2b Q4_K_M — CPU-only; warn about speed.
- Small (4GB VRAM): qwen3.5:4b Q4_K_M.
- Mid (8GB VRAM): qwen3.5:9b Q4_K_M — default tested.
- Large (16GB VRAM): qwen3.6:27b Q4_K_M — suitable for RTX 3090/4090 24GB.
- XL-32 (32GB VRAM): qwen3.5-122b-a10b IQ2_M — MoE 122B total, 10B active.
- XL-48 (48GB VRAM): qwen3.5-122b-a10b IQ3_S.
- Server (64GB+ VRAM): qwen3.5-122b-a10b Q4_K_M — near full-precision quality.

Node behavior:
- Auto-detect VRAM → select tier → ollama pull if missing.
- keep_alive=-1 on all calls to keep model resident in VRAM for the session.

## CLI

Commands:
- /peers    — list currently registered peers (live from broker)
- /clear    — reset conversational history and context counter
- /unload   — free VRAM (unload model from Ollama)
- /load     — reload model into VRAM
- ! <query> — force DELIBERATE mode (bypass classifier)

## Directory Structure (Monorepo)

```
OCC/
  forge/
    app.py                  # Gradio GUI
    _llm.py                 # OpenAI Responses API client
    _sources.py             # file reader + URL fetcher + PDF parser
    _wiki.py                # wiki file ops
    _manifest.py            # manifest.yaml management
    OPENAI_RESPONSES_API_GUIDE.md
  node/
    deliberation/
      engine.py             # local + distributed + role routing
      classifier.py         # CHAT(0) vs DELIBERATE(1)
      roles.py              # answerer, expert, contrarian, synthesizer
      tools.py              # web_search, fetch_url, read_file, write_file, run_code
    expert_runtime/
      pack.py               # ExpertPack loader
    hardware.py             # VRAM tier detection → model
    server/
      server.py             # FastAPI server (local node HTTP)
      broker_agent.py       # WebSocket agent to broker
      client.py             # calls to peers via broker
    retrieval/
      search.py             # keyword search over wiki markdown
    apps/cli/
      main.py               # CLI entrypoint
      config.py             # Node configuration
  expert-packs/
    mcp/                    # MCP wiki (14 pages)
    docker/                 # Docker ecosystem wiki (32+ pages)
  workspace/                # agent tool sandbox (gitignored)
  deliberation_log.md       # append-only log of all deliberations
```

## Technology Stack

- Local LLM: Ollama + Qwen 3.5/3.6 family
- Local inference API: ollama Python SDK
- Knowledge preparation: OpenAI GPT-5 via Responses API
- Node server: FastAPI + Uvicorn
- Node client: httpx (async) + websockets
- GUI (Forge): Gradio
- Web search tool: duckduckgo_search (ddgs)
- HTML parsing: BeautifulSoup4
- PDF parsing: integrated in _sources.py
- Broker server: FastAPI + WebSockets + Nginx
- Broker infra: Hetzner CX23, Ubuntu 24.04, Systemd, Let’s Encrypt
- Packaging: pip, requirements.txt
- VCS: Git, GitHub (MIT license)

## Status and Roadmap

- Phase 1: Local single-node, wiki retrieval, single LLM call — complete.
- Phase 2: P2P lite (FastAPI HTTP, 2 nodes, parallel roles, synthesis) — complete.
- Phase 3: OCC Forge + Docker pack + intelligent role routing — complete.
- Phase 4: WebSocket broker live at broker.opencognitivecommons.org — complete.
- Phase 5: Desktop GUI — Tauri + React.
- Phase 6: Reputation system, source registry, pack integrity (SHA-256 + OCC.org cryptographic signing), public benchmarks.
- OCC Hub: public pack catalog once 5–6 packs exist.

## Repository and Quickstart

Public repo: https://github.com/VikFinlay/occ (MIT)

Quickstart:
```
git clone https://github.com/VikFinlay/occ.git
cd occ
pip install -r node/requirements.txt
python node/apps/cli/main.py
```

## Governance and Integrity

- Community-reviewed sources only; no general web crawling (anti-GEO).
- Manifest tracks provenance (url, date, sha256).
- Future: OCC Hub for pack catalog, community-governed source registry, domain-balanced distribution.
- Future: cryptographic signing of manifests by OCC.org; reputation signals for nodes/packs.

## Query and Deliberation Flow (Illustrative)

```
[User Node] --(outbound WS)--> [OCC Broker] <--(outbound WS)-- [Peer Nodes...]
   |                                 |
   |---- query: "docker+mcp" ------->|
   |                                 |-- forwards to peers advertising docker+mcp
   |<--- aggregated peer answers ----|
   |-- local retrieval + synthesis --|
   |----------- final answer --------|
```

## Key Points

- Expert Packs implement an LLM-authored, persistent wiki that accumulates, cross-references, and flags contradictions—superseding ad-hoc chunked RAG.
- OCC Nodes route queries via a fast CHAT vs DELIBERATE classifier, then perform local retrieval and distributed synthesis through a federable WebSocket broker.
- Forge provides deterministic ingestion (concept extraction, page update/create, index/log/manifest updates) using the OpenAI Responses API.
- A unified Qwen model family across hardware tiers (vision, 262K context, thinking-mode toggle) enables consistent behavior from CPU to multi-GPU.
- The broker routes only; all knowledge, retrieval, inference, and synthesis remain local, preserving privacy and decentralization.