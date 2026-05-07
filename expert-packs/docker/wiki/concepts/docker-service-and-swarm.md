---
title: Docker service and Swarm
slug: docker-service-and-swarm
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker service and Swarm

Docker service and Swarm describe Docker’s built-in model for running and scaling containers across multiple Docker daemons. A Docker service is a first-class Docker object that defines and scales containers, while a Swarm is the cooperative set of Docker daemons that host those service-replicas and communicate via the Docker Engine API.

## Conceptual overview

- Docker is a set of products using operating system-level virtualization to package software into containers, enabling consistent application execution across environments.
- The core runtime is Docker Engine, consisting of:
  - dockerd (daemon): persistent process managing containers and Docker objects; listens on the Docker Engine API.
  - docker (CLI): client for interacting with the daemon via the API.
- Docker objects used to assemble applications include images, containers, and services.
  - Image: read-only template used to build containers; ships application binaries and dependencies.
  - Container: standardized, encapsulated runtime environment for applications.
  - Service: an object that scales containers across multiple Docker daemons; the cooperating daemons form a Swarm and communicate through the Docker API.

## Service

- Definition: A Docker service is a Docker object that specifies one or more identical container instances to run and scale across Docker daemons.
- Purpose: Enables horizontal scaling of a containerized workload beyond a single host by scheduling container instances on multiple daemons.
- Control plane interface:
  - Managed through the Docker Engine API.
  - Operable via the docker CLI (as a general interface to Docker objects).
- Relationship to other Docker objects:
  - Services are defined in terms of images; each service replica runs a container created from the referenced image.
  - Services orchestrate multiple containers, potentially spanning hosts, unlike a single standalone container on one daemon.

## Swarm

- Definition: A Swarm is the result of running services across multiple cooperating Docker daemons.
- Composition: A set of daemons that communicate via the Docker Engine API to host the containers defined by services.
- Function: Provides the distributed substrate on which services place and scale container instances.

## Architecture and data flow

- Client-to-daemon:
  - The docker CLI sends requests over the Docker Engine API.
  - dockerd receives API requests, manages images, containers, services, and coordinates with other daemons in a Swarm.
- Container runtime isolation (applies to all containers managed by services or standalone):
  - Linux kernel features: namespaces (isolation of process trees, network, user IDs, mounts) and cgroups (resource limits for CPU and memory).
  - Union/overlay-capable filesystems (e.g., OverlayFS) provide layered image and container filesystems.
- Platform considerations:
  - Linux runs containers directly using kernel facilities (including libcontainer).
  - macOS runs containers inside a Linux virtual machine.
  - Windows supports Docker Engine and Desktop; containers run with OS-level isolation in the supported environment.

## Images, registries, and deployment

- Images:
  - Read-only blueprints for containers; services reference images to instantiate replicas.
  - Built locally or pulled from registries.
- Registries:
  - Repositories for storing and distributing images; public or private.
  - Docker Hub is the default public registry for Docker.
  - Registries support event-based notifications.
- Example image definition (Dockerfile):
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

## Relationship to Docker Compose

- Docker Compose is a tool for defining and running multi-container Docker applications on a single logical environment using a YAML specification.
- The docker compose CLI can:
  - Build images.
  - Scale containers.
  - Start/stop multiple containers as a group.
- Scope distinctions (per source):
  - Compose focuses on multi-container definitions and lifecycle operations (commands aimed at one container, such as certain image manipulation or interactive options, are not within Compose’s scope).
  - Services/swarm address scaling across multiple Docker daemons (clustered scope), whereas Compose coordinates multiple containers (application scope), typically within a single environment.

## Design and performance context (relevant to services and swarm)

- Containers share a single OS kernel, reducing overhead vs. virtual machines and enabling higher container densities per host.
- Typical deployments can run many containers per host; lightweight isolation facilitates efficient horizontal scaling when services distribute workloads across multiple daemons in a Swarm.

## Platform and implementation notes

- Written in Go.
- Runs on Linux, Windows, macOS; supports multiple architectures (x86-64, ARM, s390x, ppc64le).
- Docker Engine (Linux) is under the Apache-2.0 license; Docker Desktop is under an end-user license agreement.

## Key Points

- A Docker service is a Docker object that defines and scales containers across multiple Docker daemons.
- A Swarm is the cooperative set of Docker daemons hosting service replicas and communicating via the Docker Engine API.
- Services depend on images stored in registries (Docker Hub by default) and instantiate containers from those images.
- Management flows through the docker CLI and Docker Engine API to dockerd, which orchestrates containers and services.
- Container isolation uses Linux namespaces and cgroups with layered filesystems; macOS runs containers via a Linux VM.