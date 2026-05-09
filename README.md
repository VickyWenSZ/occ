# Open Cognitive Commons

> Free, trustworthy AI for everyone. Forever.

OCC is a distributed AI system where small language models — running on ordinary hardware, owned by ordinary people — reason together to produce answers that no single model could reach alone.

Every node accesses the same **verified, community-curated knowledge**: expert packs built from approved sources, cryptographically signed, and served from the OCC server. The network is not a collection of specialists each guarding their own domain. It is a collective of reasoners, all working from the same trusted foundation, each contributing the cognitive role their hardware is best suited for.

No cloud inference. No subscription. The knowledge is shared and verified. The reasoning is local and private. The network makes you smarter than your hardware alone.

---

## How it works

When you ask a technical question, your node runs a three-stage deliberation:

```
1. RETRIEVE (private)
   Your node matches your question against a local index
   → fetches the relevant knowledge pages by name from the OCC server
   The server never sees your question — only which pages you requested.

2. REASON (distributed)
   Your node writes an Expert answer using the retrieved knowledge.
   If a peer with stronger hardware is online, it reviews that answer as Critic —
   checking for errors, gaps, and unsupported claims.
   The peer receives the answer and context, encrypted end-to-end.
   The broker routes the message without reading it.

3. SYNTHESIZE (local)
   Your node combines the Expert answer and the Critique
   → produces a final response, streamed to you.
```

Routing happens automatically based on your question and available peers:

- **Chat** — conversational questions answered directly, no retrieval
- **Local** — deliberation using server knowledge, no suitable peer available
- **Distributed** — deliberation with a peer Critic (stronger hardware online)
- **Local private** — deliberation using your own private packs (local mode)

The stronger your peer's hardware, the harder the reasoning task it receives. A 27B model reviews what a 9B model wrote. A 9B model reviews what a 4B model wrote. The network is self-organizing by capability.

---

## Getting started

### 1 — Prerequisites

- [Python 3.11+](https://www.python.org/downloads) — on Windows, check *Add Python to PATH* during installation
- [Git](https://git-scm.com/downloads) — all defaults are fine
- **Ollama** — the setup script checks for it automatically and will prompt you if it is missing

### 2 — Installation

```bash
git clone https://github.com/VikFinlay/occ.git
cd occ
```

Then run the setup script for your platform:

**Windows**
```
start.bat
```

**macOS / Linux**
```bash
bash start.sh
```

The script walks you through setup step by step — checks all requirements, installs dependencies, and launches OCC automatically. At the end, it creates an **OCC Node shortcut on your desktop** so future launches require no terminal at all.

### 3 — First launch

On the first run, OCC detects your available VRAM and downloads the appropriate model automatically. This download only happens once — subsequent launches start in seconds.

| Tier | VRAM | Model | Quant | Size |
|------|------|-------|-------|------|
| Micro | CPU | qwen3.5:2b | Q4_K_M | — |
| Small | 4 GB | qwen3.5:4b | Q4_K_M | 3.4 GB |
| Mid | 8 GB | qwen3.5:9b | Q4_K_M | 5.97 GB |
| Large | 16 GB | qwen3.5:9b | Q8_0 | 9.53 GB |
| XL | 24 GB | qwen3.5:9b | BF16 | 19 GB |
| Server S | 32 GB | qwen3.6:27b | Q4_K_M | 16.8 GB |
| Server L | 80 GB | qwen3.6:27b | BF16 | 56 GB |

All tiers use the Qwen family with 262K context and thinking mode.

### 4 — Launching OCC

Double-click the **OCC Node** icon on your desktop. The server starts and OCC opens in your browser automatically — no terminal needed.

**Manual fallback** — if the shortcut does not work, open a terminal in the OCC folder and run:

```bash
python node/apps/gui/server.py
```

Then open `http://localhost:7891` in your browser.

### 5 — Updating

Inside OCC Node, open **Settings** and click **Update to latest**. OCC pulls the newest version, reinstalls dependencies, and restarts automatically.

**Manual fallback:**

```bash
git pull
```

---

Once running, your node connects to the network broker and becomes part of the collective. You can ask anything — questions within your expert packs get answered locally, questions that match other nodes get routed automatically.

---

## Expert packs

Expert packs are the knowledge units of OCC. Each pack is a structured wiki of dense, factual pages on a specific domain — built by a language model from approved sources, following the [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Packs on the OCC server are:
- Built exclusively from sources approved by the community (the Source Registry)
- Cryptographically signed before distribution
- Identical for every node — no node can poison the network with corrupted local knowledge
- Auditable: every page is traceable to its source URL and ingestion timestamp

To build your own packs from documents, URLs, or free text, use **OCC Forge** — accessible from the sidebar inside OCC Node. Private packs live on your machine and are only used when you enable local mode.

---

## Network

Nodes connect through a lightweight WebSocket broker at `broker.opencognitivecommons.org`. The broker is not a knowledge server — it is a mailman.

It does three things:
- Maintains a registry of online nodes and their hardware tier
- Routes encrypted messages between nodes
- Knows nothing about the content of what it carries

All deliberation payloads are encrypted end-to-end between nodes. The broker sees only opaque blobs and routing metadata. No query, no answer, no retrieved content is ever readable by the broker.

The broker is open source and federatable. Anyone can run a compatible instance. Nodes point to whichever broker they trust via `OCC_BROKER_URL`.

---

## Project structure

```
occ/
  node/               ← OCC Node (what you run)
    apps/
      cli/            ← terminal chat interface
      gui/            ← web GUI (http://localhost:7891) — includes Forge
    deliberation/     ← engine, classifier, roles, tools
    expert_runtime/   ← pack loading and retrieval
    server/           ← broker agent, HTTP client
  forge/              ← OCC Forge backend (knowledge builder, uses GPT-5)
  expert-packs/       ← local knowledge bases
```

---

## Status

OCC is early and experimental. The core loop works: local retrieval, distributed deliberation, synthesis. The network layer is functional. Expert packs are small but real.

What's missing: more packs, pack signing, a public pack catalog. These are next.

---

## Philosophy

The premise of OCC is that intelligence is not a property of model size. It is a property of knowledge, reasoning, and — when models work together — deliberation.

The knowledge problem: most AI systems either centralize inference in the cloud (fast, expensive, private to one company) or leave users alone with a small local model and no knowledge base. OCC takes a third path — shared, verified knowledge that no single actor controls, combined with distributed reasoning that no single node could achieve alone.

The trust problem: any system that lets users contribute knowledge becomes a target for manipulation. OCC's answer is a community-governed Source Registry. Packs are built only from approved sources, signed, and auditable. Adding a bad source requires compromising a public, reviewable process — not just uploading a file.

The hardware problem: a 2B model and a 70B model are not the same. OCC uses the difference deliberately. The stronger the peer's hardware, the harder the cognitive task it receives. A small model writes a first answer. A larger model finds its flaws. The network routes work to where it fits.

The result: free, trustworthy AI that runs on hardware people already own, backed by knowledge that a community maintains and verifies, improving as more people join.

---

## License

MIT — see [LICENSE](LICENSE).
