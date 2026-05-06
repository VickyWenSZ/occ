---
title: Tool-Agentic Framework
slug: tool-agentic-framework
source: occ
confidence: high
tags: [occ, agents, tools, sandbox, retrieval]
---

# Tool-Agentic Framework

The Tool-Agentic Framework in OCC (Open Cognitive Commons) is the runtime layer within the OCC Node that equips every LLM call—across modes and roles—with a consistent, sandboxed set of tools for grounded reasoning, execution, and synthesis. It is designed for reliability, privacy, and composability in a distributed deliberation setting.

## Design Goals

- Always-on tools: tools are available to the LLM in all calls (CHAT and DELIBERATE, across answerer/expert/contrarian/synthesizer roles).
- Safety by construction: strict sandboxing, path traversal blocking, short execution timeouts.
- Offline-first, privacy-preserving: local retrieval and inference; no implicit web access; explicit opt-in for web search.
- Deterministic orchestration: tools are stateless or state-scoped to workspace/; side effects are local and auditable.
- Seamless integration with distributed deliberation: works identically in local, delegate, and hybrid routing.

## Tool Inventory (node/deliberation/tools.py)

Available to the LLM in all calls:

- web_search
  - Backend: DuckDuckGo via duckduckgo_search (ddgs)
  - Usage: only when explicitly requested by the model/user; no API keys; avoids background crawling (anti-GEO)
  - Purpose: quick discovery of external resources when needed; complements curated expert packs
- fetch_url
  - Backend: requests + BeautifulSoup4
  - Behavior: fetches an HTTP(S) URL and returns normalized text/HTML fragments; intended for targeted retrieval from trusted pages
- read_file / write_file
  - Scope: filesystem access sandboxed under workspace/
  - Behavior: read/write UTF-8 files; path traversal is blocked; cannot escape workspace/
  - Use cases: scratchpads, intermediate artifacts, cached results, simple datasets
- list_files
  - Scope: lists files under workspace/ (recursively or top-level depending on implementation)
  - Use cases: inspection, reproducibility of multi-step tool plans
- run_code
  - Backend: Python executed in a subprocess
  - Working directory: workspace/
  - Timeout: 30 seconds hard limit
  - Security: path traversal blocked; no network by default unless explicitly allowed by the environment; inherits sanitized env
  - Use cases: lightweight computation, parsing, small simulations, data wrangling on artifacts in workspace/

Notes:
- The toolset is intentionally minimal, auditable, and general-purpose.
- All side effects are confined to workspace/ (gitignored; user-controlled; easy to purge).

## Execution Model and Lifecycle

1) Mode selection (semantic classifier)
- A tiny LLM classifier decides 0 (CHAT) vs 1 (DELIBERATE).
- Rules:
  - 0 CHAT: general conversation; no wiki retrieval; conversational system prompt
  - 1 DELIBERATE: document-grounded answer; wiki retrieval; technical system prompt
  - Prefix override: user may force DELIBERATE with ! at query start
- Classifier config: binary output 0/1, num_predict=3, temperature=0, fast

