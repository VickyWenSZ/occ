---
title: Ingestion Pipeline
slug: ingestion-pipeline
source: occ
confidence: high
tags: [occ, forge, expert-pack, llm-wiki, responses-api]
---

# Ingestion Pipeline

The OCC Forge ingestion pipeline turns approved sources into a persistent, cross-referenced “LLM Wiki” contained in expert packs. Unlike classic RAG, knowledge is accumulated, curated, and versioned into dense wiki pages that downstream nodes can query efficiently and deterministically.

## Role in OCC Architecture

- Position: Component 2 (OCC Forge — knowledge preparation). User nodes never crawl; they consume curated expert packs.
- Inputs: Community-approved sources (URLs/files, incl. PDF).
- Outputs: Updated expert pack with:
  - wiki/concepts/*.md (dense wiki pages)
  - wiki/index.md (regenerated each ingest)
  - wiki/log.md (append-only ingest log)
  - wiki/schema.md (conventions)
  - manifest.yaml (Hub-ready metadata: name, version, domains, sources, signature)

Related operations (pattern “LLM Wiki”):
- INGEST (this pipeline): read sources → extract concepts → create/update pages → update index/log/manifest.
- QUERY: read index.md → select relevant pages → synthesize answers with citations.
- LINT: health checks (contradictions, orphans, obsolete claims, missing cross-references).

## LLM Wiki vs Classic RAG (Context)

- Classic RAG: on-demand chunking; no accumulation; rediscovery per query.
- LLM Wiki (OCC):
  - Precompiles sources into structured wiki pages.
  - Accumulates and composes knowledge over time.
  - Maintains cross-references; flags contradictions proactively.
  - Produces stable, LLM-optimized artifacts for later retrieval.

## How to Run

- Launch GUI: python forge/app.py (Gradio in browser).
- Tech stack:
  - Python, Gradio.
  - OpenAI Responses API (POST /v1/responses) — never Chat Completions.
  - load_dotenv(override=True), 3 automatic retries, max_output_tokens: 32000, timeout=None.

Directory (Forge excerpts):
- forge/_llm.py — Responses API client and retry logic.
- forge/_sources.py — file reader, URL fetcher, PDF parser.
- forge/_wiki.py — wiki I/O (create/update pages, index, log).
- forge/_manifest.py — manifest.yaml read/write.

## Pipeline Stages (Per Source)

1) Concept Extraction
- Model: gpt-5-mini via Responses API.
- Task: extract_concepts() → JSON array of {slug, title, summary}.
- Slugs are stable identifiers (deterministic per concept) to allow idempotent updates.

Example response shape:
```json
[
  {"slug": "ingestion-pipeline", "title": "Ingestion Pipeline", "summary": "Forge process to build and update expert packs."},
  {"slug": "expert-pack-structure", "title": "Expert Pack — Structure", "summary": "Layout, manifest, index, log."}
]
```

2) Page Materialization per Concept
- If slug exists:
  - update_wiki_page(): LLM reads the existing page + new source content; enriches without deleting prior validated content.
  - Contradictions are flagged inline in the page body:
    > ⚠️ Conflict: <concise conflicting claim + source attribution>
- If slug is new:
  - write_wiki_page(): create page from scratch (dense, factual, LLM-optimized).

3) Index, Log, Manifest Update
- wiki/index.md: fully regenerated catalog of all pages at every ingest.
- wiki/log.md: append-only entry with timestamp and source metadata (provenance, results).
- manifest.yaml: update name/version/domains; append source entries with url+date+hash; maintain Hub readiness and signature field.

## Data Contracts and Artifacts

- Concept object: {slug, title, summary}
- Wiki pages:
  - Dense technical content.
  - Cross-references to related slugs.
  - Inline conflict flags using blockquote lines prefixed by “⚠️ Conflict:”.
- index.md:
  - Canonical list of all concepts with titles and slugs; regenerated each run.
- log.md (append-only):
  - Timestamp, source, list of created/updated pages, notes (e.g., conflicts).
- manifest.yaml:
```yaml
name: <pack-name>
version: <semver or date-based>
domains:
  - <domain-keyword-1>
  - <domain-keyword-2>
sources:
  - url: <source-url-or-path>
    date: <ISO-8601>
    hash: <sha256-of-source-content>
signature: <pack-signature-or-empty>
```

## Source Handling and Governance

- Anti-GEO principle: no crawling; only approved sources via community governance with public review.
- Input types: URLs, local files, PDFs (parsing in _sources.py).
- Provenance: Each source tracked in manifest.yaml with url+date+hash; each ingest logged in wiki/log.md.

## Update Semantics and Knowledge Accumulation

- Additive updates: New evidence enriches existing pages; nothing is discarded unless explicitly refuted.
- Contradictions: Clearly flagged inline for later LINT resolution and editorial review.
- Deterministic structure: Stable slugs ensure continuity across multiple ingests.
- Accumulation: Over successive ingests, the wiki becomes more comprehensive and internally cross-referenced.

## API Usage Notes (Forge)

- Endpoint: POST /v1/responses (OpenAI Responses API).
- Characteristics:
  - 3 automatic retries on transient failures.
  - max_output_tokens: 32000 to accommodate large page updates.
  - timeout=None (long-running calls allowed in GUI).
  - Uses load_dotenv(override=True) to load environment config at runtime.

Pseudo-call (illustrative):
```python
from forge._llm import responses_api
concepts = responses_api.call(
  model="gpt-5-mini",
  system="Extract OCC wiki concepts as JSON {slug,title,summary}.",
  input=source_text,
  max_output_tokens=32000
)
```

## File Layout within an Expert Pack

- expert-packs/<domain>/
  - wiki/
    - concepts/*.md
    - index.md (regenerated)
    - log.md (append-only ingest log)
    - schema.md (content/layout conventions)
  - manifest.yaml (Hub-ready descriptor)
- Current packs (examples):
  - mcp/ (Model Context Protocol) — 14 pages
  - docker/ — 32+ pages (built with Forge)

## Example Wiki Page Patterns

Conflict annotation inside a page:
```
> ⚠️ Conflict: Source A states "X >= 1.0", but Source B states "X < 1.0" (see manifest entries YYYY-MM-DD).
```

Cross-referencing related concepts:
```
See also: [Expert Pack — Structure](expert-pack-structure.md), [Retrieval](retrieval.md)
```

## Relation to Node-Side Operations

- INGEST runs in Forge (admin/community side).
- Node queries:
  - Use keyword search over local wiki markdown.
  - Consider a pack “relevant” if ≥300 characters are retrieved.
  - Benefit from accumulated structure and conflict flags authored during ingests.

## Reliability and Observability

- log.md provides an immutable audit trail of all ingests with timestamps and sources.
- manifest.yaml tracks verifiable source hashes to detect drift.
- LINT pass (separate operation) can later resolve conflicts, detect orphans, and flag obsolete claims.

## Constraints and Guarantees

- No web crawling; only whitelisted/approved inputs.
- Local determinism: index.md regeneration and manifest updates ensure pack consistency after each ingest.
- GUI-first workflow (Gradio) for transparency and community oversight.

## Minimal Operator Workflow

1. Start Forge: python forge/app.py
2. Add a source (URL/file/PDF) in the GUI.
3. Review extracted concepts (slug, title, summary).
4. Execute ingest:
   - Creates or updates pages.
   - Regenerates index.md.
   - Appends log.md.
   - Updates manifest.yaml (including new source hash).
5. Optionally run LINT to address conflicts and structural issues.

## Key Points

- INGEST compiles approved sources into durable, LLM-optimized wiki pages with provenance and versioning.
- The pipeline is additive: updates enrich existing pages; contradictions are flagged inline for later resolution.
- Artifacts updated every run: wiki/concepts/*.md, wiki/index.md, wiki/log.md (append-only), manifest.yaml.
- Forge uses the OpenAI Responses API (with retries, large outputs, no timeouts) via a Gradio GUI.
- Stable slugs, manifest source hashes, and append-only logs provide reproducibility, auditability, and Hub readiness.