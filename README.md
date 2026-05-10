# Open Cognitive Commons

> Free, trustworthy AI for everyone. Forever.

OCC is a distributed AI system where small language models — running on ordinary hardware, owned by ordinary people — reason together to produce answers no single model could reach alone.

Every node accesses the same **verified, community-curated knowledge**: expert packs built from approved sources, version-controlled, and served from the OCC broker. The network is not a collection of specialists each guarding their own domain. It is a collective of reasoners, all working from the same trusted foundation, each contributing the cognitive role its hardware is best suited for.

No cloud inference. No subscription. No data harvesting. The knowledge is shared and verified. The reasoning is local and private. The network makes you smarter than your hardware alone.

> Full documentation: **[opencognitivecommons.org/docs](https://opencognitivecommons.org/docs)**

---

## How it works

When you ask a knowledge question, your Node runs a three-stage deliberation:

```
1. RETRIEVE
   The Node sends focused sub-queries to the broker's search index
   → fetches the most relevant pages from approved expert packs
   The broker sees keywords; it never sees your original question.

2. REASON
   Your local model writes an Expert draft using the retrieved knowledge.
   A separate Critic agent reviews that draft against the same sources,
   flagging unsupported or contradicted claims (with a verbatim verification tool).
   When a peer with stronger hardware is online, the Critic runs there
   over an end-to-end encrypted exchange — the broker routes ciphertext only.

3. SYNTHESIZE
   Your Node integrates the Expert draft and the Critic's review
   → produces a final answer, streamed to you.
```

Routing happens automatically based on the question and the available peers:

- **Chat** — conversational message, no retrieval.
- **Local** — full deliberation against server packs, no suitable peer available.
- **Distributed** — full deliberation, with a peer Critic on stronger hardware.
- **Local private** — full deliberation against your own private packs only (local mode on).

The stronger the peer's hardware, the harder the cognitive task it receives. A 27B model reviews what a 9B model wrote. A 9B model reviews what a 4B model wrote. The network self-organizes by capability.

---

## Components

OCC is split into four cooperating parts. Each is small, well-defined, and does one thing.

### Node

The runtime that lives on your machine. Loads a local Qwen model, retrieves verified knowledge from the broker, runs the multi-agent deliberation, and exposes everything through a chat-style web UI at `http://localhost:7891`. Includes Forge as a tab. Adapts to your hardware through a tier system that scales context length and model size automatically. Connects to the broker as a peer, lending its GPU as a Critic for other Nodes when idle.

→ [Node documentation](https://opencognitivecommons.org/docs/node)

### Forge

The pack-building tool, on the same Node. Takes curated sources — URLs, files, pasted text — and produces a structured expert pack: extracted concepts, dense factual pages, cross-links, immutable raw sources. Three modes (`Add sources` / `Recompile from raw` / `Rebuild from scratch`) and a quality lint pass. Forge does not invent knowledge — it only synthesizes what you give it. Private packs stay on your machine; public packs can be submitted to the registry for community review.

→ [Forge documentation](https://opencognitivecommons.org/docs/forge)

### Expert packs

The unit of knowledge in OCC. Each pack covers one domain and follows a structured format adapted from Andrej Karpathy's LLM-wiki pattern: an index, a set of dense factual pages, cross-links between concepts, and an immutable record of original sources. Packs are normal markdown files in normal folders — version-controlled, reviewable, signable.

→ [Anatomy of a pack](https://opencognitivecommons.org/docs/packs)

### Broker

A lightweight FastAPI service running on shared infrastructure. Hosts the published packs, runs a SQLite FTS5 search index over them at `/search`, and routes encrypted peer-Critic exchanges between Nodes. The broker is *not* the source of authority — packs are. Anyone can host a replacement.

→ [Broker documentation](https://opencognitivecommons.org/docs/broker)

---

## Getting started

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads) — on Windows, check *Add Python to PATH* during installation
- [Git](https://git-scm.com/downloads) — all defaults are fine
- **Ollama** — the setup script checks for it and prompts you if missing

### Installation

```bash
git clone https://github.com/VikFinlay/occ.git
cd occ
```

**Windows**
```
start.bat
```

**macOS / Linux**
```bash
bash start.sh
```

The script walks you through setup step by step — verifies prerequisites, installs dependencies, detects your hardware tier, downloads the appropriate Qwen model, and creates an **OCC Node shortcut on your desktop**. Subsequent launches need only a double-click.

### Hardware tiers

On first run, OCC detects your VRAM and picks the right Qwen variant:

| Tier      | VRAM      | Model              | Quant   | Approx size |
|-----------|-----------|--------------------|---------|-------------|
| Micro     | CPU only  | qwen3.5:2b         | Q4_K_M  | ~1.5 GB     |
| Small     | 4 GB      | qwen3.5:4b         | Q4_K_M  | 3.4 GB      |
| Mid       | 8 GB      | qwen3.5:9b         | Q4_K_M  | 5.97 GB     |
| Large     | 16 GB     | qwen3.5:9b         | Q8_0    | 9.53 GB     |
| XL        | 24 GB     | qwen3.5:9b         | BF16    | 19 GB       |
| Server S  | 32 GB     | qwen3.6:27b        | Q4_K_M  | 16.8 GB     |
| Server L  | 80 GB     | qwen3.6:27b        | BF16    | 56 GB       |

All tiers run the same code paths. Context length and retrieval budget scale with the tier — see the [docs](https://opencognitivecommons.org/docs/node) for details.

### Daily use

Double-click the **OCC Node** icon on your desktop. The server starts and OCC opens in your browser automatically.

**Manual fallback** — if the shortcut doesn't work:

```bash
python node/apps/gui/server.py
```

Then open `http://localhost:7891`.

### Updating

Inside OCC Node, open **Settings** and click **Update to latest**. OCC pulls the newest version, reinstalls dependencies, and restarts automatically.

Or manually:
```bash
git pull
python -m pip install -r node/requirements.txt
```

Full setup walkthrough: **[opencognitivecommons.org/docs/getting-started](https://opencognitivecommons.org/docs/getting-started)**.

---

## Why OCC

**The knowledge problem.** Most AI systems either centralize inference in the cloud (fast, expensive, private to one company) or leave users alone with a small local model and no knowledge base. OCC takes a third path — shared, verified knowledge that no single actor controls, combined with distributed reasoning that no single node could achieve alone.

**The trust problem.** Any system that lets users contribute knowledge becomes a target for manipulation — including Generative Engine Optimization, where bad actors seed the open web with content specifically to bias AI answers. OCC's answer is a community-governed source registry: packs are built only from publicly approved sources, version-controlled, auditable, and (when signing rolls out) cryptographically signed. Manipulating the network requires getting a malicious source past public review, not just publishing SEO content.

**The hardware problem.** A 2B model and a 70B model are not the same. OCC uses the difference deliberately. The stronger the peer's hardware, the harder the cognitive task it receives. A small model writes a first answer; a larger model finds its flaws. Work routes to where it fits.

**The privacy problem.** OCC's default is local inference: queries do not leave the user's machine. When peer collaboration happens, payloads are encrypted end-to-end — the broker, which routes them, never holds the keys. There is no telemetry, no per-user state, no profile.

The result: free, trustworthy AI that runs on hardware people already own, backed by knowledge a community maintains and verifies, improving as more people join.

---

## Project structure

```
occ/
  node/                 ← OCC Node (what you run)
    apps/
      cli/              ← terminal chat interface
      gui/              ← web GUI (http://localhost:7891) — includes Forge tab
    deliberation/       ← engine, classifier, roles, tools
    expert_runtime/     ← pack loading and retrieval
    server/             ← broker agent, HTTP client, broker code
    crypto.py           ← Curve25519 / AES-GCM peer-encryption
    hardware.py         ← tier detection
    provider.py         ← Ollama / OpenRouter providers
  forge/                ← Forge backend (knowledge synthesis)
  expert-packs/         ← local knowledge bases (gitignored — built or installed by user)
```

The repository ships with the code only. Pack content is built locally with Forge or fetched from the broker — packs do not live in this repository. See [Anatomy of a pack](https://opencognitivecommons.org/docs/packs) for the format.

---

## Status

OCC is early and experimental. The core loop works end to end: classification, retrieval against a broker-side full-text index, multi-pack fan-out, See Also expansion, three-agent deliberation with a verbatim-verification Critic tool, and tier-aware context budgets across the network. The pack catalog is small but growing.

What's next, in order: more packs across more domains, pack signing, a public pack catalog with review workflow, broker federation. See the [roadmap](https://opencognitivecommons.org/docs/roadmap).

---

## Contributing

OCC is open source. Code, packs, governance, and the docs you are reading are all in public repositories with normal pull-request workflows. There is no proprietary core.

- **Code contributions** — open a pull request against this repository. Issues and design discussions happen in GitHub Issues.
- **Pack contributions** — build a pack with Forge, then submit it to the public pack catalog (the `occ-packs` repository) when it's ready.
- **Source registry contributions** — propose a new authoritative source domain via pull request to the `occ-registry` repository. The community reviews and votes.

See [Governance](https://opencognitivecommons.org/docs/governance) for the review process.

---

## License

MIT — see [LICENSE](LICENSE).
