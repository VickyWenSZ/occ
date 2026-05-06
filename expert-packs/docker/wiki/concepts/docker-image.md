---
title: Docker image
slug: docker-image
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker image

A Docker image is a read-only template used to build containers and to store and ship applications within the Docker platform. Images are one of the core Docker objects, alongside containers and services. They encapsulate application software and its dependencies so that applications can run consistently across different environments, including on-premises systems and public or private clouds, on Linux, Windows, or macOS hosts.

## Role in Docker architecture

- Objects:
  - Images: Read-only templates used to create containers; used to store and distribute applications.
  - Containers: Standardized, encapsulated environments that run applications; instantiated from images and managed via the Docker API or CLI.
  - Services: Definitions that scale containers across multiple Docker daemons; collections of cooperating daemons form a swarm and communicate through the Docker API.

- Software components:
  - Docker daemon (dockerd): Persistent process that manages container objects and listens for requests via the Docker Engine API.
  - Docker client (docker): Command-line interface that interacts with Docker daemons via the Engine API.

- Execution model and portability:
  - Docker packages applications and dependencies in containers that, in principle, run on Linux, Windows, or macOS, enabling consistent deployment across on-premises, distributed, decentralized, or cloud environments.
  - On Linux, Docker relies on kernel features such as cgroups and namespaces plus a union-capable filesystem (e.g., OverlayFS) to run multiple isolated containers efficiently on a single kernel.
  - On macOS, Docker runs containers inside a Linux virtual machine.

## Building images with Dockerfile

Images are commonly built from a Dockerfile, a text file that specifies the base image and build steps for assembling application software, runtime, configuration, and files.

Example Dockerfile (from source):

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

Key directives illustrated:
- ARG: Defines a build-time variable (e.g., CODE_VERSION) used within the Dockerfile.
- FROM: Selects a base image (e.g., ubuntu) and can reference build arguments for tag selection.
- COPY: Adds files from the build context into the image’s filesystem.
- ENV: Sets environment variables baked into the image for container runtime.
- RUN: Executes commands at build time to modify the image (e.g., install/update packages).
- VOLUME: Declares a mount point intended for volumes.
- EXPOSE: Documents the port a container created from the image will listen on.

Images built from such instructions are immutable (read-only) artifacts that can be distributed and instantiated into containers.

## Distribution via registries

Docker images are stored and distributed via registries:

- Registries can be public or private repositories for images.
- Clients connect to registries to download ("pull") images for use or upload ("push") images they have built.
- Docker Hub is the main public registry and the default where Docker looks for images.
- Registries can emit notifications based on events (e.g., image pushes).

This registry workflow enables sharing and reuse of images across organizations and environments.

## Integration with Docker Compose

Docker Compose defines and runs multi-container applications using YAML:

- Compose can build images via the build option, including configuration such as the Dockerfile path.
- The command option in Compose can override default Docker commands for services.
- The docker compose CLI orchestrates creation and startup of all containers defined in a Compose file with a single command.
- Compose targets multi-container orchestration; commands focused purely on image manipulation or single-container interactivity are out of scope for Compose because they address one container at a time.

## Isolation and efficiency context

While images are templates, they are integral to Docker’s lightweight containerization:

- Containers created from images are isolated via Linux kernel namespaces (process trees, network, user IDs, mounts) and governed by cgroups (CPU, memory limits).
- Multiple containers can run simultaneously on a single host, benefiting from the shared OS kernel and union filesystems to minimize overhead compared to traditional virtual machines.

## Key Points

- A Docker image is a read-only template that stores and ships applications and is used to create containers.
- Images are distributed via registries (public or private); Docker Hub is the default public registry, supporting pull/push and event notifications.
- Images are commonly built from Dockerfiles using directives like FROM, RUN, COPY, ENV, VOLUME, and EXPOSE.
- Compose can build images and orchestrate multi-container applications, while image-specific, single-container commands fall outside Compose’s scope.
- Docker’s isolation (namespaces, cgroups) and storage (union-capable filesystems) make image-based containers lightweight and portable across Linux, Windows, and macOS environments.