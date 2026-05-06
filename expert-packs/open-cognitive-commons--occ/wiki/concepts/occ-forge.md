---
title: OCC Forge (Knowledge Preparation)
slug: occ-forge
source: occ
confidence: high
tags: [knowledge-preparation, llm-wiki, ingestion, openai-responses, gradio]
---

# OCC Forge (Knowledge Preparation)

OCC Forge is the knowledge-preparation toolchain of Open Cognitive Commons (OCC). It turns curated sources (URLs, files) into dense, factual, cross-referenced wiki pages (“expert packs”) optimized for LLM consumption. Forge implements the Karpathy-inspired LLM Wiki pattern for cumulative, structured knowledge, departing from ad-hoc, per-query RAG.

Forge is a Python application with a Gradio GUI that orchestrates OpenAI’s Responses API to:
- Extract canonical concepts from sources.
- Create or incrementally enrich wiki pages per concept (idempotent updates).
- Maintain provenance (index.md, log.md) and a Hub-ready manifest.yaml.

It is designed for admin/community maintainers; OCC Nodes only consume the produced packs for retrieval and deliberation.

## Role in OCC Architecture

- OCC Node (runtime): Runs local LLMs via Ollama, performs retrieval, distributed deliberation, and user chat. It never performs knowledge crawling.
- OCC Forge (this component): Prepares and maintains the expert packs (LLM Wiki) from approved, reviewed sources. Operated by maintainers.
- OCC Hub (future): Public catalog, source registry, and pack distribution/integrity.

Forge is intentionally separated from runtime inference. It ensures all knowledge is:
- Curated (Anti-GEO principle: no uncontrolled web crawling).
- Structured (concept-centric wiki).
- Accumulative (updates refine existing pages and track contradictions).

## Why LLM Wiki vs Classic RAG

- Classic RAG: extracts chunks on every query; no lasting structure or accumulation.
- LLM Wiki (OCC):
  - One-time ingest transforms sources into stable, reusable wiki pages.
  - Knowledge compounds over time with cross-refs and contradiction flags.
  - Querying becomes lightweight retrieval over well-structured, curated pages.

## Running Forge

- Entry point: python forge/app.py
- Launches a Gradio GUI in the browser for:
  - Adding sources (URL/files).
  - Running ingestion.
  - Inspecting diffs, logs, and manifest updates.

Repository layout (subset):
```
OCC/
  forge/
    app.py                 # Gradio GUI and orchestration
    _llm.py                # OpenAI Responses API client wrapper
    _sources.py            # Source fetchers: URL reader, file loader, PDF parser
    _wiki.py               # Wiki file I/O (create/update pages, index, log)
    _manifest.py           # manifest.yaml read/update/validate
    OPENAI_RESPONSES_API_GUIDE.md
  expert-packs/
    <domain>/
      wiki/
        concepts/*.md
        index.md
        log.md
        schema.md
      manifest.yaml
```

## Expert Pack Structure

