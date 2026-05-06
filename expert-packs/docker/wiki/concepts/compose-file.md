---
title: Compose file (compose.yaml)
slug: compose-file
source: compose-application-model
confidence: high
tags: [docker, compose, yaml, containers, orchestration]
---

# Compose file (compose.yaml)

A Compose file (compose.yaml) is a YAML configuration that declares a multi-container application’s services, networks, volumes, configs, and secrets according to the Compose Specification. The Compose CLI (docker compose …) consumes this file to create, start, and manage all declared resources as an isolated project.

## Application model (per the Compose Specification)

- Services
  - Abstract definition of computing units. Implemented by running one or more containers from the same image with shared configuration.
  - Services can reference:
    - Networks for inter-service communication.
    - Volumes for persistent data.
    - Configs for runtime/platform-provided configuration (mounted as files).
    - Secrets for sensitive data (mounted as files, managed via platform-specific secure stores).

- Networks
  - Abstraction for IP routing between containers. Services attached to the same network can communicate.

- Volumes
  - High-level filesystem mounts with global options to persist and/or share data across container runs.

- Configs
  - Runtime or platform-dependent configuration data.
  - Behave like volumes inside containers (mounted as files) but are defined differently at the platform level.

- Secrets
  - Sensitive configuration material (for example, certificates, tokens).
  - Exposed to services as files, backed by platform-secure resources and thus treated distinctly from generic configs.

Note: Volumes, configs, and secrets can be declared simply at the top level and refined with platform-specific details in service-level usage.

## Projects, naming, and isolation

- A project is one deployment of an application specification on a platform.
- The top-level name attribute sets the project name. Compose uses this to:
  - Group and isolate resources from other applications or separate deployments of the same model.
  - Prefix resource names and set the label com.docker.compose.project on created resources.
- Compose lets you override the project name so the same compose.yaml can be deployed multiple times on the same infrastructure with distinct names.

## File names, location, and structure

- Default file: compose.yaml (preferred) or compose.yml in the working directory.
- Backward compatibility: docker-compose.yaml and docker-compose.yml are also supported.
- If both canonical and legacy names are present, compose.yaml takes precedence.
- Maintainability features:
  - Fragments and extensions to keep files concise and DRY.
  - Multiple Compose files can be merged. Behavior:
    - Order matters: later files override or extend earlier ones.
    - Simple attributes and maps are overridden by the highest-order file.
    - Lists are merged by appending.
    - Relative paths resolve against the parent folder of the first Compose file when complementary files reside elsewhere.
    - When elements can be expressed as strings or objects, merges apply to the expanded form.
  - include can reuse other Compose files or factor parts out. Useful when depending on external applications (e.g., managed by another team) or when sharing components.

## CLI interaction (docker compose)

The Docker CLI provides docker compose and subcommands (included with Docker Desktop) to manage application lifecycle defined in compose.yaml.

Common commands:
- Start all services:
  - docker compose up
- Stop and remove running services:
  - docker compose down
- Stream and inspect logs:
  - docker compose logs
- List services and status:
  - docker compose ps

Refer to the CLI reference for the full command set.

## Illustrative example

This example defines a web frontend and a backend database. The frontend receives an HTTP config and an HTTPS certificate via config and secret, respectively. The backend persists data in a volume. Both share an isolated back-tier network; the frontend also connects to a front-tier network and publishes port 443.

```yaml
services:
  frontend:
    image: example/webapp
    ports:
      - "443:8043"
    networks:
      - front-tier
      - back-tier
    configs:
      - httpd-config
    secrets:
      - server-certificate

  backend:
    image: example/database
    volumes:
      - db-data:/etc/data
    networks:
      - back-tier

volumes:
  db-data:
    driver: flocker
    driver_opts:
      size: "10GiB"

configs:
  httpd-config:
    external: true

secrets:
  server-certificate:
    external: true

networks:
  # The presence of these objects is sufficient to define them
  front-tier: {}
  back-tier: {}
```

- docker compose up creates the frontend and backend services, provisions the specified networks and volume, and mounts the configuration and secret into the frontend.
- docker compose ps shows current service/container state and published ports, for example:
  - example-frontend-1 Up, 0.0.0.0:443->8043/tcp
  - example-backend-1 Up

## Key Points

- compose.yaml encodes a multi-container app per the Compose Specification: services, networks, volumes, configs, and secrets.
- Project naming (top-level name) scopes and isolates resources; Compose prefixes names and sets com.docker.compose.project.
- Preferred file is compose.yaml; legacy docker-compose.* files are supported, with compose.yaml taking precedence when both exist.
- Multiple files can be merged: later files override maps, append lists; relative paths resolve from the first file; merges apply to expanded forms.
- Use docker compose up/down/logs/ps to run, stop, observe, and inspect applications defined in the Compose file.