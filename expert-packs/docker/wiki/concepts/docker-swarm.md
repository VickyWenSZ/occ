---
title: Docker Swarm
slug: docker-swarm
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker Swarm

Docker Swarm is the result of scaling Docker containers across multiple Docker daemons using the Docker “service” abstraction. A service distributes containerized workloads over a cooperating set of daemons that communicate through the Docker Engine API; this cooperating set is called a swarm. Swarm mode leverages Docker’s OS-level virtualization model—containers, images, and registries—while retaining the same Docker Engine, daemon (dockerd), and CLI interaction patterns.

## Concept and Scope

- Service: A Docker object that allows containers to be scaled across multiple Docker daemons. Defining one or more services yields a swarm: a set of cooperating daemons communicating via the Docker API.
- Swarm: A logical cluster formed by Docker daemons (dockerd) that work together using the Docker Engine API. Swarms coordinate the placement and scaling of containers defined by services.

## Architecture Building Blocks

- Docker Engine and Daemons
  - dockerd is a persistent process that manages containers and Docker objects and listens for requests via the Docker Engine API.
  - The docker CLI provides a command-line interface to interact with one or more Docker daemons, including issuing service-related operations.

- Docker API and Objects
  - Containers: Standardized, encapsulated environments for running applications; managed via the API/CLI.
  - Images: Read-only templates used to build containers; the unit shipped to registries and pulled by daemons participating in a swarm.
  - Services: Top-level objects for scaling and distributing containers across multiple daemons; defining services yields a swarm of cooperating daemons.

- Registries and Image Distribution
  - Registries store and serve images to Docker clients/daemons; supports pull/push operations.
  - Docker Hub is the default and main public registry.
  - Registries can emit notifications based on repository/image events—useful for automating image distribution to daemons that participate in a swarm.

## Container Runtime Foundations (relevant to Swarm)

- Isolation and Efficiency
  - Linux kernel features: cgroups and namespaces provide resource limits and isolation (process trees, network, user IDs, mounted filesystems).
  - Union-capable filesystems such as OverlayFS enable layered image storage for lightweight containers.
  - Because containers share a single OS kernel, they use fewer resources than virtual machines; hosts typically run multiple containers simultaneously (e.g., analyses have observed around eight per host, with a subset running 18+).

- Cross-Environment Portability
  - Docker packages applications and dependencies in containers that, in principle, can run on Linux, Windows, or macOS.
  - macOS runs Docker containers via a Linux virtual machine.
  - Containers can be deployed across on-premises, public, or private cloud environments, and even on resource-constrained devices like Raspberry Pi—contexts in which swarms can coordinate multiple daemons.

## Services and Swarm Semantics

- Service Definition
  - Encapsulates how containers are instantiated from images and scaled across multiple daemons.
  - Scaling a service creates multiple container instances distributed over the swarm’s daemons.

- Swarm Communication
  - Daemons in a swarm communicate through the Docker Engine API to coordinate service-related lifecycle operations (create, scale, start/stop, etc.).

## Images, Dockerfiles, and Swarm

- Services reference images; swarms rely on daemons pulling the correct image versions from registries.
- Dockerfiles define how images are built. Example:

```
ARG CODE_VERSION=latest
FROM ubuntu:${CODE_VERSION}
COPY ./examplefile.txt /examplefile.txt
ENV MY_ENV_VARIABLE="example_value"
RUN apt-get update
# Mount a directory from the Docker volume
# Note: This is usually specified in the 'docker run' command.
VOLUME ["/myvolume"]
# Expose a port (22 for SSH)
EXPOSE 22
```

- Consistent image construction is essential for deterministic service behavior across all daemons in a swarm.

## Compose vs. Swarm

- Docker Compose defines and runs multi-container applications using YAML, orchestrating creation and startup with a single command via the docker compose CLI.
- Compose focuses on coordinating multiple containers (often on a single host), whereas a service scales containers across multiple daemons to form a swarm.
- In Compose, commands aimed at image manipulation or interactive single-container options are not relevant because they target one container; in contrast, services natively model multi-daemon scaling.

## Platform and Deployment Context

- Supported operating systems for Docker include Linux, Windows, and macOS; platforms include x86-64, ARM, s390x, and ppc64le.
- On Linux, Docker directly uses kernel isolation features; on macOS, containers run inside a Linux VM.
- Swarm deployments benefit from Docker’s portability across on-prem, public, and private clouds.

## Key Points

- A Docker service scales containers across multiple Docker daemons; the cooperating set of daemons is a swarm.
- Swarms are coordinated via the Docker Engine API; daemons (dockerd) and the docker CLI are the primary control plane interfaces.
- Images (built from Dockerfiles) are pulled from registries (e.g., Docker Hub) by daemons participating in a swarm.
- Container isolation relies on Linux cgroups, namespaces, and union filesystems like OverlayFS, enabling high density and efficiency.
- Compose coordinates multi-container apps, while services enable multi-daemon scaling that forms a swarm.