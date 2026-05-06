---
title: OCC Node — Deliberation Engine
slug: occ-node-deliberation-engine
source: occ
confidence: high
tags: [distributed-ai, mixture-of-experts, retrieval, websocket-broker, qwen]
---

# OCC Node — Deliberation Engine

The OCC Node is the end-user runtime of the Open Cognitive Commons (OCC) system. It runs a local LLM, retrieves structured knowledge from “expert packs” (LLM Wiki pattern), and deliberates locally and across peers via a WebSocket broker. It routes queries between conversational chat and document-grounded deliberation, assigns roles to peers based on domain manifests, and synthesizes results. All knowledge, retrieval, inference, and final synthesis remain local to each node.

## Context and Philosophy

- Decentralized Mixture of Experts: each user runs a small, specialized LLM and participates in a distributed committee. Intelligence emerges collectively across internet-connected nodes.
- Anti-GEO (Generative Engine Optimization): nodes do not crawl the public web automatically; knowledge only comes from community-approved, reviewed sources compiled into expert packs (LLM Wiki).
- UX target: simple chat interface; routing, retrieval, and peer synthesis are transparent to the user.

## Responsibilities of OCC Node

- Local LLM runtime via Ollama (Qwen family; vision capable; 262K context; thinking mode toggle).
- Expert pack management and retrieval over structured wiki (concept pages, index, manifest, logs).
- Deliberation: semantic classification (chat vs deliberate), role routing (local, delegate, hybrid), multi-peer synthesis (additive/adversarial).
- Agent tools (web search, fetch, file I/O in sandbox, run_code).
- Network participation via WebSocket broker (federable; node advertises manifest domains).
- Conversational memory and context management.
- CLI interface and local HTTP server for node metadata (e.g., GET /manifest).

## Query Flow

1. Semantic Classifier runs on the user’s query to route between:
   - 0 (CHAT): general conversation; no wiki retrieval; conversational system prompt.
   - 1 (DELIBERATE): document-grounded; wiki retrieval + technical system prompt.
   - User override: prefixing query with “!” forces DELIBERATE.
2. If DELIBERATE, perform local retrieval against expert packs.
3. Three-Mode Routing:
   - local: local pack relevant; no peers matching domain → answer from local pack only.
   - delegate: local pack not relevant; peers with domain match → ask peers; locally synthesize.
   - hybrid: both local and peers relevant → local answer + peer answers → local synthesis.
4. Role Assignment (Level 1, manifest-based): peers are assigned expert/contrarian roles based on domain overlap; synthesis is additive for disjoint domains and adversarial when domains overlap.

All inference and synthesis happen locally; remote peers only return their own locally-grounded answers.

## Semantic Classifier

- Purpose: decide if the query needs documented knowledge.
- Output: binary 0/1.
- Parameters: num_predict=3, temperature=0 (fast, deterministic).
- Heuristic: “When in doubt, prefer 0 (CHAT)” to avoid unnecessary retrieval.
- Manual override: “! <query>” bypasses classifier, forcing DELIBERATE.

## Retrieval over Expert Packs (LLM Wiki)

