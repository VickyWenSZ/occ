---
title: Expert Pack File Structure and Manifest
slug: expert-pack-structure-and-manifest
source: occ
confidence: high
tags: [replace with 3-5 relevant lowercase keywords]
---

# Expert Pack File Structure and Manifest

This page specifies the on-disk layout and manifest contract for Open Cognitive Commons (OCC) Expert Packs. It defines the wiki-first knowledge structure, required/optional files, manifest fields, update semantics during ingestion, and how nodes and brokers use the manifest for routing and governance.

## Purpose and Scope

- Expert Pack: a self-contained, LLM-optimized “wiki” of dense, factual pages for a coherent domain (e.g., docker/, mcp/), plus a machine-readable manifest used by OCC Forge, OCC Node, and the future OCC Hub.
- Design goals:
  - LLM Wiki pattern: persistent, structured, cross-referenced knowledge that accumulates across ingests (vs. ad-hoc chunking).
  - Deterministic file layout and append-only provenance records for auditability.
  - Hub-ready manifest for distribution, peer routing, and future integrity verification.

## Directory Layout

Each pack lives under expert-packs/<domain>/ and contains a wiki/ directory and a manifest.yaml.

```
expert-packs/
  <domain>/
    wiki/
      concepts/
        <slug-1>.md
        <slug-2>.md
        ...
      index.md         # regenerated at every ingest (catalog)
      log.md           # append-only ingest log (timestamp, source)
      schema.md        # pack conventions and style guide
    manifest.yaml      # Hub/Node-facing metadata (name, version, domains, sources, signature)
```

