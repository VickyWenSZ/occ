---
title: Multiple Compose files and merging
slug: compose-file-merging
source: compose-application-model
confidence: high
tags: [docker compose, compose file, merging, overrides, include]
---

# Multiple Compose files and merging

Docker Compose represents a multi-container application using one or more YAML files that conform to the Compose Specification. Multiple Compose files can be merged to produce a single application model (project) that the Compose CLI deploys. Merging is deterministic: later files in the order you specify override or append to earlier ones, with rules that depend on the YAML data type.

## Compose file discovery and canonical names

- Default Compose file path in the working directory:
  - Preferred: compose.yaml
  - Also supported: compose.yml
- Backwards-compatibility:
  - docker-compose.yaml and docker-compose.yml are supported.
- If both canonical and legacy names exist, compose.yaml is preferred.

## Project model and scoping (context for merged output)

- The merged files define one project (an individual deployment of the application) with a top-level name attribute.
- The project name groups and isolates platform resources; when creating resources, prefix names by the project and set the label com.docker.compose.project.
- Compose lets you set and override the project name so the same compose.yaml can be deployed multiple times with distinct names.

## What is merged

- Services: the core units of the application, each typically runs one container image with configuration. Services interconnect via networks, persist data with volumes, and consume configs and secrets.
- Top-level resources:
  - networks: define routable connectivity among services.
  - volumes: persistent data stores.
  - configs: non-sensitive runtime/platform configuration injected as files.
  - secrets: sensitive data injected as files.
- Note: Volumes, configs, and secrets can be declared simply at the top level, with platform-specific details added at the service level. The mere presence of networks/volumes/configs/secrets objects (even as empty maps) is sufficient to define them.

## Merge mechanics

When you provide multiple Compose files, Compose produces a single model by applying later files over earlier ones. The combination is implemented by appending or overriding YAML elements based on the file order you set.

- Order matters: Given files [file1, file2, ..., fileN], fileN has the highest precedence.
- Type-based rules:
  - Scalars (simple attributes): overridden by the value from the highest-precedence file.
  - Maps: overridden by the value from the highest-precedence file.
  - Lists: merged by appending list items from later files to earlier ones.
- Normalization before merge:
  - Some Compose elements can be expressed as either single strings or complex objects (for example, certain mount or port definitions). Merges apply to the expanded (normalized) form.
- Path resolution across files:
  - Relative paths are resolved based on the parent folder of the first Compose file in the set, even when complementary files live in other folders.

## Include, fragments, and extensions

- include: You can reuse other Compose files or factor parts of your model into separate files with include. This is useful when your application depends on another application managed by a different team, or when you need to share parts of the model.
- Fragments and extensions: Use YAML fragments and Compose extensions to keep files DRY and maintainable while building the final merged model.

## CLI usage context

- The Docker Compose CLI (docker compose) consumes the merged model to manage the application lifecycle:
  - docker compose up starts services and creates required networks/volumes, injecting configs and secrets.
  - docker compose ps inspects running service state.
  - docker compose logs streams container logs.
  - docker compose down stops and removes resources created for the project.
- The CLI is included with Docker Desktop.

## Example: merge semantics

Given two files provided in order [compose.yaml, extra.yaml], the second file has higher precedence.

compose.yaml:
```yaml
name: example
services:
  frontend:
    image: example/webapp:1.0
    ports:
      - "443:8043"
    volumes:
      - ./conf:/etc/conf
    networks: [front-tier, back-tier]
    configs: [httpd-config]
    secrets: [server-certificate]
  backend:
    image: example/database:1.0
    volumes:
      - db-data:/var/lib/data
    networks: [back-tier]
volumes:
  db-data: {}
configs:
  httpd-config:
    external: true
secrets:
  server-certificate:
    external: true
networks:
  front-tier: {}
  back-tier: {}
```

extra.yaml:
```yaml
# Higher-precedence file
name: example-override   # overrides the project name
services:
  frontend:
    image: example/webapp:2.0  # scalar override
    ports:
      - "8443:8043"            # list append (both port mappings will be present)
    volumes:
      - ./extras/conf:/etc/conf.d  # list append
```

Resulting effective model (highlights):
- Project name: example-override (overrides example).
- services.frontend.image: example/webapp:2.0 (overrides 1.0).
- services.frontend.ports: ["443:8043", "8443:8043"] (list append).
- services.frontend.volumes includes both mounts; the relative path ./extras/conf is resolved relative to the parent folder of the first file (compose.yaml), not extra.yaml.

## Key Points

- Multiple Compose files are merged by order: later files override scalars/maps and append to lists from earlier files.
- Relative paths in all files are resolved against the parent directory of the first Compose file.
- Elements that support both short and long syntax are normalized before merging; rules apply to the expanded form.
- Top-level name defines the project scope; it can be overridden across files to redeploy the same model with different isolation.
- Use include, fragments, and extensions to factor and reuse Compose definitions across teams and projects.