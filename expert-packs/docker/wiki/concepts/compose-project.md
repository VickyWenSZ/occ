---
title: Project and resource isolation
slug: compose-project
source: compose-application-model
confidence: high
tags: [docker-compose, project-name, isolation, networks, resources]
---

# Project and resource isolation

Project and resource isolation in Docker Compose is achieved by scoping all application resources (services, networks, volumes, configs, secrets) under a project. A project is an individual deployment of an application specification, identified by a project name. The project name is used to group resources, prevent naming collisions, and enable concurrent installations of the same Compose-defined application on the same platform.

## Project: definition and purpose

- A project is an individual deployment of a Compose application on a platform.
- The project name is set with the top-level `name` attribute in `compose.yaml`.
- The project name scopes and groups all resources so they are isolated from:
  - Other applications
  - Other installations of the same Compose application with different parameters

Example top-level project declaration:
```yaml
name: example

services:
  frontend:
    image: example/webapp
  backend:
    image: example/database
```

## Resource scoping, naming, and labels

- When creating resources on a platform, resource names must be prefixed by the project name and labeled with:
  - Label: `com.docker.compose.project`
- This naming/labeling convention provides deterministic isolation and discoverability of all resources belonging to a project.
- Resources grouped by the project include:
  - Services (containers derived from a service definition)
  - Networks (IP routing domains for service-to-service communication)
  - Volumes (persistent storage mounts)
  - Configs (non-secret configuration data mounted as files)
  - Secrets (sensitive data mounted as files)

Resulting names commonly include the project prefix. For example, after `docker compose up` with `name: example`, service instances can appear as:
```
example-frontend-1
example-backend-1
```

## Isolating deployments via project names

- Compose allows setting and overriding the project name so the same `compose.yaml` can be deployed multiple times, unchanged, on the same infrastructure.
- Distinct project names allow parallel, isolated stacks that:
  - Use the same service definitions and images
  - Maintain separate networks, volumes, configs, and secrets
  - Avoid port, name, and label collisions

## Intra-project isolation via networks, volumes, configs, and secrets

Within a single project, isolation boundaries are further structured by resource type:

- Networks
  - Abstract platform capability to create IP routes between containers.
  - Only services attached to the same network can communicate across that network.
  - Multiple networks enable tiering and internal/external segmentation.
- Volumes
  - High-level filesystem mounts for persistent data with global options.
  - Bound to services that declare them; other services cannot read unless explicitly mounted.
- Configs
  - Runtime/platform-dependent configuration mounted as files inside containers.
  - Defined differently at the platform level but behave like volumes from inside a container.
- Secrets
  - Sensitive configuration mounted as files.
  - Treated distinctly from configs due to security considerations.

Top-level declarations can be simple, with additional platform-specific details supplied at the service level.

## Example: isolated multi-tier deployment

Compose file fragment demonstrating project-scoped resources and network tiering:
```yaml
name: example

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

Behavior:
- `docker compose up` creates the `frontend` and `backend` services, their networks (`front-tier`, `back-tier`), volume (`db-data`), and injects the config and secret into `frontend`.
- The `frontend` service exposes `443` externally (mapped to container port `8043`), while `frontend` and `backend` communicate internally over `back-tier`.
- Isolation is achieved by:
  - Project scoping (names and labels prefixed with `example`)
  - Network segmentation (front-tier vs back-tier)
  - Dedicated per-project resources (volume, configs, secrets)

`docker compose ps` shows project-prefixed resource names and ports:
```
$ docker compose ps
NAME                 IMAGE               COMMAND                    SERVICE   CREATED         STATUS        PORTS
example-frontend-1   example/webapp      "nginx -g 'daemon of…"     frontend  2 minutes ago   Up 2 minutes  0.0.0.0:443->8043/tcp
example-backend-1    example/database    "docker-entrypoint.s…"     backend   2 minutes ago   Up 2 minutes
```

## Lifecycle and isolation with the CLI

- `docker compose up` starts all services and creates project-scoped resources.
- `docker compose down` stops and removes running services (and, per configuration/flags, associated resources).
- `docker compose logs` streams logs for services in the current project context.
- `docker compose ps` lists services and their status within the project.

All operations are executed within the active project's scope, ensuring actions do not affect other projects deployed on the same platform.

## Working with multiple files and includes

- Compose supports multiple files that are merged to form the final application model:
  - Later files override simple attributes and maps; lists are appended.
  - Relative paths resolve from the first file’s parent directory.
  - Merges apply to the expanded form when elements support both scalar and object syntax.
- `include` can reuse or factor out parts of the model (e.g., depending on an external application managed by another team).
- Regardless of how the model is composed (single file, merged files, or includes), the resulting resources are still grouped and isolated by the project name and label.

## Key Points

- A project is the isolation unit for a Compose deployment; its name scopes all resources.
- Resource names must be prefixed by the project and labeled with com.docker.compose.project.
- Distinct project names enable concurrent, isolated deployments of the same compose.yaml.
- Networks, volumes, configs, and secrets provide fine-grained isolation within a project.
- CLI operations (up/down/logs/ps) act strictly within the current project's resource scope.