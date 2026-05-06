---
title: Moby project
slug: moby-project
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Moby project

## Overview
The Moby project is an open research and development initiative created by Docker, Inc. in 2017. It is positioned within the broader Docker container ecosystem, which provides operating system–level virtualization for packaging and running applications in containers. Moby’s stated purpose is to serve open R&D, reflecting Docker’s practice of developing container technologies in the open since Docker’s initial open-source release in March 2013.

## Historical Context within Docker
- Origins: Docker began as an internal project at dotCloud (a PaaS company) founded by Kamel Founadi, Solomon Hykes, and Sebastien Pahl, and was open-sourced in March 2013.
- Early runtime: Docker initially used LXC as its default execution environment.
- Low-level container runtime: With Docker 0.9 (2014), Docker introduced libcontainer (written in Go) to directly leverage Linux kernel primitives for containers.
- Establishment of Moby (2017): Docker created the Moby project for open research and development, formalizing an open approach to experimenting with and advancing container infrastructure.
- Ongoing relevance: Docker and its ecosystem (including research and retrospective recognition, e.g., a 2026 Communications of the ACM cover article) continued to evolve after Moby’s creation.

## Technical Context: Docker’s Containerization Stack
Moby sits in the context of Docker’s core technologies and patterns, which define the areas of container R&D it relates to:

- OS-level virtualization foundations (Linux):
  - Kernel primitives: cgroups (resource control), namespaces (isolation of process trees, networks, user IDs, and filesystems).
  - Union-capable filesystems: e.g., OverlayFS for layered images and efficient copy-on-write.
  - Runtime abstraction: Docker provides its own libcontainer and can also utilize interfaces like libvirt, LXC, and systemd-nspawn.
- Core software and interfaces:
  - Docker Engine (daemon: dockerd) exposes the Docker Engine API to manage images, containers, and services.
  - Docker CLI (docker) is the user-facing command-line client.
- Objects and orchestration model:
  - Images: read-only templates for packaging software and dependencies.
  - Containers: standardized, isolated execution environments instantiated from images.
  - Services/Swarm: scaling containers across multiple daemons into cooperating clusters via the Docker API.
- Distribution:
  - Registries (e.g., Docker Hub) for pushing/pulling images and subscribing to image-related events/notifications.

These areas collectively define the technical landscape around which open R&D such as the Moby project operates.

## Platform and Ecosystem Relevance
- Cross-environment consistency: Docker packages applications and dependencies to run across Linux, Windows, and macOS (on macOS via a Linux VM).
- Resource efficiency: Containers share a single OS kernel, providing lower overhead than full virtual machines and enabling high container density per host.
- Tooling and workflows (context):
  - Dockerfile: declarative build instructions for images (base distribution, environment, package installation, file copy, port exposure, volumes).
  - Compose: YAML-based multi-container definitions and lifecycle management via the docker compose CLI.

## Governance and Licensing Context
- Development: Docker, Inc. continues to develop Docker while maintaining open-source components.
- Licensing: Docker Engine (Linux) is available under the Apache-2.0 license; Docker Desktop is governed by a separate end-user license agreement (EULA). The Moby project’s creation underscores the open research and development orientation within Docker’s licensing and contribution model.

## Timeline Highlights
- 2013-03: Docker open-sourced; initially used LXC.
- 2014: Docker 0.9 introduces libcontainer (Go), leveraging kernel primitives directly.
- 2017: Docker creates the Moby project for open research and development.
- 2026-03: Communications of the ACM features Docker in a decade retrospective.

## Key Points
- The Moby project was created by Docker, Inc. in 2017 explicitly for open research and development in the containerization domain.
- It exists within Docker’s open-source lineage that includes Docker Engine, libcontainer, and kernel-based isolation (cgroups, namespaces) with layered filesystems (e.g., OverlayFS).
- Moby’s context spans Docker’s object model (images, containers, services) and distribution mechanisms (registries like Docker Hub).
- Docker Engine (Linux) is Apache-2.0 licensed; Docker Desktop uses an EULA—framing the open R&D posture that Moby represents.
- The project follows years of iterative evolution in Docker’s runtime architecture, from LXC to libcontainer, and broad ecosystem adoption.