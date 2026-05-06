---
title: Networks
slug: compose-networks
source: compose-application-model
confidence: high
tags: [docker compose, networks, services, isolation, compose file]
---

# Networks

In the Compose Specification, networks are a platform capability abstraction used to establish IP routing between containers so that services can communicate. Networks define how services connect to each other and enable traffic segmentation (for example, front-tier vs. back-tier). Compose creates the necessary networks declared in your compose.yaml and connects service containers to them when you run the application.

## Concept

- A network is an abstraction to establish an IP route between containers within services connected together.
- Services communicate with each other through networks; a service can attach to one or more networks to control reachability.
- Networks are resources in a Compose project. The project name groups and isolates all resources (including networks) from other applications or other deployments of the same application using a different project name.
- Compose sets the com.docker.compose.project label and uses the project name as a prefix for resource names so multiple deployments of the same compose.yaml can coexist on the same infrastructure.

## Declaring networks in compose.yaml

- Networks are defined at the top-level networks section.
- A service opts into one or more networks via its networks list.
- The presence of a top-level network object is sufficient to define it; empty objects {} create networks with default settings.

Example (fragment):
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
  db-data: {}

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

Notes:
- frontend is dual-homed (front-tier and back-tier) and exposes port 443 for external usage, while backend is isolated to back-tier.
- ports configure host-to-container mappings and are orthogonal to network membership.

## Creation and lifecycle via CLI

- docker compose up creates the services and the necessary networks and volumes, and injects configs and secrets as declared.
- docker compose ps shows running services, their status, and any published ports; this helps verify connectivity expectations (for example, external exposure on 0.0.0.0:443->8043/tcp in the example).

Example:
```
$ docker compose up
# ...
$ docker compose ps
NAME                 IMAGE               COMMAND                 SERVICE   CREATED        STATUS       PORTS
example-frontend-1   example/webapp      "nginx -g '...'"        frontend  2 minutes ago  Up 2 minutes 0.0.0.0:443->8043/tcp
example-backend-1    example/database    "docker-entrypoint..."  backend   2 minutes ago  Up 2 minutes
```

## Project scoping and isolation

- A project is an individual deployment; its name (set via the top-level name attribute or CLI options) groups resources and isolates them from other deployments.
- To create resources on a platform, resource names are prefixed by the project and the com.docker.compose.project label is set. This ensures:
  - Distinct, non-conflicting network resources per deployment.
  - The ability to deploy the same compose.yaml multiple times on the same infrastructure by passing a distinct project name.

## Working with multiple Compose files

- Compose can merge multiple YAML files to define the model:
  - Simple attributes and maps (such as the top-level networks map) are overridden by the highest-order file.
  - Lists (such as a service’s networks list) are merged by appending.
- Merges apply to the expanded form when elements can be expressed as strings or objects.
- Relative paths resolve from the first Compose file’s parent folder; network names themselves are logical and are still grouped under the project.

## Relationship to other Compose model elements

- Services: compute units that attach to networks to communicate.
- Volumes: persistent data stores; independent of network configuration.
- Configs and secrets: mounted as files into containers; orthogonal to networks.
- Ports: expose container ports externally; used in combination with network membership to shape connectivity (internal via networks, external via published ports).

## Key Points

- Networks in Compose are an abstraction that provides IP routing between containers; services join networks to communicate.
- Declare networks at the top level and reference them from services; an empty {} definition is sufficient to create a network.
- docker compose up creates the necessary networks; project naming groups and isolates those resources.
- Multiple networks enable tiered segmentation (for example, front-tier and back-tier) and services can connect to multiple networks.
- When merging Compose files, top-level network definitions (maps) are overridden by later files; service networks lists are appended.