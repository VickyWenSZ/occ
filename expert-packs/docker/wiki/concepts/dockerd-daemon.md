---
title: Docker daemon (dockerd)
slug: dockerd-daemon
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker daemon (dockerd)

The Docker daemon (dockerd) is the persistent background process of Docker Engine that manages container lifecycle and other Docker objects, and exposes the Docker Engine API that clients use to interact with Docker. It is written in Go and is a core component of Docker’s OS-level virtualization platform, running on Linux, Windows, and macOS across multiple CPU architectures. Dockerd orchestrates container operations using kernel isolation and filesystem layering features on Linux, and it interoperates with tooling such as the docker CLI, Docker Compose, and image registries.

- Original author: Solomon Hykes
- Developer: Docker, Inc.
- Initial release: 2013-03-20
- Stable release (Docker): 29.4.1 (2026-04-20)
- Written in: Go
- Operating systems: Linux, Windows, macOS
- Platforms: x86-64, ARM, s390x, ppc64le
- License: Apache-2.0 (Docker Engine, for Linux only); Docker Desktop governed by an end-user license agreement

## Role in the Docker architecture

Dockerd is the server-side of Docker Engine:

- Persistent daemon process that:
  - Manages Docker objects: images, containers, services.
  - Handles container lifecycle (create, start, stop), image storage/retrieval, and service orchestration across daemons.
- Exposes the Docker Engine API (daemon listens for requests sent via this API).
- Interacts with:
  - docker (CLI): the client program that issues commands to one or more Docker daemons via the API.
  - Registries: for pulling and pushing images.
  - Other daemons: to form a swarm when services are scaled across multiple hosts.

## Objects managed by dockerd

Dockerd manages the primary Docker object types:

- Images: read-only templates used to build containers; store and ship applications.
- Containers: standardized, encapsulated environments that run application processes.
- Services: definitions that allow containers to be scaled across multiple Docker daemons; the cooperating set of daemons forms a swarm communicating via the Docker API.

Dockerd’s object model underpins the workflows of image build/pull/push, container run/stop, and service scale/update.

## API and client interaction

- Docker Engine API: high-level API implemented by dockerd to provide lightweight container execution with process isolation.
- docker CLI: issues commands (e.g., container and image operations) to dockerd over the Engine API.
- Swarm communication: multiple dockerd instances cooperate for services via the same API surface.

## Execution model and kernel integration (Linux)

On Linux, dockerd uses kernel facilities to isolate and constrain workloads and to provide efficient filesystem layering:

- Isolation: kernel namespaces (process trees, network, user IDs, mounted filesystems) isolate each container’s view of the system.
- Resource control: cgroups limit CPU and memory usage for containers.
- Filesystem layering: union-capable filesystems (e.g., OverlayFS) provide image layering and copy-on-write efficiency.
- Virtualization interface evolution:
  - Initially used LXC as the default execution environment.
  - Since version 0.9, includes libcontainer (written in Go) to use kernel features directly.
  - Can also use abstracted interfaces via libvirt, LXC, and systemd-nspawn.

Because containers share a single OS kernel, dockerd can run many lightweight containers per host, avoiding the overhead of full virtual machines. Empirical analysis (2018) found typical deployments running ~8 containers per host, with a quarter of organizations running 18 or more per host.

## Platform behavior (Windows and macOS)

- Windows:
  - Microsoft integrated Docker Engine into Windows Server and added native Docker client support in Windows.
  - Docker can be used natively on Windows 10; WSL 2 enabled broader Windows 10 Home support.
  - WSL 2 backported to Windows 10 versions 1903 and 1909; Docker made available on these platforms.
- macOS:
  - Docker uses a Linux virtual machine to run containers, with dockerd and containers operating inside that VM while remaining accessible from macOS.

## Registries and image distribution

Dockerd participates in image distribution workflows:

- Registries: repositories for Docker images (public or private).
  - Docker clients connect to registries to pull images for use or push images they have built.
  - Docker Hub is the main public registry and the default registry where Docker looks for images.
  - Registries can emit notifications based on events.

## Compose and multi-container workflows

While dockerd manages the underlying objects, Docker Compose defines and coordinates multi-container applications:

- Compose uses YAML files to configure services, and starts all containers with a single command.
- The docker compose CLI runs commands across multiple containers (e.g., build images, scale containers, start/stop).
- Compose focuses on multi-container orchestration; commands tied to single-container interactive behavior or individual image manipulation are not the focus in Compose.
- docker-compose.yml options include:
  - build: configuration such as the Dockerfile path.
  - command: override default container commands.

## Example: Dockerfile managed by dockerd

Dockerd builds and runs images defined by Dockerfiles. Example (from the source):

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

## Adoption and ecosystem context

- Industry collaborations and platform integrations expanded dockerd’s reach:
  - Red Hat (Fedora, RHEL, OpenShift)
  - Microsoft (Windows Server integration, Windows 10 native use)
  - Amazon EC2 container services
  - IBM Cloud strategic partnership
  - Oracle Cloud support (via StackEngine acquisition)
- Tooling and project evolution:
  - Docker for Mac and Windows betas (2016).
  - Moby project (2017) for open R&D related to Docker technologies.
- Distribution and licensing:
  - Docker Desktop licensing changes (Aug 2021): no longer free of charge for enterprise users; Docker Engine on Linux remained unaffected.
  - Docker acquired AtomicJar (Dec 2023) to expand testing capabilities.
- Recognition: Communications of the ACM featured Docker in a 2026 retrospective cover article.

## Key Points

- Dockerd is the persistent Docker Engine daemon that manages images, containers, and services, and exposes the Docker Engine API.
- On Linux, dockerd leverages namespaces, cgroups, and union filesystems (e.g., OverlayFS); since 0.9 it uses libcontainer for direct kernel integration.
- Images are pulled/pushed via registries (Docker Hub by default); services scale containers across multiple daemons to form a swarm.
- Docker runs on Linux, Windows, and macOS (macOS uses a Linux VM); wide platform and architecture support includes x86-64, ARM, s390x, and ppc64le.
- Docker Engine is written in Go and licensed under Apache-2.0 on Linux; Docker Desktop is covered by an end-user license agreement.