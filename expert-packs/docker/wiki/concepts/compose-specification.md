---
title: Compose Specification
slug: compose-specification
source: compose-application-model
confidence: high
tags: [docker, compose, yaml, services, orchestration]
---

# Compose Specification

The Compose Specification defines a portable, platform-agnostic model for multi-container applications using a YAML configuration file (compose.yaml). Docker Compose implements this formal specification, enabling you to declare services, networks, volumes, configs, and secrets, and to deploy them as a cohesive project via the Compose CLI.

## Application Model

- Services
  - Abstract units of computation defined by a container image and configuration.
  - Materialized on platforms by running the same image (and configuration) one or more times.
  - Communicate over declared networks and can mount volumes, configs, and secrets.

- Networks
  - Abstractions of platform capabilities to establish IP routing between containers.
  - Services connect to one or more networks to communicate with other services.

- Volumes
  - High-level persistent data mounts with global options.
  - Shared and persisted across service instances as needed.

- Configs
  - Runtime or platform-dependent configuration data.
  - Presented inside containers as files (mounted similarly to volumes), but defined differently at the platform level.

- Secrets
  - Sensitive configuration data (e.g., certificates, keys) with dedicated handling.
  - Exposed to services as mounted files, backed by platform-specific secret stores.

Note: Volumes, configs, and secrets can be declared at the top level, then augmented with platform-specific details under each service.

## Projects and Resource Scoping

- A project is a single deployment of an application specification on a platform.
- The top-level name attribute defines the project name.
  - Used to group and isolate resources from other applications or distinct installs of the same spec.
  - When creating platform resources, prefix resource names by the project and set the label:
    - com.docker.compose.project
- Compose supports overriding the project name so the same compose.yaml can be deployed multiple times on the same infrastructure with different names.

## Compose File

- Default filenames (in working directory):
  - Preferred: compose.yaml (canonical) or compose.yml
  - Backward-compatible: docker-compose.yaml or docker-compose.yml
  - If both canonical and legacy files exist, compose.yaml is preferred.

- Structure aids
  - Fragments and extensions help keep files efficient and maintainable.
  - include supports reusing other Compose files or factoring parts of the model, useful for shared dependencies or cross-team integration.

## Multiple Files and Merge Semantics

Compose can consume multiple files and merge them to form the final model. Merge behavior is ordered according to the file list you supply:

- Simple attributes and maps: overridden by the highest-order (last) file.
- Lists: merged by appending.
- Relative paths: resolved against the first Compose file’s parent folder, even when later files are in other directories.
- Elements that can be expressed as either a string or an object are merged in their expanded (object) form.

See “Working with multiple Compose files” for detailed procedures.

## CLI Integration

The Docker Compose CLI (docker compose) manages the application lifecycle described in compose.yaml. Docker Desktop includes the CLI by default.

Common commands:
- Start all services:
  - docker compose up
- Stop and remove running services:
  - docker compose down
- Stream container logs:
  - docker compose logs
- List services and status:
  - docker compose ps

## Illustrative Example

The example below shows a frontend (exposes 443, consumes a config and a secret) and a backend (persists data to a volume). They share an isolated back-tier network; the frontend also connects to a front-tier.

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
  # Presence is sufficient to define these networks with defaults
  front-tier: {}
  back-tier: {}
```

- docker compose up:
  - Starts frontend and backend services.
  - Creates required networks and the db-data volume.
  - Injects httpd-config and server-certificate into the frontend.

- docker compose ps example output:
```
$ docker compose ps
NAME                 IMAGE               COMMAND                    SERVICE   CREATED         STATUS        PORTS
example-frontend-1   example/webapp      "nginx -g 'daemon of…"    frontend  2 minutes ago   Up 2 minutes  0.0.0.0:443->8043/tcp
example-backend-1    example/database    "docker-entrypoint.s…"    backend   2 minutes ago   Up 2 minutes
```

## Key Points

- The Compose Specification models applications as services connected by networks, with persistent state in volumes and runtime data via configs and secrets.
- The project name scopes and isolates resources; set com.docker.compose.project when creating platform resources.
- Preferred file is compose.yaml; multiple files merge with maps overridden, lists appended, and paths resolved relative to the first file.
- Configs and secrets are mounted as files like volumes but have distinct, platform-specific definitions and handling.
- The docker compose CLI (up, down, logs, ps) manages the full lifecycle of the declared multi-container application.