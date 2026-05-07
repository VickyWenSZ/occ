---
title: Docker daemon (dockerd)
slug: docker-daemon-dockerd
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker daemon (dockerd)

The Docker daemon (dockerd) is the persistent background service of Docker Engine that manages container lifecycles and Docker objects. It listens for and processes requests sent over the Docker Engine API (from local or remote clients), orchestrates image and container operations, and coordinates multi-node clustering via services and swarms.

Docker Engine is written in Go and provides OS-level virtualization. It runs on Linux, Windows, and macOS, and targets multiple CPU architectures (x86-64, ARM, s390x, ppc64le). As of 20 April 2026, the stable release is 29.4.1. Licensing differs by component: Docker Engine for Linux is under the Apache-2.0 license, while Docker Desktop is covered by an end-user license agreement.

## Role in the Docker architecture

- Persistent manager:
  - Runs as dockerd to manage containers and higher-level Docker objects across their lifecycles.
  - Listens for requests via the Docker Engine API and executes them.
- Client/daemon model:
  - The docker CLI is a user-facing client that interacts with one or more Docker daemons.
  - Multiple cooperating daemons form a swarm for clustering and scaling.

## Objects managed by dockerd

- Images:
  - Read-only templates used to build containers; used to store and ship applications.
- Containers:
  - Standardized, encapsulated environments that run applications; created and managed via the Docker API or CLI.
- Services:
  - Define desired state and scaling across multiple daemons; form a swarm (set of cooperating daemons communicating through the Docker API).

## Engine API and client interaction

- dockerd exposes the Docker Engine API to:
  - Create, start, stop, and remove containers.
  - Build, tag, pull, and push images.
  - Define and scale services in swarm mode.
  - Query and manipulate other Docker objects.
- The docker CLI sends commands that are translated into Engine API requests to dockerd.
- Docker Compose:
  - Uses YAML to define multi-container applications.
  - The docker compose CLI issues operations to dockerd to build and run sets of services, scale them, and manage their lifecycle together.
  - Options include build (e.g., Dockerfile path) and command (override defaults). Commands focused on single-container, user-interactive flows or low-level image manipulation are generally not the focus of Compose.

## Registry integration

- Registries store and distribute images. Clients (via dockerd) pull images for use and push images they have built.
- Registries can be public or private; Docker Hub is the default public registry.
- Registries can emit notifications based on events (e.g., image push).

## Build inputs (Dockerfile)

dockerd builds images from Dockerfiles that specify base images, dependencies, configuration, and exposed interfaces.

Example Dockerfile from the source:

```dockerfile
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

## Kernel integration and isolation model (Linux)

- Resource isolation and security:
  - Namespaces isolate process trees, networking, user IDs, and mounts (containerized processes see a restricted view of the system).
  - cgroups enforce resource limits (CPU, memory).
- Storage:
  - Union-capable filesystems (such as OverlayFS) provide layered image and container filesystems.
- Runtime:
  - Docker implements a high-level API for lightweight containers that run processes in isolation.
  - Initially used LXC; since version 0.9, Docker includes libcontainer to directly use Linux kernel facilities, with support for abstracted interfaces via libvirt, LXC, and systemd-nspawn.

## Platform specifics

- Linux:
  - Containers run natively using kernel features (namespaces, cgroups, union FS).
- macOS:
  - Docker on macOS runs containers inside a Linux virtual machine.
- Windows:
  - Docker Engine and client integration are available on Windows; the platform supports running Docker through native integrations (including Windows Server) and, for desktop workflows, through Docker Desktop and technologies such as WSL 2.

## Efficiency and scale characteristics

- Containers share the services of a single operating system kernel, using fewer resources than virtual machines.
- Docker containers are lightweight; a single host can run many containers concurrently. A 2018 analysis reported a typical use case of eight containers per host, with a quarter of organizations running 18 or more per host.
- Docker can also be installed on small systems such as Raspberry Pi.

## Licensing and distribution

- Docker Engine (Linux) is licensed under Apache-2.0.
- Docker Desktop is distributed under an end-user license agreement (Docker introduced changes in August 2021 affecting enterprise usage).
- Docker platform includes both free and paid tiers.

## Historical evolution relevant to dockerd

- 2013: Docker open-sourced; used LXC as the default execution environment.
- 2014 (v0.9): Replaced LXC with libcontainer (written in Go), integrating more directly with Linux kernel features.
- Ongoing: The Moby project provides open R&D for Docker components.

## Key Points

- dockerd is the persistent Docker Engine daemon that manages containers, images, and services, serving the Docker Engine API.
- On Linux, dockerd relies on namespaces, cgroups, and union filesystems (e.g., OverlayFS) for isolation and layered storage; containers are lighter than VMs.
- Images, containers, and services (swarm) are the core objects; registries (with Docker Hub as default) enable pull/push and event notifications.
- Docker Compose defines multi-container apps in YAML and drives dockerd via the CLI to build, run, and scale services.
- Docker Engine is written in Go, runs on Linux/Windows/macOS across multiple CPU architectures, and is Apache-2.0 licensed on Linux (Docker Desktop uses an EULA).