Expert packs live under expert-packs/<domain>/ with:
- wiki/concepts/*.md — Concept-centric pages, dense, factual, LLM-optimized.
- wiki/index.md — Catalog of pages (regenerated every ingest).
- wiki/log.md — Append-only lineage: timestamped ingests with sources.
- wiki/schema.md — Style and structural conventions for the pack.
- manifest.yaml — Hub-ready metadata:
  - name, version, domains
  - sources: url/file, date, content hash (e.g., SHA-256)
  - signature (for integrity; to be used by OCC Hub)

Example manifest.yaml:
```yaml
name: docker
version: 0.5.3
domains:
  - containers
  - docker
  - compose
sources:
  - url: https://docs.docker.com/engine/
    date: 2026-04-28
    sha256: "e3b0c44298fc1c149afbf4c8996..."
  - file: ./ingest/docker_networking_guide.pdf
    date: 2026-04-28
    sha256: "0f343b0931126a20f133d67c2b..."
signature: null  # to be signed by OCC Hub in future phases
```

## Ingestion Pipeline

Triggered via the GUI for each source (URL or file):

1) Concept extraction
- Model: gpt-5-mini (via OpenAI Responses API).
- Function: extract_concepts()
- Output: JSON array of {slug, title, summary}.
- Slugs uniquely identify concepts; summaries drive page scaffolding and dedup.

Example output:
```json
[
  {
    "slug": "docker-network-driver-bridge",
    "title": "Docker Network Driver: bridge",
    "summary": "The default single-host network driver providing NAT and intra-host container connectivity..."
  },
  {
    "slug": "compose-services-and-dependencies",
    "title": "Compose: Services and Dependencies",
    "summary": "Service definitions, dependency graphs, healthchecks, and startup ordering semantics..."
  }
]
```

2) Page upsert per concept
- If concepts/<slug>.md exists:
  - update_wiki_page(): The LLM reads the current page and the new source, then enriches the page without losing prior content.
  - It flags contradictions or discrepancies inlined in the page using:
    > ⚠️ Conflict: <brief, source-anchored statement of the discrepancy>
- If not exists:
  - write_wiki_page(): Creates a new dense page, using the pack’s schema conventions.

3) Index, log, manifest maintenance
- wiki/index.md: Regenerated to list all concept pages, with short descriptors.
- wiki/log.md: Appends a new entry with:
  - timestamp (UTC ISO-8601)
  - source (URL or file path)
  - concepts updated/created (slugs)
  - source content hash
- manifest.yaml: Adds/updates the source entry (url/file + date + hash); bumps version if configured.

Operational settings:
- OpenAI interface: Responses API (POST /v1/responses), never Chat Completions.
- max_output_tokens: 32000 (large-page updates in a single pass).
- Retries: 3 automatic (transient errors).
- Timeout: None (let long updates complete).
- Environment: dotenv with load_dotenv(override=True).

## Source Types and Parsers

- URLs (HTML): fetched with requests; parsed by BeautifulSoup4; main content heuristics applied.
- Files:
  - Markdown/MD and text.
  - PDF: parsed by the embedded PDF handler in _sources.py.
- All inputs are normalized to a clean text representation before passing to LLMs.
- Every ingested artifact is hashed (e.g., SHA-256) for manifest/log provenance.

## Page Authoring Conventions (schema.md)

Pages are optimized for LLM consumption:
- Dense, factual, unambiguous prose; minimal fluff.
- Stable headings (## sections), explicit definitions, lists for enumerations.
- Code/config samples where appropriate.
- Clear cross-references to related concepts by slug/title.
- Provenance cues and contradiction flags inline:
  - > ⚠️ Conflict: <short description>
- No private credentials or non-public tokens in content.
- Deterministic anchors: use kebab-case slugs, consistent terminology.

Example skeleton for concepts/<slug>.md:
```markdown
---
title: Docker Network Driver: bridge
slug: docker-network-driver-bridge
source: docker
confidence: high
tags: [docker, networking, bridge]
---

## Summary
Concise, canonical description...

## Capabilities
- NAT, port-mapping, intra-host connectivity...

## Configuration
- Default subnet/cidr...
- iptables interactions...
- Example:
  ```
  docker network create --driver bridge mynet
  ```

## Interactions and Limits
- Service discovery with embedded DNS...
- Performance notes...

## Cross-References
- docker-network-driver-overlay
- docker-port-mapping

## Notes
> ⚠️ Conflict: Some sources state X about default MTU; docs as of 2026-04 indicate Y.
```

## OpenAI Responses API Integration

Forge accesses OpenAI exclusively via the Responses API for long-context, structured outputs.

Python client pattern (see forge/_llm.py):
```python
from os import getenv
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)
client = OpenAI()

def llm_call(prompt, model="gpt-5-mini", max_output_tokens=32000):
    # Implement retries and error handling externally
    resp = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=max_output_tokens,
    )
    return resp.output_text  # or parse JSON with resp.output if using tool-calling
```

Guidelines:
- Keep messages compact and instruction-focused.
- Prefer JSON outputs for concept extraction; validate/repair JSON before use.
- Batch concepts to amortize API latency while keeping deterministic upserts.

## Provenance, Integrity, and Logging

- wiki/log.md is append-only to preserve ingestion history.
- Each log entry includes source identifier, timestamp, and content hash.
- manifest.yaml tracks all contributing sources for the pack’s current state.
- Future OCC Hub will:
  - Sign manifests (cryptographic signatures).
  - Provide a community registry of approved sources.
  - Verify pack integrity and support public catalog distribution.

## Anti-GEO and Curation Workflow

- No unsupervised web crawling. Maintainers explicitly submit approved sources.
- Public review of sources and pack diffs before publishing.
- Contradictions are flagged rather than silently resolved; maintainers adjudicate if needed.

## Interop with OCC Node

- Node retrieval operates over wiki markdown produced by Forge.
- Node’s DELIBERATE mode (for knowledge-backed queries) pulls relevant pages via keyword search and length thresholds.
- Forge ensures pages are:
  - Self-contained.
  - Cross-referenced.
  - Long-context friendly (so Node can synthesize answers with minimal additional calls).

## Current Packs Built with Forge

- docker/ — 32+ pages covering Docker Engine, Compose, networking, storage, and operations.
- mcp/ — 14 pages documenting the Model Context Protocol.

## Roadmap

- Extract Forge into a separate repository for independent versioning.
- Expand LINT capabilities:
  - Orphan page detection.
  - Stale claim detection vs. latest source hashes.
  - Required cross-references and schema compliance checks.
- Integrate with OCC Hub:
  - Source registry.
  - Manifest signing and public benchmarks.
- Advanced diffs and PR-style review inside the GUI.

## Security and Operational Notes

- Never store or commit private credentials/tokens in packs or logs.
- Use environment variables (.env) for API configuration; do not hardcode secrets.
- All knowledge remains local to maintainers during preparation; only pack artifacts (markdown + manifest) are published.
- Deterministic slugs and explicit provenance minimize ambiguity and ease distributed auditing.

## Example End-to-End Flow

1) Add source (URL or file) in the GUI.
2) Run INGEST:
   - Concepts extracted → new/updated pages written.
   - index.md regenerated; log.md appended; manifest.yaml updated with hash.
3) Review diffs:
   - Check for > ⚠️ Conflict markers.
   - Validate cross-references and structure.
4) Publish pack (commit/push).
5) OCC Nodes pull updated packs and benefit from accumulated knowledge during DELIBERATE queries.

## Key Points

- Forge converts curated sources into stable, accumulative LLM Wiki packs (not ad-hoc RAG chunks).
- Pipeline: extract concepts → upsert pages (with contradiction flags) → refresh index/log → update manifest.
- Implementation: Python + Gradio, OpenAI Responses API (max_output_tokens 32k, 3 retries, dotenv override).
- Outputs are Hub-ready: manifest.yaml with sources, dates, hashes; append-only logs; schema-enforced pages.
- Anti-GEO: no crawling; only approved, reviewed sources to protect against manipulation and ensure integrity.