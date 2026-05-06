---
title: Secrets
slug: compose-secrets
source: compose-application-model
confidence: high
tags: [docker, compose, secrets, configs, security]
---

# Secrets

Secrets in the Docker Compose application model are a dedicated type of configuration resource intended for sensitive data (for example, certificates, keys, tokens) that require security considerations. In Compose, secrets are made available to services as files mounted into their containers. While this mounting behavior resembles volumes, secrets are distinct at the specification and platform levels because they map to platform-specific secure data stores and delivery mechanisms.

## Purpose and Behavior

- Secrets represent sensitive configuration data that should not be exposed without security controls.
- Delivery: From inside a container, a secret is mounted as a file (similar to a volume-backed file), enabling applications to read it at runtime.
- Platform distinction: Although secrets behave like files in containers, they are modeled separately from configs and volumes because platforms provide specialized secret-management resources.
- Scope: Secrets are defined at the project level and referenced by services that need them. Project scoping isolates resources across multiple deployments of the same Compose model.

## Relationship to Other Compose Resources

- Volumes: Provide persistent storage and filesystem mounts for data. Unlike volumes, secrets are specifically for sensitive data and are handled as a special configuration resource.
- Configs: Provide non-sensitive runtime configuration mounted as files. Secrets are a specialized “flavor” of configuration, separated due to stricter handling requirements.
- Networks: Unrelated to secret storage, but services that consume secrets can also be connected to one or more networks for inter-service communication.

## Declaration and Reference in compose.yaml

Compose supports a two-level pattern for secrets:
- Top-level declaration: Define the secrets available to the application.
- Service-level reference: Attach one or more declared secrets to a service so they are mounted into that service’s containers.

You can provide a minimal top-level declaration and refine platform-specific details at the service level as needed.

Example (focused on secrets):

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

Notes:
- The frontend service consumes the secret server-certificate, which is declared as external: true, indicating it is managed by the platform (for example, a secured secret store).
- Secrets are injected as files into the consuming service’s containers at runtime.

## Lifecycle and CLI Integration

- docker compose up:
  - Starts declared services.
  - Creates defined networks and volumes.
  - Injects declared configs and secrets into services that reference them.
- docker compose ps:
  - Lists running services, their status, and exposed ports (useful to verify the application state after secrets are injected).
- docker compose down:
  - Stops and removes running services and related resources created by the project (behavior for external secrets depends on the platform since they are not owned by the Compose project).

## Projects, Naming, and Isolation

- A project represents one deployment of a Compose specification. The project name (set via the top-level name attribute or CLI overrides) groups and isolates resources (including secrets) so multiple deployments can coexist on the same infrastructure.
- Resource naming is prefixed by the project and labeled with com.docker.compose.project to ensure isolation between different applications or multiple deployments of the same application model.

## Working with Multiple Compose Files

- Compose can merge multiple YAML files to build the final application model.
- Merge behavior:
  - Simple attributes and maps are overridden by later files in the specified order.
  - Lists are merged by appending.
  - Merges apply to the expanded form when elements can be expressed as single strings or complex objects.
- Practical implication: Secrets definitions and service references can be extended or overridden across files, enabling environment- or platform-specific secret wiring without modifying the base file.

## Illustrative Use Case

- Frontend service:
  - Receives an HTTPS server certificate via a secret from a secured store (external secret).
  - Receives non-sensitive HTTP configuration via a config resource.
  - Exposes port 443 and connects to both front-tier and back-tier networks.
- Backend service:
  - Uses a persistent volume for data.
  - Connects to the back-tier network.
- Result: docker compose up creates networks and volumes and injects the config and secret into the frontend service so it can serve HTTPS securely.

## Key Points

- Secrets are dedicated resources for sensitive data, mounted as files into containers and distinct from configs and volumes.
- Define secrets at the top level and reference them in services that need them; external secrets can be sourced from platform secret stores.
- docker compose up injects secrets into consuming services at runtime alongside other resources.
- Project scoping (via the project name) isolates secrets and other resources across multiple deployments.
- When merging Compose files, later files override maps and append to lists, enabling environment-specific secret configuration.