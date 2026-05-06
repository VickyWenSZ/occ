---
title: Configs
slug: compose-configs
source: compose-application-model
confidence: high
tags: [docker, compose, configs, containers, specification]
---

# Configs

Configs in the Docker Compose application model represent configuration data that is dependent on runtime or platform. They are a first-class concept in the Compose Specification, distinct from volumes and secrets, and are consumed by services at runtime.

## Concept and Behavior

- Purpose: Provide runtime- or platform-dependent configuration data to services.
- Container behavior: From inside a container, configs behave like volumes—they are mounted as files made available to the service.
- Platform model: Although they appear as mounted files inside containers, configs are defined and managed differently at the platform level than volumes.
- Distinction from secrets: Secrets are a specific flavor of configuration intended for sensitive data and are handled via platform-specific secure stores. Configs cover non-sensitive configuration data.

## Declaration and Attachment

- Top-level declaration: Configs can be declared once at the top level of the Compose file (compose.yaml).
- Service-level use: Services reference one or more configs to have them mounted into their containers.
- Layering information: You can keep a simple top-level declaration for configs and add platform-specific information at the service level as needed.

Example (excerpt focusing on configs):
```yaml
services:
  frontend:
    image: example/webapp
    configs:
      - httpd-config   # Attach a config to the service
    secrets:
      - server-certificate

configs:
  httpd-config:
    external: true     # Reference a platform-provided configuration

secrets:
  server-certificate:
    external: true
```

## External Configs

- external: true indicates that a config is provided by the underlying platform (created outside the current Compose project) and should be referenced rather than created by Compose.
- Use case: Reference infrastructure-managed configuration (for example, an HTTP server config) and inject it into services at runtime.

## Lifecycle with the Compose CLI

- Start: docker compose up creates required resources and injects configs into the relevant services.
- Introspection: docker compose ps shows running services and their state; docker compose logs can be used for debugging services that consume configs.
- Stop/remove: docker compose down stops and removes the running services and associated resources created by the project (not external ones referenced with external: true).

Example:
```bash
docker compose up
docker compose ps
docker compose down
```

In the illustrative example, docker compose up starts frontend and backend services, creates networks and volumes, and injects the configuration (httpd-config) and secret (server-certificate) into the frontend container.

## Interactions with Other Compose Primitives

- Services: The units that consume configs; a service can reference multiple configs.
- Volumes: Provide persistent data mounts; unlike volumes, configs are for configuration data and are defined differently at the platform level.
- Secrets: Also mounted as files, but for sensitive data; sufficiently distinct to be a separate concept in the specification.
- Networks: Orthogonal to configs; used for inter-service communication.

## Projects and Resource Scoping

- Project: A deployment of an application specification, named via the top-level name attribute.
- Scoping: Resources created on a platform should be prefixed by the project name and labeled with com.docker.compose.project to group and isolate them. This scoping applies to project-managed resources; external configs are managed outside the project.

## Multiple Compose Files and Reuse

When composing multiple files (merging), the following rules apply and affect config declarations and attachments:

- Order: Files are combined in the order specified.
- Override vs append:
  - Simple attributes and maps are overridden by the highest-order file (top-level configs: map keys and their attributes follow this rule).
  - Lists are merged by appending (service-level configs lists are appended across files).
- Expanded form: When elements can be a simple string or an object, merges apply to the expanded object form.
- Include: You can factor parts of your application into separate Compose files using include, useful when configs come from or must align with another application's definitions.

## End-to-End Example (Contextual)

A two-service application:
- frontend (example/webapp): consumes an external HTTP configuration via configs and a secret for TLS; connected to front-tier and back-tier networks; exposes port 443.
- backend (example/database): uses a persistent volume; on back-tier network.

Relevant configs excerpt is shown above; the full example also defines networks, secrets, and volumes to complete the application model.

## Key Points

- Configs supply runtime/platform-dependent configuration to services and are mounted as files inside containers.
- They are distinct from volumes (persistence) and secrets (sensitive data), with a dedicated concept in the Compose Specification.
- Declare configs at the top level and attach them to services; platform-specific details can be added at the service level.
- external: true references platform-managed configuration rather than creating it within the Compose project.
- In multi-file setups, top-level configs (maps) are overridden by higher-order files, while service-level configs (lists) are appended.