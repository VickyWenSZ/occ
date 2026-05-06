---
title: Fragments, includes, and extensions
slug: compose-fragments-and-extensions
source: compose-application-model
confidence: high
tags: [docker compose, yaml, reuse, include, configuration]
---

# Fragments, includes, and extensions

This page explains how Docker Compose supports configuration reuse and composition through fragments, includes, and multi-file merges, as defined by the Compose Specification and implemented by Docker Compose.

Compose applications are described in a YAML configuration file (preferred name: compose.yaml; also supports compose.yml, and legacy docker-compose.yaml/docker-compose.yml). You define services and their relationships (networks, volumes, configs, secrets), then manage lifecycle with the docker compose CLI.

Compose provides mechanisms to:
- Keep a single Compose file efficient and maintainable (fragments and extensions).
- Build a full application model from multiple files (merging).
- Reuse other Compose files maintained elsewhere (include).

## File names and precedence

- Preferred canonical file: compose.yaml (preferred over compose.yml).
- Backwards-compatible names supported: docker-compose.yaml, docker-compose.yml.
- If compose.yaml and docker-compose.yaml both exist, compose.yaml is preferred.

## Fragments (in-file reuse)

Fragments are reusable pieces of configuration within a single Compose file that help eliminate duplication and centralize common settings. They are a structural pattern supported by the Compose Specification through YAML’s ability to factor and reuse content and through Compose’s tolerance for maintainability constructs. Use fragments to:
- Centralize shared options across services (for example, common environment, labels, or resource limits).
- Keep service definitions short by factoring shared blocks into a single place.
- Apply consistent configuration without repeating it verbatim.

Notes:
- Fragments affect only authoring and maintainability; the resulting application model is the expanded, concrete configuration applied to services and resources.
- When later combining files, merges operate on this expanded form (see “Merging semantics” below).

## Extensions (maintainability fields)

Extensions are configuration constructs used to keep Compose files organized, DRY, and tool-friendly. They enable:
- Storing reusable defaults or patterns without directly defining runtime resources.
- Attaching supplemental or platform-specific configuration that can be applied to services when needed.
- Keeping the top-level application model clear while preserving maintainability information close by.

Notes:
- Extensions are part of authoring patterns intended to improve readability and reuse. They do not, by themselves, create services or other resources. Only the expanded, referenced configuration shapes the final application model.
- Use extensions together with fragments to factor and apply complex shared configurations cleanly.

## Include (cross-file reuse)

Include lets you reuse other Compose files or factor parts of your application into separate files, especially when:
- Your Compose application depends on another application managed by a different team.
- You need to share a common base or component across multiple projects.

Use include to:
- Pull in and compose pre-defined service stacks (for example, a shared database or monitoring stack).
- Keep domain- or team-owned pieces in their own repositories while still building a single combined application model.

Notes:
- Include is distinct from passing multiple files to Compose via the CLI; it is an authoring-time mechanism within the Compose model to reuse external files as part of a single application specification.
- It is particularly useful for dependency scenarios or when distributing reusable Compose components.

## Working with multiple files (merge and override)

You can define the application model by merging multiple Compose files. The combination is implemented by appending or overriding YAML elements based on the file order you set.

Merging semantics:
- Simple attributes and maps: overridden by the highest-order (last) Compose file.
- Lists: merged by appending.
- Path resolution: relative paths are resolved based on the first Compose file’s parent folder, even when complementary files live in other folders.
- Normalization: some elements accept both a simple string and a complex object form; merges apply to the expanded (normalized) form.

Example (non-normative) illustrating override vs append:

File A (base):
```yaml
services:
  web:
    image: example/webapp:1.0
    ports:
      - "443:8043"
    environment:
      MODE: dev
    networks:
      - front-tier
      - back-tier

volumes:
  db-data: {}
networks:
  front-tier: {}
  back-tier: {}
```

File B (override/extend):
```yaml
services:
  web:
    image: example/webapp:2.0    # simple attribute overridden
    environment:
      MODE: prod                 # map key overridden by later file
    ports:
      - "8443:8043"              # list appended (result has two entries)
```

Effective merged model:
- services.web.image = example/webapp:2.0
- services.web.environment.MODE = prod
- services.web.ports = ["443:8043", "8443:8043"] (appended)
- networks/volumes from File A remain unless explicitly overridden

Important:
- Because merges apply to the expanded form, fields provided as short strings (for example, port mappings) are normalized before merge logic is applied.

## Application model context

Within the merged or included Compose model:
- Services implement the compute layer (running one or more instances of a container image with configuration).
- Networks provide connectivity between services.
- Volumes store and share persistent data.
- Configs provide runtime/platform-dependent configuration mounted as files.
- Secrets provide sensitive data mounted as files with security considerations.

Top-level declarations vs service-level details:
- You can declare volumes, configs, and secrets at the top level, then augment with platform-specific information at the service level.

## CLI interaction (resulting model)

Once your final model is produced (after in-file fragments/extensions, includes, and multi-file merges), manage it with the docker compose CLI:
- docker compose up — create and start all defined services and supporting resources.
- docker compose down — stop and remove running services and created resources.
- docker compose logs — stream or inspect container logs.
- docker compose ps — list services and their status.

## Practical guidance

- Prefer a canonical compose.yaml at the root of your project; factor shared blocks as fragments/extensions to reduce duplication.
- Use include to share or depend on Compose stacks maintained by other teams or repositories.
- Use multiple files to separate concerns (for example, base vs environment-specific overrides) and rely on deterministic merge rules:
  - Put overrides later to take precedence for simple attributes and maps.
  - Remember lists append; plan for deduplication where necessary.
- Keep relative resource paths (build contexts, file mounts, etc.) anchored to the first Compose file’s parent directory because path resolution uses that root during merges.
- When mixing shorthand and longform field syntaxes across files, be aware that merges are applied to the normalized, expanded representation of those fields.

## Key Points

- Fragments and extensions keep a single compose.yaml maintainable by factoring reusable configuration; only the expanded result shapes the runtime model.
- Include reuses other Compose files (for dependencies or shared components) and is distinct from CLI-based multi-file merging.
- Multiple Compose files merge deterministically: simple attributes/maps override by last file; lists append; merges apply to the expanded form.
- Relative paths resolve from the first Compose file’s parent folder across all merged files.
- compose.yaml is the preferred canonical filename; if multiple legacy names exist, compose.yaml is preferred.