- <domain>: canonical directory name for the pack’s principal domain (e.g., docker, mcp).
- wiki/concepts/*.md: dense, factual pages optimized for LLM consumption; one concept per file.
- wiki/index.md: inventory of all concept pages; Forge regenerates it on each ingest.
- wiki/log.md: append-only; every ingest appends a timestamped record with the source(s) used.
- wiki/schema.md: human-readable conventions for slugs, linking, page structure, and conflict notation used by the pack.
- manifest.yaml: machine-readable metadata used by Forge, Nodes, and the Hub.

Current examples (as of repo state):
- expert-packs/mcp/ — Model Context Protocol (≈14 wiki pages)
- expert-packs/docker/ — Docker ecosystem (32+ wiki pages; built with Forge)

## Wiki Content Model (LLM Wiki Pattern)

Compared to classic RAG, OCC persists structured knowledge that composes and accumulates over time.

- Page type: concept page
  - Location: wiki/concepts/<slug>.md
  - Content: dense, factual, self-contained, cross-referenced; optimized for LLMs to read directly.
  - Cross-references: standard Markdown links across slugs.
  - Conflict notation: when sources disagree, content is enriched and contradictions are explicitly flagged inline:
    - Example: 
      > ⚠️ Conflict: Source A states X; Source B states Y (date, citation).
- Index:
  - wiki/index.md is a comprehensive, regenerated catalog of all concept pages; drives LLM retrieval planning during Query.
- Provenance log:
  - wiki/log.md is append-only; every ingest appends a line with timestamp and source info (URLs, file paths).
- Schema/conventions:
  - wiki/schema.md documents slug conventions, page templates, linking norms, conflict markers, and any pack-specific rules.

## Manifest: Purpose and Consumers

manifest.yaml is the authoritative metadata for:
- OCC Forge: updates during ingestion (sources, versions, timestamps), managed via forge/_manifest.py.
- OCC Node: advertised domain footprint for routing; nodes expose GET /manifest containing their domains to peers.
- OCC Hub (future): cataloging, distribution, governance (source registry), and integrity verification.
- Role routing: Level 1 routing uses domains from manifests to assign expert/contrarian roles across peers.

## Manifest Schema

Minimal, hub-ready schema (fields and meaning derived from OCC spec):

- name (string): canonical pack name (usually equals <domain> directory).
- version (string): semantic or calendar version of the pack content (maintained by Forge/community).
- domains (array[string]): domain tokens used for peer routing. Tokenization of user queries is matched against these.
- sources (array[object]): provenance entries for the pack build; each entry includes:
  - url (string): canonical source URL (or file URI).
  - date (string): ISO 8601 timestamp of ingestion.
  - hash (string): content hash (e.g., SHA-256) of the source snapshot used at ingestion time.
- signature (string|null): cryptographic signature over the manifest for integrity (planned; becomes mandatory with Hub integrity rollout).

Notes:
- Fields are intentionally compact and auditable. No embeddings or model-specific artifacts are stored here.
- Integrity roadmap: Phase 6 introduces mandatory SHA-256 + OCC.org cryptographic signature; until then signature may be null/omitted.

### Example manifest.yaml

```yaml
name: docker
version: "0.3.0"
domains:
  - docker
sources:
  - url: https://docs.docker.com/get-started/overview/
    date: "2026-04-18T12:34:56Z"
    hash: "a7f5f35426b927411fc9231b56382173...sha256"
  - url: file://local/path/compose_v2_guide.pdf
    date: "2026-04-18T12:35:10Z"
    hash: "b4b147bc522828731f1a016bfa72c073...sha256"
signature: null  # to be set when OCC Hub signing is enabled
```

## Ingestion Lifecycle and File Semantics

Forge (python forge/app.py; Gradio UI) orchestrates ingestion with OpenAI Responses API:

- Pipeline (per source):
  1. extract_concepts() via gpt-5-mini → emits JSON [{slug, title, summary}, ...].
  2. For each concept:
     - If slug exists: update_wiki_page() — merges new facts into existing page, preserves prior content, and flags contradictions using > ⚠️ Conflict: ...
     - If new slug: write_wiki_page() — creates a new concept page.
  3. Update artifacts:
     - Regenerate wiki/index.md
     - Append ingest record to wiki/log.md with timestamp and source
     - Update manifest.yaml (sources list; version as per community policy)

- Forge implementation details:
  - Technologies: Python, Gradio, OpenAI Responses API (POST /v1/responses), load_dotenv(override=True)
  - Retries: 3 automatic
  - max_output_tokens: 32000
  - timeout: None
  - Relevant modules: forge/_wiki.py (file ops), forge/_sources.py (readers, URL and PDF), forge/_manifest.py (manifest management)

- Lint operation (health check):
  - Detects contradictions, orphan pages, obsolete claims, and missing cross-references.
  - Intended to keep wiki coherent and maintainable across iterative ingests.

## Node Consumption and Retrieval

- Retrieval strategy:
  - Keyword search over wiki/*.md with IT+EN stop word filters to reduce false positives.
  - Relevance threshold: pack considered “relevant” if ≥300 characters of matching content are retrieved.

- Classifier & routing:
  - A lightweight classifier LLM routes queries:
    - 0 (CHAT): general conversation → no wiki context.
    - 1 (DELIBERATE): documented knowledge needed → wiki retrieval + technical system prompt.
    - ! prefix: user override to force DELIBERATE.
  - Three-mode routing with peers (uses manifests):
    - local: only local pack is relevant → answer from local wiki.
    - delegate: local pack not relevant; delegate to peers with matching domains.
    - hybrid: local pack relevant + peers relevant → synthesize local and peer answers.

- Manifest in peer discovery:
  - Each node exposes GET /manifest with its domains for Level 1 routing:
    - Query tokens are matched to peer domains.
    - Single relevant peer → expert role.
    - Two peers with different domains → both expert roles; additive synthesis.
    - Two peers with same domains → expert + contrarian; adversarial synthesis to resolve disagreements.

## Governance, Integrity, and Roadmap

- Anti-GEO principle: packs ingest only from community-approved sources (no web crawling for discovery).
- Provenance-first: wiki/log.md + manifest.sources[] provide reproducible audit trails for each ingest.
- Integrity (planned with OCC Hub rollout):
  - Mandatory SHA-256 hashing of all sources.
  - Cryptographic signing of manifest.yaml (OCC.org signature).
- Distribution:
  - OCC Hub will catalog, verify, and distribute packs; nodes declare installed pack domains via their manifest.
- Federation:
  - Brokers route queries; knowledge, retrieval, and inference remain local to nodes.

## Example Pack Tree (docker/)

```
expert-packs/
  docker/
    wiki/
      concepts/
        docker-overview.md
        docker-compose-file-v2.md
        docker-networking-basics.md
        ...
      index.md
      log.md
      schema.md
    manifest.yaml
```

## Authoring Conventions (Recommended)

- Slugs: lowercase, hyphen-separated; stable over time (e.g., docker-networking-basics).
- Page structure:
  - H1: concept title
  - Dense factual body; avoid redundancy; maintain citations and cross-links.
  - Use explicit conflict markers when sources disagree: > ⚠️ Conflict: ...
- Linking: prefer relative links to other concept slugs to aid LLM traversal.
- Updates: augment existing pages rather than rewriting; record all ingests in log.md and manifest.sources[].

## Interactions With OCC Operations

- INGEST: builds/updates wiki pages; regenerates index.md; appends log.md; updates manifest.yaml.
- QUERY: LLM consults index.md to find relevant concepts; synthesizes answers with citations.
- LINT: validates structural health and coherence; identifies candidates for refinement.

## Key Points

- Expert Packs are structured as an LLM-optimized wiki plus a hub-ready manifest under expert-packs/<domain>/.
- manifest.yaml minimally includes name, version, domains, sources[{url,date,hash}], and a signature field for future integrity.
- Forge handles ingestion: concept extraction, page updates with conflict flags, index regeneration, log append, and manifest updates.
- Nodes expose their domains via GET /manifest for manifest-based peer routing and role assignment.
- Provenance (log.md + manifest.sources) and planned signing ensure auditability and integrity across the OCC network.