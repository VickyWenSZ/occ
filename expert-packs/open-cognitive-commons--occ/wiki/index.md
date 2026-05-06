# Wiki Index

Last updated: 2026-05-06  
Total pages: 12

## Pages

| File | Title | Summary |
|------|-------|---------|
| concepts/expert-pack-llm-wiki.md | Expert Pack — LLM Wiki Pattern | A self-contained knowledge pack for a domain that uses an LLM to build and maintain a structured wiki (concept pages, index, log, schema) enabling accumulated, queryable knowledge instead of raw RAG chunking. |
| concepts/expert-pack-structure-and-manifest.md | Expert Pack File Structure and Manifest | A standard expert-pack layout containing a wiki (concept pages, index, log, schema) and a manifest.yaml that lists name, version, domains, sources (with hashes/dates) and a signature for Hub distribution. |
| concepts/ingestion-pipeline.md | Ingestion Pipeline | The stepwise process in Forge where an LLM extracts concept slugs/titles/summaries, updates or creates wiki pages, appends logs, and updates the pack index and manifest for each source. |
| concepts/manifest-based-routing.md | Level 1 Routing — Manifest-Based Role Assignment | A peer discovery and role-assignment mechanism where nodes expose a manifest of domains and the deliberation engine fetches peer manifests to select experts, contrarians, and synthesizers based on domain overlap. |
| concepts/occ-forge.md | OCC Forge (Knowledge Preparation) | A Gradio-based toolchain and pipeline for ingesting URLs/files, extracting concepts via GPT-5, generating or updating wiki pages, and producing Hub-ready manifests for expert packs. |
| concepts/occ-node-deliberation-engine.md | OCC Node — Deliberation Engine | The local runtime Python package that runs an Ollama LLM, handles pack retrieval and retrieval-based queries, classifies queries as chat vs deliberate, orchestrates distributed deliberation, and provides CLI and tool integrations. |
| concepts/open-cognitive-commons-occ.md | Open Cognitive Commons (OCC) | A distributed Mixture-of-Experts style AI system that enables users to run small local LLMs (expert packs) which collaborate over a network to provide high-quality, community-curated AI services with a simple chat UX. |
| concepts/retrieval-and-conversational-memory.md | Retrieval and Conversational Memory | Local retrieval uses keyword search over pack markdown with multilingual stopwords and a 300-character relevance threshold, while session history stores up to 1000 messages and provides context usage indicators. |
| concepts/three-mode-routing.md | Three-Mode Routing (local / delegate / hybrid) | A runtime routing strategy that chooses between local-only answers, delegating queries to peers, or hybrid synthesis based on local pack relevance and peer domain matches. |
| concepts/tier-system-models.md | Tier System for Models | A hardware-aware tiering scheme that maps detected VRAM/CPU capacity to Qwen model variants (Micro to Server tiers) with automatic model selection and VRAM management. |
| concepts/tool-agentic-framework.md | Tool-Agentic Framework | A set of sandboxed, always-available tools (web_search, fetch_url, read_file, write_file, list_files, run_code) that LLMs can call during any request to extend capabilities safely. |
| concepts/websocket-broker-architecture.md | WebSocket Broker Architecture | A brokered, outbound-connection architecture where nodes maintain outbound WebSocket connections to a broker that routes queries to relevant peers, avoiding NAT traversal and central knowledge storage. |
