# Open Cognitive Commons

> What if small AI models, running on ordinary hardware, could think together?

OCC is a distributed AI system where each participant runs a small local language model specialized with an **expert pack** — a curated knowledge base on a specific domain. When you ask a question, your node consults peers across the network. Each peer retrieves from its own knowledge, reasons with its own model, and sends back a perspective. Your node synthesizes the answers.

The result is a response that no single small model could produce alone.

No cloud inference. No data sent to third parties. The knowledge stays local. The thinking stays local. Only the conversation between nodes travels through the network — through a lightweight broker that knows nothing about what it carries.

---

## How it works

```
You ask a question
    └── your node checks its expert packs
    └── your node asks the broker: "who knows about this?"
    └── broker routes the question to relevant peers
    └── each peer retrieves from its knowledge base, runs its LLM
    └── your node receives their answers
    └── your node synthesizes a final response
```

Three routing modes happen automatically:

- **Local** — your packs cover the question, no peers needed
- **Delegate** — peers know more than you, you synthesize their answers
- **Hybrid** — you and peers both know something, all perspectives combined

---

## Getting started

**Requirements:** Python 3.11+, [Ollama](https://ollama.com) installed and running.

```bash
git clone https://github.com/VikFinlay/occ.git
cd occ
pip install -r node/requirements.txt
python node/apps/cli/main.py
```

On first run, OCC detects your hardware and selects the right model automatically. If the model isn't installed, it offers to download it.

Once running, your node connects to the network broker and becomes part of the collective. You can ask anything — questions within your expert packs get answered locally, questions that match other nodes get routed automatically.

---

## Expert packs

Expert packs are the knowledge units of OCC. Each pack is a collection of dense, factual wiki pages on a specific domain, optimized for LLM retrieval.

```
expert-packs/
  mcp/        ← Model Context Protocol
  docker/     ← Docker & container ecosystem
  general/    ← OCC itself, deliberation concepts
```

Packs are plain markdown. You can read them, edit them, add to them. To build new packs from web sources and documents, use **OCC Forge** (`python forge/app.py`).

---

## Network

Nodes connect through a lightweight WebSocket broker at `broker.opencognitivecommons.org`. The broker:

- Knows which nodes are online and what domains they cover
- Routes questions to relevant nodes
- Collects and returns answers
- Knows nothing about the content of messages

The broker is open source and federatable. Anyone can run a compatible broker. Nodes point to whichever broker they trust via `OCC_BROKER_URL`.

---

## Project structure

```
occ/
  node/               ← OCC Node (what you run)
    apps/cli/         ← chat interface
    deliberation/     ← engine, classifier, roles, tools
    expert_runtime/   ← pack loading and retrieval
    server/           ← broker agent, HTTP client (legacy)
  forge/              ← OCC Forge (knowledge builder, uses GPT-4o/5)
  expert-packs/       ← knowledge bases
```

---

## Status

OCC is early and experimental. The core loop works: local retrieval, distributed deliberation, synthesis. The network layer is functional. Expert packs are small but real.

What's missing: more packs, a desktop GUI, pack signing, a public pack catalog. These are next.

---

## Philosophy

The premise of OCC is that intelligence is not a property of model size. It is a property of knowledge, reasoning, and — when models work together — deliberation.

A 9B model that knows everything about Docker, talking to a 9B model that knows everything about Kubernetes, produces something neither could produce alone. Scale that to hundreds of domains and thousands of nodes, and the collective becomes something new.

OCC is an experiment in what that could look like.

---

## License

MIT — see [LICENSE](LICENSE).
