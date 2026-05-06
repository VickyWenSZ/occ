---
title: Docker (software)
slug: docker-software
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker (software)

Docker is a platform for building, shipping, and running applications using operating system–level virtualization (containers). It automates packaging applications and their dependencies into portable, lightweight containers that run consistently across environments. The core runtime and management component is Docker Engine.

- Original author: Solomon Hykes
- Developer: Docker, Inc.
- Initial release: 2013-03-20
- Stable release: 29.4.1 (2026-04-20)
- Written in: Go
- Operating systems: Linux, Windows, macOS
- Architectures: x86-64, ARM, s390x, ppc64le
- Type: OS-level virtualization
- Licenses: Apache-2.0 (Docker Engine for Linux); EULA (Docker Desktop)
- Website: https://www.docker.com
- Repository: https://github.com/docker

## History

- Origins: Began as an internal project at dotCloud (a platform-as-a-service company) founded by Kamel Founadi, Solomon Hykes, and Sebastien Pahl during Y Combinator Summer 2010; dotCloud launched in 2011 and was renamed Docker, Inc. in 2013. Public debut at PyCon 2013 (Santa Clara). Open-sourced March 2013.
- Runtime evolution: Initially used LXC as the default execution environment; with version 0.9 (2014), introduced libcontainer (written in Go) to interface directly with Linux kernel features.
- Open R&D: In 2017, Docker created the Moby project for open research and development.
- Recognition: In March 2026, Communications of the ACM featured Docker in a decade retrospective cover article.

## Adoption timeline

- 2013-09-19: Collaboration announced with Red Hat around Fedora, RHEL, and OpenShift.
- 2014-10-15: Microsoft announced Docker Engine integration with Windows Server and native Docker client support on Windows.
- 2014-11: Docker services announced for Amazon EC2.
- 2014-11-10: Partnership with Stratoscale.
- 2014-12-04: IBM strategic partnership to integrate Docker with IBM Cloud.
- 2015-06-22: Multi-vendor effort announced to create a vendor- and OS-independent container standard.
- 2015-12: Oracle Cloud added Docker container support after acquiring StackEngine.
- 2016-03: Docker for Mac and Docker for Windows betas released.
- 2016-04: Windocks released an independent port of Docker’s open-source project to Windows (Server 2012 R2, 2016) with SQL Server 2008+ support.
- 2016-05: Major contributors identified: Docker team, Cisco, Google, Huawei, IBM, Microsoft, Red Hat.
- 2016-06-08: Native Docker availability on Windows 10 announced by Microsoft.
- 2017-01: LinkedIn profile mentions indicated 160% Docker presence growth in 2016.
- 2019-05-06: Microsoft announced WSL 2; Docker, Inc. began work on Docker for Windows on WSL 2, enabling use on Windows 10 Home (previously Pro/Enterprise via Hyper-V).
- 2020-08: WSL 2 backported to Windows 10 versions 1903/1909; Docker made available for these versions.
- 2021-08: Docker Desktop for Windows/macOS ended free availability for larger enterprises; replaced Free Plan with Personal Plan. Docker Engine on Linux remained unaffected.
- 2023-12: Docker acquired AtomicJar to expand testing capabilities.

## Design and architecture

Docker provides process isolation and resource control via Linux kernel features and, where necessary, virtualization:

- Kernel primitives (Linux):
  - Namespaces: Isolate an application’s view of the system (process trees, networks, user IDs, mounts).
  - cgroups: Limit and account for CPU and memory resources.
  - Union-capable filesystems: OverlayFS (and similar) provide layered, copy-on-write images.
- Execution environment:
  - Linux: Containers run directly on a single Linux kernel instance using namespaces and cgroups; avoids the overhead of full virtual machines.
  - macOS: Runs containers inside a Linux virtual machine.
  - Windows: Platform support and integration provided via Windows Server and, on client systems, WSL 2; enables operation on Windows 10 Home and later backported releases.