2) Retrieval (DELIBERATE only)
- Keyword search over local expert pack wiki/*.md with IT+EN stop-word filtering
- Relevance threshold: at least 300 characters of retrieved content to mark a pack “relevant”
- Retrieved passages provided as context to tool-capable roles

3) Distributed routing (with peers connected)
- local: only local pack used when relevant; no delegation
- delegate: no relevant local pack; forward to peers with matching domains (via broker); OCC Node synthesizes
- hybrid: both local and peers relevant; local answer + peer answers → synthesis
- Role assignment via manifests:
  - 1 relevant peer → expert
  - 2 peers, different domains → both experts; additive synthesis
  - 2 peers, same domains → expert + contrarian; adversarial synthesis

4) Tool-agentic planning and execution
- In every role, the LLM may call tools opportunistically (e.g., fetch_url to inspect a cited page; run_code to reconcile numbers; read_file/write_file for scratchpads)
- web_search is only used upon explicit model/user intent
- All tool outputs feed back into the role’s working context for final answering/synthesis

5) Memory and observability
- Conversational memory: self._history up to ~1000 messages; passed to each LLM call (models have 262K context)
- Context usage indicator after each reply (visual meter)
- Deliberation logs: append-only deliberation_log.md for auditability of distributed synthesis

## Security and Sandboxing

- Filesystem
  - read_file/write_file/list_files constrained to workspace/
  - Path traversal blocked (no .. escapes)
- Code execution
  - run_code executed as a subprocess
  - cwd=workspace/, 30s timeout, no external state access beyond workspace/
- Network
  - web_search and fetch_url are explicit, auditable actions; no background crawling
  - Aligns with anti-GEO: tools only access approved/explicit sources; primary knowledge is curated expert packs
- Broker separation
  - The WebSocket broker routes queries/responses between nodes; it is not used for tool execution or data centralization
  - Knowledge, retrieval, tool runs, and inference remain local on each node

## Integration with OCC Stack

- LLM runtime: Ollama with Qwen family (3.5/3.6) across tiers; 262K context; vision-capable; thinking mode togglable via think=False/True
- Keep-alive: models kept in VRAM during session (keep_alive=-1)
- Node server: FastAPI + Uvicorn; async client via httpx + websockets
- Files and modules
  - node/deliberation/tools.py: tool implementations
  - node/deliberation/engine.py: orchestration (local + distributed + role routing)
  - node/deliberation/roles.py: answerer, expert, contrarian, synthesizer roles
  - node/retrieval/search.py: keyword retrieval over wiki markdown
  - workspace/: sandboxed area for tool state and artifacts

## Example Tool Call Patterns

Tool calls are structured, explicit, and return machine-parseable results suitable for further reasoning.

- web_search (explicitly requested)
```
{
  "tool": "web_search",
  "args": { "query": "Docker Compose healthcheck syntax" }
}
```

- fetch_url (targeted extraction)
```
{
  "tool": "fetch_url",
  "args": { "url": "https://docs.docker.com/compose/compose-file/05-services/" }
}
```

- read/write workflow in workspace/
```
{ "tool": "write_file", "args": { "path": "workspace/notes.md", "content": "# Findings\n..." } }
{ "tool": "read_file",  "args": { "path": "workspace/notes.md" } }
{ "tool": "list_files", "args": { "path": "workspace/" } }
```

- run_code with timeout and local files
```
{
  "tool": "run_code",
  "args": {
    "language": "python",
    "code": "import json,glob\nprint(json.dumps(sorted(glob.glob('*.md'))))"
  }
}
```

All paths are interpreted relative to workspace/; attempts to access outside are rejected.

## Operational Characteristics

- Availability: Tools are injected into every role call—no separate “tool use” phase required
- Latency considerations:
  - run_code capped at 30s; web_search/fetch_url add network latency only on explicit use
  - Distributed modes add broker round-trip, but tool runs remain local to each participating node
- Failure handling:
  - Tool errors are surfaced to the LLM for recovery (e.g., retry with corrected arguments, or fall back to pack knowledge)
- Reproducibility:
  - Intermediate artifacts kept in workspace/ and discoverable via list_files
  - deliberation_log.md records role outcomes and synthesis steps

## Extensibility

- Adding tools: implement in node/deliberation/tools.py with:
  - Clear input schema (validated), explicit return schema (JSON/strings)
  - Deterministic behavior, no hidden network calls
  - Workspace-scoped side effects only
- Domain-specific tools: recommended to remain small and auditable; prefer enriching expert packs over complex toolchains
- Federation: identical tool semantics across nodes enable reliable multi-node synthesis without central coordination

## Interplay with Knowledge Curation

- Primary grounding: curated expert packs (LLM Wiki pattern) with accumulated, cross-referenced knowledge
- Tools serve to:
  - Inspect and verify specifics (fetch_url for canonical docs)
  - Compute and reconcile numeric or structural details (run_code)
  - Maintain local artifacts that inform iterative reasoning (read/write/list)
  - Only expand beyond curated sources when explicitly needed (web_search)

## Limitations and Constraints

- Execution budget: 30s limit for run_code; unsuitable for long-running tasks
- No arbitrary filesystem access; all state is confined to workspace/
- No implicit web access; web_search is opt-in to avoid data pollution and preserve privacy
- Retrieval threshold (≥300 chars) governs when local packs are considered relevant in DELIBERATE mode

## Key Points

- Tools are always available to all LLM roles and modes, with strict sandboxing and explicit network access.
- Side effects are confined to workspace/, path traversal is blocked, and run_code is limited to 30 seconds.
- The framework complements curated expert packs: local retrieval first; web access only on explicit request (anti-GEO).
- Tool semantics are uniform across local, delegate, and hybrid routing; all execution remains on participating nodes.
- Implementations live in node/deliberation/tools.py and integrate with OCC’s deliberation engine, roles, and retrieval stack.