- Store: expert-packs/<domain>/wiki/*.md with dense technical pages, index.md, log.md, schema.md; manifest.yaml at pack root.
- Retrieval: keyword search over Markdown pages with IT+EN stop words to reduce noise.
- Relevance threshold: pack considered relevant if ≥300 characters are retrieved for the query.
- Benefits vs classic RAG:
  - Persistent, structured wiki (accumulating knowledge, cross-references, flagged contradictions).
  - Query-time reads from curated pages rather than ad-hoc chunking raw sources.

Example pack inventory (as of current state):
- mcp/ — Model Context Protocol (14 wiki pages)
- docker/ — Docker ecosystem (32+ wiki pages; built with Forge)

## Three-Mode Routing and Role Logic

- Triggers:
  - local: local pack relevant; no peer domain match.
  - delegate: local pack not relevant; peer domain match exists.
  - hybrid: both local and peer domain matches.
- Level 1 Routing — Manifest-based Role Assignment:
  1. Each node serves GET /manifest with its domains.
  2. The deliberation engine fetches manifests from peers in parallel.
  3. Tokenize query; compute domain overlap.
  4. If 1 relevant peer → assign expert role.
  5. If 2 relevant peers with different domains → both expert; synthesis is ADDITIVE (“Integrate both expert perspectives — each covers a different domain”).
  6. If 2 relevant peers with the same domain → assign expert + contrarian; synthesis is ADVERSARIAL (“Synthesize resolving disagreements, keep strongest points”).
- Local roles: answerer (local), expert, contrarian, synthesizer modules orchestrated under deliberation/roles.py.

## Agent Tools (always available)

- web_search: DuckDuckGo (ddgs); only on explicit user request; no API key.
- fetch_url: HTTP GET + BeautifulSoup4 parsing.
- read_file / write_file: scoped to workspace/ sandbox.
- list_files: workspace inventory.
- run_code: execute Python in subprocess, cwd=workspace, timeout=30s; path traversal blocked.

## Conversational Memory and Context

- In-memory history: self._history holds message list for the session; included in each LLM call.
- Limits: up to 1000 messages (models support 262K tokens).
- Commands: /clear resets history and context counter.
- Context usage indicator after each response: e.g., “ctx [████░░░░] 3,241 / 32,768 tokens (9.9%)” with color cues.

## Network Architecture — WebSocket Broker

- Rationale: Pure P2P abandoned (NAT traversal complexity); centralized knowledge abandoned (kills OCC’s value). Broker is a “post office,” not a knowledge or inference server.
- Data locality: packs, retrieval, inference, and synthesis remain on each node.
- Broker duties:
  - Maintain registry of connected nodes and their manifests.
  - Route queries to peers with matching domains.
  - Aggregate peer responses back to requester.
- Transport:
  - Outbound-only WebSockets for all nodes (NAT-friendly).
  - Federable: any compatible broker can be deployed; nodes use OCC_BROKER_URL in config.
- Cost/scaling: ~€5.71/month on Hetzner for first ~1,000 nodes; scales linearly.
- Reference deployment:
  - Domain: broker.opencognitivecommons.org with SSL (Let’s Encrypt auto-renew).
  - Server stack: FastAPI + WebSockets + Nginx (proxy_read_timeout 600s) + Systemd.
  - Implementation: ~200–300 lines Python.

## Model Tier System (Ollama + Qwen)

- Common guarantees across tiers:
  - Qwen 3.5/3.6 family for consistent API and thinking mode.
  - Native vision (early fusion).
  - 262K context window (avoid truncation).
  - Thinking mode on/off via top-level think=False in ollama.chat().
- Tiers:
  - Micro (CPU): qwen3.5:2b Q4_K_M (no GPU; slower).
  - Small (4GB VRAM): qwen3.5:4b Q4_K_M.
  - Mid (8GB VRAM): qwen3.5:9b Q4_K_M (default tested).
  - Large (16GB VRAM): qwen3.6:27b Q4_K_M (e.g., RTX 3090/4090 24GB).
  - XL-32 (32GB VRAM): qwen3.5-122b-a10b IQ2_M (MoE: 122B total, 10B active).
  - XL-48 (48GB VRAM): qwen3.5-122b-a10b IQ3_S.
  - Server (64GB+ VRAM): qwen3.5-122b-a10b Q4_K_M (near full-precision quality).
- Runtime policy:
  - Auto-detect VRAM on startup → select tier → pull model if missing.
  - keep_alive=-1 for all calls to keep model in VRAM during session.

## CLI

- /peers — list peers registered on the broker in real time.
- /clear — reset conversational history and context counter.
- /unload — free VRAM (unload model from Ollama).
- /load — reload model into VRAM.
- ! <query> — force DELIBERATE mode (bypass classifier).

Example:
```
git clone https://github.com/VikFinlay/occ.git
cd occ
pip install -r node/requirements.txt
python node/apps/cli/main.py
```

## Directory Structure (selected)

- node/deliberation/
  - engine.py — DeliberationEngine (local + distributed + role routing).
  - classifier.py — chat(0) vs deliberate(1) router.
  - roles.py — answerer, expert, contrarian, synthesizer.
  - tools.py — web_search, fetch_url, read_file, write_file, run_code.
- node/expert_runtime/pack.py — ExpertPack loader.
- node/hardware.py — VRAM/tier detection → model selection.
- node/server/
  - server.py — local FastAPI server (HTTP endpoints, e.g., GET /manifest).
  - broker_agent.py — WebSocket agent to connect to broker.
  - client.py — async client for peer calls via broker.
- node/retrieval/search.py — keyword search over wiki markdown.
- node/apps/cli/
  - main.py — CLI entry point.
  - config.py — Config class.
- expert-packs/
  - mcp/, docker/ — curated LLM Wiki packs.
- workspace/ — sandbox for agent tools (gitignored).
- deliberation_log.md — append-only log of all deliberations.

## Tech Stack

- Local LLM: Ollama + Qwen 3.5/3.6.
- Inference API: ollama Python SDK.
- Knowledge preparation (Forge): OpenAI GPT-5 via Responses API (never Chat Completions).
- Node server: FastAPI + Uvicorn.
- Node client: httpx (async) + websockets.
- GUI (Forge): Gradio.
- Web search tool: duckduckgo_search (ddgs).
- HTML parsing: BeautifulSoup4.
- PDF parsing: integrated in Forge _sources.py.
- Broker: FastAPI + WebSockets + Nginx; Hetzner CX23; Ubuntu 24.04; Systemd.
- Packaging: pip + requirements.txt.
- VCS: GitHub (MIT license).

## Logging and Health

- deliberation_log.md: append-only record with timestamps and roles used.
- Lint/health (via Forge on packs): detect contradictions, orphan pages, obsolete claims, missing cross-references.
- Context usage indicator exposed after each response for transparency.

## Security and Data Locality

- Anti-GEO: no automated web crawling; only curated expert packs from community-approved sources.
- Data locality: knowledge, retrieval, inference, and synthesis stay on the node.
- Broker is transport-only; does not store or compute over user content.
- Tool sandboxing: file ops restricted to workspace/; run_code uses subprocess with timeout and blocked path traversal.

## Project Status and Roadmap

- Done:
  - Phase 1: Local single-node, wiki retrieval, single LLM call.
  - Phase 2: P2P-lite (HTTP, 2 nodes, parallel roles, synthesis).
  - Phase 3: OCC Forge + Docker pack + intelligent role routing.
  - Phase 4: WebSocket broker live at broker.opencognitivecommons.org.
- Next:
  - Phase 5: Desktop GUI (Tauri + React).
  - Phase 6: Reputation, source registry, pack integrity (SHA-256 + OCC.org signature), public benchmarks.
  - OCC Hub: public pack catalog (after 5–6 packs).
- Repo: https://github.com/VikFinlay/occ — MIT license.

## Operational Notes

- Classification is domain-agnostic; only distinguishes casual chat from knowledge-grounded tasks.
- Retrieval trigger is conservative: do not engage packs unless clearly needed (prefer CHAT on ambiguity).
- Synthesis modes:
  - Additive: combine disjoint domain expertise.
  - Adversarial: resolve disagreements when multiple experts cover the same domain; keep strongest arguments and evidence.
- All models support a “thinking mode” toggle to balance speed vs reasoning depth per call.

## Key Points

- OCC Node routes queries between CHAT and DELIBERATE, with manual “!” override, and conducts local and distributed deliberation with additive/adversarial synthesis.
- Knowledge is curated into expert packs (LLM Wiki), retrieved via keyword search with a ≥300-char relevance threshold; no automatic web crawling (anti-GEO).
- Networking uses a federable WebSocket broker: outbound-only connections, manifest-based domain routing, local inference and synthesis.
- Runs Qwen models via Ollama across VRAM-based tiers (262K context, vision, thinking mode), auto-selecting and keeping models resident in VRAM.
- Provides agent tools (web search, fetch, sandboxed file I/O, run_code), conversational memory with /clear, and a transparent context usage indicator.