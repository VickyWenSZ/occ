---
title: OS-level virtualization (containerization)
slug: os-level-virtualization
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# OS-level virtualization (containerization)

OS-level virtualization (containerization) is a method for running applications in isolated user-space environments (containers) that share a single operating system kernel. Containers encapsulate software, its libraries, and configuration, while leveraging kernel primitives for isolation and resource control. Compared to hardware virtualization (virtual machines), containers avoid booting full guest OS instances, reducing overhead and enabling higher density and faster startup.

Docker is a widely used implementation that automates building, distributing, and running containerized applications via Docker Engine and associated tooling. It provides a high-level API and CLI for managing images, containers, and multi-node services.

## Core properties

- Single-kernel, multi-tenant execution: all containers on a host share one OS kernel, drastically reducing memory and CPU overhead versus VMs.
- Process, filesystem, and network isolation: primarily via Linux namespaces (process tree, network stack, user IDs, mounts) and cgroups for CPU/memory limits.
- Layered, union-capable filesystems: image and container filesystems built from layered snapshots (e.g., OverlayFS), enabling copy-on-write efficiency.
- Deterministic packaging and deployment: images bundle application code and dependencies for consistent execution across environments (on-premises, public/private clouds).
- Lightweight and scalable: a single server or VM can run many containers concurrently; empirical analyses reported typical deployments running multiple containers per host.

## Kernel primitives and execution environment

- Namespaces (Linux): mostly isolate application views of system resources:
  - pid: process trees
  - net: network interfaces, routing, ports
  - user: user and group IDs
  - mount: mounted filesystems
- cgroups (Linux): limit and account resources, including memory and CPU.
- Union-capable filesystems: OverlayFS commonly used for image layering and container copy-on-write semantics.
- Execution backends/interfaces:
  - Early Docker used LXC; since Docker 0.9, libcontainer (written in Go) directly uses Linux kernel facilities.
  - Integrations exist via libvirt, LXC, and systemd-nspawn.
- Non-Linux hosts:
  - macOS: uses a Linux virtual machine to host containers.
  - Windows: integration of the Docker engine with Windows Server, and later support via Windows Subsystem for Linux 2 (WSL 2) on client editions.

## Architecture (Docker-based)

- Docker Engine:
  - dockerd: persistent daemon managing images, containers, networks, and volumes; exposes the Docker Engine API.
  - docker: CLI client interacting with the daemon/API.
  - High-level API provides lifecycle operations to build, run, and manage isolated processes.
- Objects:
  - Image: read-only, layered template for building containers; used to store and ship applications.
  - Container: runnable, isolated environment instantiated from an image; lifecycle controlled via API/CLI.
  - Service: definition for scaling containers across multiple daemons; forms a swarm (cooperating daemons communicating via the Docker API).
- Registries:
  - Repositories for images; support push (upload) and pull (download).
  - Public or private; Docker Hub is the default public registry.
  - Event notifications supported for registry actions.

## Packaging and build (images)

Images are defined by declarative build files that encode base OS, dependency installation, configuration, and runtime settings. Example Dockerfile:

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

## Multi-container composition

- Docker Compose:
  - YAML-based configuration to define and run multi-container applications.
  - The docker compose CLI orchestrates build, startup, scaling, and other bulk operations across defined services.
  - Per-container interactive/image-manipulation commands are generally out-of-scope for Compose; configuration focuses on service definitions (e.g., build options including Dockerfile path, command overrides).

## Platform support and performance characteristics

- Operating systems: Linux (native), Windows, macOS (via Linux VM).
- CPU architectures: x86-64, ARM, s390x, ppc64le (via Docker tooling).
- Density and efficiency:
  - Containers are lightweight; many can run simultaneously per host.
  - Analyses (2018) observed typical deployments around eight containers per host, with a significant fraction running 18+ per host.
- Form factors: can run on single-board computers such as Raspberry Pi.

## Usage patterns and environments

- Consistent execution across development, testing, and production environments.
- Deployable on-premises and across public/private cloud infrastructure.
- Communication between containers occurs through well-defined channels (e.g., virtual networks), while maintaining isolation of processes, filesystems, and user spaces.

## History and adoption (Docker ecosystem)

- 2010–2013: Originated as an internal project at dotCloud (a PaaS company) founded by Kamel Founadi, Solomon Hykes, and Sebastien Pahl; debuted publicly at PyCon 2013; open-sourced in March 2013; initial runtime based on LXC; moved to libcontainer in 0.9 (Go-based).
- 2013–2016 ecosystem growth:
  - 2013-09-19: Collaboration with Red Hat around Fedora, RHEL, OpenShift.
  - 2014-10-15: Microsoft announced Docker engine integration into Windows Server and native Docker client support on Windows.
  - 2014-11: Container services announced for Amazon EC2.
  - 2014-11-10: Partnership with Stratoscale.
  - 2014-12-04: Strategic partnership with IBM to integrate with IBM Cloud.
  - 2015-06-22: Industry effort toward a vendor- and OS-independent container standard.
  - 2015-12: Oracle Cloud added Docker support after acquiring StackEngine.
  - 2016-03: Docker for Mac and Windows (beta) released.
  - 2016-04: Windocks released a Windows port supporting Windows Server 2012 R2/2016 and SQL Server 2008+.
  - 2016-06-08: Microsoft announced native Docker on Windows 10.
- 2017–2026:
  - 2017: Moby Project established for open R&D.
  - 2017-01: LinkedIn profile analysis indicated 160% year-over-year growth in mentions (2016).
  - 2019-05-06: WSL 2 announced; Docker began work on Windows Docker using WSL 2, enabling Windows 10 Home support (previously required Hyper-V on Pro/Enterprise).
  - 2020-08: WSL 2 backported to Windows 10 versions 1903/1909; Docker support announced for these builds.
  - 2021-08: Docker Desktop for Windows/macOS moved to a paid model for enterprise; a Personal Plan replaced the Free Plan; Docker Engine on Linux remained unaffected.
  - 2023-12: Docker acquired AtomicJar to expand testing capabilities.
  - 2026-03: Communications of the ACM featured Docker in a retrospective cover article.
- Development and licensing:
  - Core software written in Go.
  - Docker Engine (Linux) under Apache-2.0; Docker Desktop distributed under an end-user license agreement.
  - Product tiers include free and paid offerings.
  - Stable Docker Engine release: 29.4.1 (20 April 2026).

## Implementation notes

- Interfaces to Linux virtualization features can vary; Docker can use native kernel interfaces directly (libcontainer) or through abstraction layers (libvirt, LXC, systemd-nspawn).
- Containers communicate via configured interfaces while preserving isolation. Resource policies (cgroups) control CPU/memory to prevent noisy-neighbor effects.
- On macOS, the necessary Linux kernel features are provided by an embedded Linux VM; Windows environments leverage Windows Server integration or WSL 2 to host Linux containers.

## Key Points

- Containers use OS-level virtualization to isolate processes via kernel namespaces and cgroups while sharing a single kernel, yielding lower overhead than VMs.
- Docker operationalizes containerization with a daemon/API, CLI, image/registry model, and multi-container orchestration via services (swarm) and Compose.
- Layered images on union-capable filesystems (e.g., OverlayFS) enable efficient distribution and copy-on-write container filesystems.
- Cross-platform support (Linux, Windows, macOS via a Linux VM) and multi-arch builds allow consistent deployment across environments, from cloud to edge (e.g., Raspberry Pi).
- Industry adoption accelerated through integrations with major vendors and platforms, with continued evolution in tooling, licensing models, and Windows support (WSL 2).