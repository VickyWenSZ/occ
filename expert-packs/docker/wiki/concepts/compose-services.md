---
title: Services
slug: compose-services
source: compose-application-model
confidence: high
tags: [docker, compose, services, networks, volumes]
---

# Services

Services are the core compute components in a Docker Compose application model. A service is an abstract unit defined by a container image and its configuration, instantiated one or more times on a platform. The Compose file (compose.yaml) describes services and their relationships to other platform abstractions (networks, volumes, configs, secrets), and the Compose CLI orchestrates their lifecycle.

## Definition and Role in the Compose Application Model

- A service specifies how to run one or more identical containers from the same image and configuration.
- Services communicate over declared networks, persist data via volumes, and can be injected with runtime/platform-dependent configuration via configs and secrets.
- Services are platform-agnostic abstractions defined by the Compose Specification and implemented by Docker Compose.

## Related Application Model Abstractions

- Networks
  - Platform capability abstraction that establishes IP routing between containers within and across services.
  - Services connect to one or more networks to enable inter-service communication and/or external exposure.
- Volumes
  - High-level persistent storage mounts with global options, used by services to store/share data beyond container lifecycles.
  - Declared at top-level and referenced/mounted within services.
- Configs
  - Non-sensitive configuration data that may be runtime- or platform-dependent.
  - From inside a container, configs are mounted as files (volume-like), but are defined as a distinct platform resource.
- Secrets
  - Sensitive configuration data delivered securely to services.
  - Exposed to containers as files; modeled distinctly from configs due to platform-specific handling and security properties.
- Note: Volumes, configs, and secrets can have simple top-level declarations, with optional platform-specific detail at the service level.

## Projects and Resource Isolation

- A project is a single deployment of a Compose application on a platform.
- The top-level name attribute sets the project name used to:
  - Group and isolate all resources (services, networks, volumes, etc.).
  - Prefix resource names.
  - Apply the label com.docker.compose.project on created resources.
- Compose supports customizing/overriding the project name to deploy the same compose.yaml multiple times on the same infrastructure without file changes.

## Compose File: Location and Structure

- Default file names (preferred first): compose.yaml, compose.yml.
- Backwards-compatible names also supported: docker-compose.yaml, docker-compose.yml.
- If both canonical and legacy names exist, compose.yaml is preferred.

Maintainability features:
- Fragments and extensions can be used to keep files concise and DRY.
- include allows factoring out or reusing other Compose files (e.g., depending on an application managed by another team).

## Working with Multiple Compose Files

- Multiple YAML files can be merged to define an application:
  - Order controls precedence: later files override earlier ones.
  - Simple attributes and maps are overridden by higher-order files.
  - Lists are merged by appending.
  - Relative paths resolve against the first (base) Compose file’s parent folder, even if subsequent files are elsewhere.
  - Merges apply to the expanded form when elements can be expressed as a single string or an object.

## CLI: Managing Service Lifecycle

- docker compose up
  - Creates required resources (networks, volumes, configs, secrets) and starts all services.
- docker compose down
  - Stops and removes the running services (and associated resources, as applicable).
- docker compose logs
  - Streams/prints container output for debugging or monitoring.
- docker compose ps
  - Lists services with status, names, images, commands, and published ports.
- The Compose CLI ships with Docker Desktop by default.

## Illustrative Example

A two-service application with a frontend and backend:

- frontend
  - Image example/webapp
  - Exposes 443 (mapped to container port 8043)
  - Connected to front-tier and back-tier networks
  - Injected with one config (httpd-config) and one secret (server-certificate)
- backend
  - Image example/database
  - Persists data to a volume (db-data)
  - Connected to back-tier network
- Two networks: front-tier, back-tier
- One volume: db-data with driver and size option
- One config (external): httpd-config
- One secret (external): server-certificate

compose.yaml:
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
  front-tier: {}
  back-tier: {}
```

Commands:
```bash
# Start all services and required resources from compose.yaml
docker compose up

# View service/container status
docker compose ps

# Inspect logs across services
docker compose logs

# Stop and remove running services
docker compose down
```

Example docker compose ps output:
```
NAME                 IMAGE               COMMAND                   SERVICE   CREATED         STATUS        PORTS
example-frontend-1   example/webapp      "nginx -g 'daemon of…"    frontend  2 minutes ago   Up 2 minutes  0.0.0.0:443->8043/tcp
example-backend-1    example/database    "docker-entrypoint.s…"    backend   2 minutes ago   Up 2 minutes
```

## How Services Interact with Platform Abstractions

- Networking
  - Services list networks to join; connectivity between containers is established per-network.
  - External exposure is achieved via published ports on a service.
- Storage
  - Volumes are declared and attached via service volume mounts, enabling persistence across container restarts/replacements.
- Configuration
  - Configs and secrets are declared and then referenced under a service; inside containers, they appear as mounted files.
  - External: true indicates the resource is managed outside the current project and should be consumed as-is.

## Key Points

- A service is an abstract definition for running one or more identical containers from the same image and configuration.
- Services connect via networks, persist data with volumes, and receive configuration via configs and secrets (mounted as files).
- Projects isolate and group resources; the project name prefixes resources and sets the com.docker.compose.project label.
- compose.yaml is the canonical file; multiple files can be merged with ordered overrides (maps override, lists append; paths resolve from the first file).
- docker compose up/down/logs/ps manage service lifecycles and provide operational visibility.