---
title: Docker Engine
slug: docker-engine
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker Engine

Docker Engine is the core runtime and management software that creates, runs, and orchestrates OCI-style containers using operating system-level virtualization. It automates packaging and deployment of applications into lightweight, isolated containers that run consistently across environments.

- Original author: Solomon Hykes
- Developer: Docker, Inc.
- Initial release: 2013-03-20
- Stable release: 29.4.1 (2026-04-20)
- Written in: Go
- Operating systems: Linux, Windows, macOS
- CPU architectures: x86-64, ARM, s390x, ppc64le
- Type: OS-level virtualization
- Licenses:
  - Docker Engine (Linux): Apache-2.0
  - Docker Desktop (macOS/Windows packaging and UX): End-user license agreement (EULA)
- Website: https://www.docker.com
- Repository: https://github.com/docker

## Overview

Docker Engine provides:
- A high-level API and CLI to build images, run containers, and manage services.
- Process, filesystem, and network isolation via Linux kernel primitives (namespaces, cgroups) and a union-capable filesystem (e.g., OverlayFS).
- Cross-environment portability of applications by bundling dependencies, libraries, and configuration within images that produce standardized containerized runtime environments.

Containers share the host OS kernel (reducing overhead relative to virtual machines) while maintaining isolation. Containers can communicate over well-defined channels (e.g., container networking). On macOS (and often Windows), Docker Engine runs Linux containers inside a lightweight Linux virtual machine for compatibility.

## Architecture and Design

- Kernel interfaces:
  - Namespaces: isolate process trees, network, UIDs, mount points, etc.
  - cgroups: enforce CPU and memory resource limits/quotas.
  - Union-capable filesystems: layered image and container filesystems (e.g., OverlayFS).
- Execution drivers:
  - Early releases used LXC as the default execution environment.
  - Since v0.9, Docker introduced libcontainer (written in Go) to interface directly with kernel features.
  - Engine can also use abstracted interfaces (libvirt, LXC, systemd-nspawn) as alternatives.
- Engine process model:
  - dockerd (daemon) manages images, containers, networks, and volumes; exposes the Docker Engine API.
  - docker (CLI) is a client that issues Engine API requests to one or more daemons.
- Performance and density:
  - Containers are lightweight; multiple containers can run per host.
  - A 2018 analysis reported a typical deployment of ~8 containers per host; 25% of organizations ran 18+ per host.

## Components

- Daemon (dockerd):
  - Persistent background service.
  - Listens on local or remote sockets/ports for Docker Engine API requests.
  - Creates, runs, stops, and manages objects (images, containers, networks, volumes, services).
- Client (docker):
  - Command-line interface for building images, pushing/pulling to registries, running containers, managing resources, and orchestrating services.
- Engine API:
  - High-level HTTP API controlling lifecycle and state of Docker objects and swarms.

### Core Objects

- Images:
  - Read-only, layered templates that capture application binaries, dependencies, and configuration.
  - Built from a Dockerfile; distributed via registries; immutable once published.
- Containers:
  - Runtime instances of images with an added writable layer and isolated namespaces/cgroups.
  - Managed via CLI or Engine API (create, start, exec, stop, logs, inspect).
- Services:
  - Declarative scaling and placement of containers across multiple daemons.
  - Cooperating daemons form a swarm that communicates via the Docker API.

### Registries

- Role: Store and distribute images; clients pull to run and push to publish.
- Modes: Public or private.
- Docker Hub: Default public registry used by Docker Engine.
- Features: Event-driven notifications (e.g., on push, tag, or delete) for integration workflows.

## Dockerfiles

A Dockerfile declares how to build an image, including base OS, application dependencies, configuration, and metadata. Example from source:

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

Common instructions include FROM, RUN, COPY/ADD, ENV, EXPOSE, VOLUME, ARG, CMD/ENTRYPOINT, WORKDIR, and LABEL.

## Docker Compose

- Purpose: Define and run multi-container applications.
- Format: YAML configuration (docker-compose.yml) declaring services, networks, and volumes.
- CLI: docker compose facilitates multi-service builds, starts, stops, scaling, and lifecycle management with single commands.
- Notes:
  - Image-manipulation and interactive single-container options are not relevant within Compose’s multi-service context.
  - Key options include build (e.g., Dockerfile path and args) and command (override default container command).

## Platforms and OS Support

