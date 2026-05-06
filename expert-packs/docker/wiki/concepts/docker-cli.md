---
title: Docker client (docker CLI)
slug: docker-cli
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker client (docker CLI)

The Docker client (docker) is the command-line interface used to interact with Docker Engine. It issues requests to Docker daemons (dockerd) via the Docker Engine API to build, run, manage, and distribute containerized applications. The client is part of the Docker software stack originally authored by Solomon Hykes and developed by Docker, Inc. Docker is written in Go, runs on Linux, Windows, and macOS, and targets multiple CPU architectures (x86-64, ARM, s390x, ppc64le). As of April 20, 2026, the stable release of Docker is 29.4.1. On Linux, Docker Engine (which includes the CLI) is under the Apache-2.0 license; Docker Desktop for Windows and macOS is distributed under an end-user license agreement.

## Role in the Docker architecture

- Docker Engine components:
  - dockerd: long-running daemon managing container objects; listens for requests via the Docker Engine API.
  - docker: CLI client that sends commands to one or more Docker daemons.
- Primary object types the CLI manages:
  - Images: read-only templates used to build containers.
  - Containers: standardized, encapsulated environments that run applications; managed by the API/CLI.
  - Services: swarm-mode abstractions that scale containers across multiple daemons, forming a swarm that coordinates via the Docker API.
- Registries:
  - The CLI connects to registries to pull (download) and push (upload) images.
  - Registries can be public or private; Docker Hub is the default registry the client uses when searching for images.
  - Registries support event-based notifications.

## Platform support and execution model

- Operating systems: Linux, Windows, macOS.
- Architectures: x86-64, ARM, s390x, ppc64le.
- Execution environment (for containers managed via the CLI):
  - Linux: leverages kernel primitives (cgroups and namespaces) and union-capable filesystems (e.g., OverlayFS) for isolation and layering.
  - macOS: runs containers inside a Linux virtual machine; CLI usage is unchanged.
  - Windows: Docker client role is natively supported; broader Windows support evolved with Windows 10 and WSL2.

## Adoption and compatibility milestones relevant to the CLI

- Oct 15, 2014: Microsoft announced native support for the Docker client role in Windows and integration of the Docker engine into Windows Server.
- Jun 8, 2016: Microsoft announced Docker could be used natively on Windows 10.
- May 6, 2019: WSL2 announced; Docker began work to run on WSL2, enabling use on Windows 10 Home (previously Pro/Enterprise via Hyper‑V).
- Aug 2020: WSL2 backported to Windows 10 versions 1903/1909; Docker availability followed.
- Aug 2021: Docker Desktop for Windows and macOS ceased to be free for many enterprise users; a Personal plan replaced the previous Free plan. Docker Engine on Linux remained unaffected.

## Working with images via the CLI

Images are immutable layers used to create containers. The docker CLI builds images from Dockerfiles, lists images, and pushes/pulls images to/from registries.

- Pull an image from the default registry (Docker Hub):
  ```
  docker pull ubuntu:latest
  ```
- List local images:
  ```
  docker images
  ```
- Push an image to a registry:
  ```
  docker push myrepo/myimage:tag
  ```

## Building images with Dockerfile

A Dockerfile defines how an image is constructed. The CLI processes it with docker build.

Example Dockerfile from the source:
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

- Build an image from the Dockerfile in the current directory:
  ```
  docker build -t myapp:${CODE_VERSION:-latest} .
  ```

Notes:
- EXPOSE documents that the container listens on port 22; actual host-to-container port publishing is configured at run time.
- VOLUME declares a mount point; volumes can also be specified at run time.

## Running and managing containers via the CLI

The docker CLI creates and controls containers from images.

- Run a container interactively and remove it when it exits:
  ```
  docker run --rm -it ubuntu:latest bash
  ```
- Run with volume and port mapping aligned with the Dockerfile’s intent:
  ```
  docker run -d --name myapp \
    -v mydata:/myvolume \
    -p 2222:22 \
    myapp:latest
  ```
- List and inspect containers:
  ```
  docker ps
  docker ps -a
  docker logs myapp
  docker inspect myapp
  ```
- Stop and remove:
  ```
  docker stop myapp
  docker rm myapp
  ```

Because containers share a single OS kernel, they are lightweight compared to virtual machines, enabling multiple containers per host.

## Services and swarm (scaling with the CLI)

A service abstracts a set of replicated containers that can be distributed across multiple Docker daemons; together these daemons form a swarm that coordinates via the Docker API. The docker CLI manages service lifecycle and scaling operations in swarm mode.

## Registries and Docker Hub

- Default registry: Docker Hub (used when no explicit registry is specified).
- Operations:
  - Authenticate (when required by a private registry).
  - Pull images for local use.
  - Push locally built images for distribution.
- Registries can emit notifications based on repository events (e.g., image push), enabling automation.

## Docker Compose integration (docker compose CLI utility)

Docker Compose defines and runs multi-container applications using a YAML file (docker-compose.yml). The docker compose CLI utility operates multiple containers at once, including:

- Building images defined in the compose file.
- Creating and starting services with a single command.
- Scaling containers (replicas) for services.
- Restarting previously stopped containers.

Compose configuration highlights:
- build: options such as Dockerfile path.
- command: override default container command.

Example commands:
```
docker compose up -d
docker compose down
docker compose build
```

## Licensing and distribution

- Engine (Linux): Apache-2.0 license.
- Docker Desktop (Windows/macOS): distributed under an EULA; as of Aug 2021, Desktop is not free for many enterprise uses, with a Personal plan available for individual/small-scale use. The Linux Engine/CLI remains unaffected by these Desktop licensing terms.

## Version and implementation

- Language: Go.
- Stable release: 29.4.1 (April 20, 2026).

## Key Points

- The docker CLI is the user-facing interface to Docker Engine, issuing commands to dockerd over the Docker Engine API to manage images, containers, services, and registries.
- Docker Hub is the default registry; the CLI pulls and pushes images and works with public or private registries that can generate event notifications.
- On Linux, Docker uses kernel features (cgroups, namespaces, union filesystems) for isolation; on macOS it runs containers in a Linux VM, with a consistent CLI across platforms.
- Docker Compose is accessed via the docker compose CLI utility to define and run multi-container applications from a docker-compose.yml file, including building and scaling services.
- Docker Engine (including the CLI) is open source on Linux (Apache-2.0), while Docker Desktop for Windows/macOS is under an EULA and has distinct licensing terms for enterprises.