- Isolation and efficiency:
  - Containers package binaries, libraries, and configuration, communicating over defined channels.
  - Sharing the host kernel yields lower overhead than virtual machines, enabling higher density. A 2018 analysis reported typical deployments of ~8 containers per host; ~25% ran 18+ per host.
- Portability:
  - Applications and dependencies are packaged to run on Linux, Windows, or macOS and can be deployed on-premises or in public/private clouds.
- Interfaces to kernel/container tech:
  - Docker introduced libcontainer (v0.9+) for direct kernel integration.
  - Can also operate via abstracted interfaces such as libvirt, LXC, and systemd-nspawn.
- API:
  - A high-level Docker Engine API exposes container lifecycle and object management operations.

Docker’s lightweight footprint allows use even on constrained devices such as the Raspberry Pi.

## Components

Docker’s service and tooling can be viewed across software, objects, and registries.

### Software

- dockerd (Docker daemon):
  - Persistent system service that manages containers and higher-level objects (images, networks, volumes, services).
  - Exposes and listens on the Docker Engine API for client/server interactions.
- docker (CLI client):
  - Command-line interface used by operators and automation to interact with one or more Docker daemons via the Engine API.

### Objects

- Image:
  - Read-only, layered template describing a filesystem and metadata to instantiate containers; used to store and distribute applications.
- Container:
  - A runnable instance of an image providing an isolated user space; lifecycle managed via CLI/API (create, start, stop, exec, logs, etc.).
- Service:
  - Defines desired state for scaling containers across multiple Docker daemons; forms a swarm (a cooperating set of daemons communicating via the Engine API) for clustered deployments.

### Registries

- Function:
  - Stores and serves images. Clients pull images for use and push images they build.
- Types:
  - Public or private. Docker Hub is the primary public registry and the default lookup source for images.
- Events:
  - Registries can emit notifications based on repository/image events.

### Dockerfile

A Dockerfile specifies how to build an image: base OS, package/runtime installation, file additions, environment, ports, and volumes. Example:

```Dockerfile
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

## Docker Compose

Docker Compose defines and runs multi-container applications:

- Configuration:
  - Uses YAML (docker-compose.yml) to declare services and related settings.
  - Common options include:
    - build: Configure image build (e.g., Dockerfile path).
    - command: Override default container command.
    - Additional service, network, and volume configuration.
- Orchestration:
  - The docker compose CLI coordinates building, creating, starting, stopping, scaling, and otherwise operating on sets of containers.
- Scope:
  - Compose focuses on multi-container workflows; single-container, image-manipulation, or interactive options are generally managed outside Compose.

## Licensing and distribution

- Docker Engine (Linux): Apache-2.0 licensed.
- Docker Desktop (Windows/macOS): Distributed under an end-user license agreement; as of August 2021, enterprise usage falls under paid plans, with a Personal (free) plan for individual/small-scale use.
- Platform offerings include both free and paid tiers.

## Notable ecosystem integrations

- Red Hat (Fedora, RHEL, OpenShift) collaboration.
- Microsoft Windows Server integration; Windows 10 client support including WSL 2.
- Cloud providers: Amazon EC2 services; IBM Cloud strategic integration; Oracle Cloud support (via StackEngine acquisition).
- Additional partnerships: Stratoscale.
- Contributor ecosystem historically included major vendors (Cisco, Google, Huawei, IBM, Microsoft, Red Hat) alongside Docker.

## Key Points

- Docker provides OS-level virtualization using Linux namespaces, cgroups, and union filesystems, exposing a high-level Engine API.
- Core components include dockerd (daemon), docker (CLI), images, containers, services (swarm), and registries (with Docker Hub as default).
- Cross-platform support spans Linux, Windows, and macOS (the latter via a Linux VM), across x86-64, ARM, s390x, and ppc64le.
- Typical deployments achieve high density due to lightweight containers; portability enables on-premises and cloud use.
- Licensing differs by product: Docker Engine (Apache-2.0) vs. Docker Desktop (EULA) with free and paid tiers.