- Linux:
  - Native kernel primitives (namespaces, cgroups, OverlayFS).
  - Engine is Apache-2.0 licensed on Linux.
- macOS:
  - Uses a Linux virtual machine to host containers (since macOS lacks Linux kernel features).
- Windows:
  - Microsoft integrated Docker Engine into Windows Server and added native Docker client support in Windows.
  - Windows 10 gained native usability for Docker (2016); later, WSL 2 (2019) enabled Docker on Windows 10 Home, removing Hyper-V Pro/Enterprise limitations.
  - WSL 2 backported to Windows 10 versions 1903/1909 in 2020; Docker became available on those versions.
- Single-board computers:
  - Installable on devices such as Raspberry Pi (ARM).

## Licensing and Distribution

- Docker Engine (Linux): Apache-2.0.
- Docker Desktop (macOS/Windows distribution and UX):
  - Distributed under an EULA.
  - As of August 2021, Docker Desktop for Windows and macOS ceased to be free for enterprise users; a Personal Plan replaced the Free Plan for individuals/small businesses.
  - Docker Engine on Linux distributions remained unaffected by these Desktop licensing changes.

## History and Adoption Milestones

- 2010–2013:
  - dotCloud (PaaS) incubates Docker; company founded by Kamel Founadi, Solomon Hykes, and Sebastien Pahl (YC S10); rebrands to Docker, Inc. in 2013.
  - Public debut at PyCon 2013; open-sourced March 2013; initial runtime used LXC.
  - v0.9 (2014): Docker switches default from LXC to libcontainer (Go).
- 2014–2016 ecosystem growth:
  - 2013-09-19: Collaboration with Red Hat (Fedora, RHEL, OpenShift).
  - 2014-10-15: Microsoft announces Windows Server integration and native Docker client support on Windows.
  - 2014-11: Docker container services arrive on Amazon EC2.
  - 2014-11-10: Partnership with Stratoscale.
  - 2014-12-04: IBM strategic partnership enabling tighter IBM Cloud integration.
  - 2015-06-22: Industry collaboration launched on a vendor/OS-independent container standard.
  - 2015-12: Oracle Cloud adds Docker support after acquiring StackEngine.
  - 2016-03: Docker for Mac and Windows betas released.
  - 2016-04: Windocks releases a Windows port supporting Server 2012 R2/2016 and SQL Server 2008+.
  - 2016-05: Major contributors include Docker, Cisco, Google, Huawei, IBM, Microsoft, Red Hat.
  - 2016-06-08: Native usability on Windows 10 announced by Microsoft.
- 2017–2026:
  - 2017: Docker creates the Moby project for open R&D.
  - 2017: LinkedIn data shows 160% growth in Docker mentions (2016 YoY).
  - 2019-05-06: Microsoft announces WSL 2; Docker begins work to run on WSL 2 (enabling Windows 10 Home).
  - 2020-08: WSL 2 backported to Windows 10 1903/1909; Docker available on these platforms.
  - 2021-08: Docker Desktop licensing changes for enterprise users; Linux Engine unaffected.
  - 2023-12: Docker acquires AtomicJar to expand testing capabilities.
  - 2026-03: Communications of the ACM features Docker in a retrospective cover article.

## Swarm and Multi-Daemon Operation

- Services define desired state (replicas, image, command).
- Multiple daemons coordinate as a swarm, communicating via the Engine API to schedule containers, scale services, and achieve high availability across hosts.

## Usage Patterns

- Typical deployments run multiple containers per host to maximize resource utilization.
- Containers package complete application stacks for deployment on-premises or in public/private clouds.
- Registries (Docker Hub by default) provide centralized image distribution, with event notifications for CI/CD pipelines.

## Key Points

- Docker Engine is the core, Go-based container runtime and management layer providing a high-level API, daemon (dockerd), and CLI (docker).
- It relies on Linux kernel primitives (namespaces, cgroups, union filesystems like OverlayFS) and since v0.9 uses libcontainer by default.
- Images, containers, and services are primary objects; services scale containers across daemons into a swarm.
- Runs natively on Linux; on macOS and Windows, containers run via a Linux VM or WSL 2; Docker Hub is the default image registry.
- Licensing: Engine (Linux) under Apache-2.0; Docker Desktop under an EULA, with post-2021 changes affecting enterprise Desktop usage (Engine on Linux unaffected).