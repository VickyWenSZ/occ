---
title: Compose CLI (docker compose)
slug: compose-cli
source: compose-application-model
confidence: high
tags: [docker, compose, cli, yaml, orchestration]
---

# Compose CLI (docker compose)

The Compose CLI is the Docker command suite for defining and managing multi-container applications from a Compose file (compose.yaml) that follows the Compose Specification. It uses a declarative application model (services, networks, volumes, configs, secrets) and provides commands to build, start, stop, observe, and remove application resources as a coherent project.

## Compose application model

- Services
  - Abstract definition of application components implemented by running the same container image (with configuration) one or more times.
  - Services communicate over declared networks and consume volumes, configs, and secrets.
- Networks
  - Abstraction for connecting services with IP routing between containers.
  - Services attach to one or more networks; the presence of a network object in the Compose file is sufficient to define it.
- Volumes
  - High-level persistent data mounts with global options.
  - Declared at top-level and attached at the service level.
- Configs
  - Configuration data provided by the platform at runtime; presented inside containers as mounted files (similar to volumes) but with distinct platform-level semantics.
- Secrets
  - Sensitive configuration data exposed as files in containers, backed by platform-specific secure storage. Treated distinctly in the specification from general configs.

Note: Volumes, configs, and secrets can be declared with simple top-level definitions and further customized with platform-specific information at the service level.

This model is the Docker Compose implementation of the formal Compose Specification.

## Projects, naming, and isolation

- A project represents a single deployment of a Compose application on a platform.
- The top-level name attribute groups all resources (containers, networks, volumes, etc.) and isolates them from other applications or parallel deployments of the same application.
- When creating resources on a platform, resource names should be prefixed with the project name and labeled with com.docker.compose.project.
- Compose supports setting and overriding the project name so the same compose.yaml can be deployed multiple times on the same infrastructure by supplying distinct names.

## Compose file discovery and structure

- Default file names (searched in the working directory, precedence shown):
  - Preferred: compose.yaml
  - Alternative: compose.yml
  - Backward compatibility: docker-compose.yaml, docker-compose.yml
  - If multiple exist, compose.yaml is preferred.
- Fragments and extensions can be used to keep definitions DRY and maintainable.
- Files can be included via include to reuse other Compose files or factor out parts of the model, including models owned by other teams.

## Working with multiple Compose files

Compose can merge multiple files to form the final application model.

- Merge behavior (in file-order precedence):
  - Simple attributes and maps: overridden by the highest-order file.
  - Lists: merged by appending.
- Relative paths are resolved against the parent folder of the first Compose file, even when complementary files are elsewhere.
- Elements that support both string and object forms are merged in their expanded (object) form.

## CLI overview

- The Compose commands are available under docker compose in the Docker CLI.
- Docker Desktop includes the Compose CLI by default.
- The CLI manages the lifecycle of the application defined in compose.yaml: create, start, stop, observe logs, and remove resources.

### Key commands

- Start all services and create required resources:
  ```
  docker compose up
  ```
- Stop and remove services and associated resources:
  ```
  docker compose down
  ```
- Stream and inspect aggregated container logs:
  ```
  docker compose logs
  ```
- List services and their status (containers, state, ports):
  ```
  docker compose ps
  ```

## Illustrative example

A two-tier application with a frontend web service and a backend database:

- Frontend:
  - Image: example/webapp
  - Connected to front-tier (public) and back-tier (internal) networks
  - Exposes port 443 externally mapped to 8043 in the container
  - Receives an HTTP server config via configs and an HTTPS certificate via secrets
- Backend:
  - Image: example/database
  - Uses a persistent volume for data storage
  - Connected only to back-tier

Compose file:

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
  # Presence alone defines these networks
  front-tier: {}
  back-tier: {}
```

Behavior:

- docker compose up:
  - Creates frontend and backend services
  - Creates front-tier and back-tier networks
  - Creates/attaches db-data volume with specified driver and options
  - Injects httpd-config and server-certificate into the frontend
- docker compose ps example output:
  ```
  $ docker compose ps
  NAME                 IMAGE               COMMAND                    SERVICE   CREATED         STATUS         PORTS
  example-frontend-1   example/webapp      "nginx -g 'daemon of…"     frontend  2 minutes ago   Up 2 minutes   0.0.0.0:443->8043/tcp
  example-backend-1    example/database    "docker-entrypoint.s…"     backend   2 minutes ago   Up 2 minutes
  ```

## Key Points

- Compose uses a compose.yaml file conforming to the Compose Specification to model services, networks, volumes, configs, and secrets.
- Projects are named deployments that group and isolate resources; names can be overridden to deploy the same model multiple times, with resources labeled com.docker.compose.project.
- File discovery prefers compose.yaml; multiple Compose files can be merged with map override, list append, and paths resolved against the first file.
- The docker compose CLI (included with Docker Desktop) manages the full lifecycle: up, down, logs, ps.
- Declared networks, volumes, configs, and secrets are created or referenced as needed; external configs/secrets are mounted into services as files.