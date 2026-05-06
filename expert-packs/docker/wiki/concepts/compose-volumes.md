---
title: Volumes
slug: compose-volumes
source: compose-application-model
confidence: high
tags: [docker compose, volumes, persistent storage, mounts, compose specification]
---

# Volumes

Volumes in the Compose application model are the mechanism for services to store and share persistent data. In the Compose Specification, a volume is described as a high-level filesystem mount with global options. Volumes are declared in the Compose file and attached to services, enabling data persistence across container restarts and data sharing between service instances.

## Definition and Role in the Compose Model

- Services store and share persistent data into volumes.
- A volume represents a platform-abstracted filesystem mount with options defined at a high level by the Compose Specification.
- Volumes are distinct from:
  - Configs: configuration data mounted as files; behave like volumes from inside containers but are defined differently at the platform level.
  - Secrets: sensitive configuration data mounted as files; provided through platform-specific secure resources and treated as a separate concept.

## Declaration and Usage in compose.yaml

- Volumes are declared at the top level under the volumes key.
- Services attach volumes using the service-level volumes field (mounts), which specifies the source volume and the target path inside the container.
- Compose supports a simple top-level declaration and allows adding more platform-specific information at the service level for volumes (as well as for configs and secrets).

Example (non-normative) showing a persistent volume attached to a backend service and its top-level definition with driver options:

```yaml
services:
  backend:
    image: example/database
    volumes:
      - db-data:/etc/data

volumes:
  db-data:
    driver: flocker
    driver_opts:
      size: "10GiB"
```

Notes:
- The service mount db-data:/etc/data attaches the named volume db-data to the container path /etc/data.
- The top-level volume definition can include driver and driver_opts to convey platform-specific volume settings.

## Lifecycle and Project Scoping

- docker compose up creates the necessary volumes (and networks) defined by the application model before starting services. In the example, it creates db-data and attaches it to the backend service.
- Compose deployments are organized into projects. The project’s name (set via the top-level name attribute or via CLI options) groups resources and isolates them from other applications or other installations of the same Compose file with distinct parameters.
- When creating resources on a platform, resource names should be prefixed by the project and labeled with com.docker.compose.project to ensure grouping and isolation.

## Working with Multiple Compose Files

- Multiple Compose files can be merged by appending or overriding elements based on file order.
  - Simple attributes and maps (such as top-level volume driver/driver_opts maps) are overridden by the highest-order file.
  - Lists (such as service-level volumes mounts) are merged by appending.
- Relative paths are resolved based on the first Compose file’s parent folder. Merges apply to the expanded form when elements can be strings or complex objects.

## Example in Context

A two-service application (frontend and backend) illustrates Compose concepts:
- The backend stores data in a persistent volume:
  - Service: backend
  - Mount: db-data:/etc/data
- The volume is defined with a driver and options:
  - volumes.db-data.driver: flocker
  - volumes.db-data.driver_opts.size: "10GiB"
- Running docker compose up:
  - Creates the necessary networks and volumes
  - Starts services and mounts the volume to the backend

## Related Concepts

- Services: computing components that use volumes for persistence.
- Networks: provide inter-service communication; orthogonal to volumes.
- Configs and Secrets: mounted as files like volumes from inside containers, but managed distinctly at the platform level.

## Key Points

- Volumes provide persistent, shareable storage for services and are modeled as high-level filesystem mounts with global options.
- Declare volumes at the top level and attach them to services via service-level mounts; platform-specific details can be added where appropriate.
- docker compose up creates required volumes before starting services; resources are grouped and isolated by project name and labels.
- In multi-file setups, top-level volume maps are overridden by higher-order files, while service-level volume mount lists are appended.
- Volume definitions can include driver and driver_opts to express platform-specific storage configuration (as shown with flocker and size).