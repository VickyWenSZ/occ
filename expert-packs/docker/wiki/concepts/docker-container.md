---
title: Docker container
slug: docker-container
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker container

A Docker container is a standardized, encapsulated runtime environment for applications, delivered via OS-level virtualization. Containers package application processes together with their user-space dependencies (software, libraries, configuration) while sharing the host operating system kernel. Docker automates building, distributing, and running these containers so that applications execute consistently across Linux, Windows, and macOS, in on-premises or public/private cloud environments.

## Concept and Scope

- Type: OS-level virtualization (containers share a single OS kernel; lower overhead than full VMs).
- Isolation: Process, filesystem, network, and user identity isolation via Linux kernel namespaces; resource controls (CPU, memory) via cgroups.
- Portability: Applications and dependencies are packaged into images that run as containers on any host with a compatible Docker Engine (Linux natively; macOS via a Linux VM; Windows with native integration/WSL2).
- Efficiency: Containers are lightweight; a single host can run many containers concurrently. A 2018 analysis observed a typical eight containers per host, with ~25% of organizations running 18+ per host.

## Architecture and Isolation

- Kernel primitives (Linux):
  - Namespaces: isolate process trees (PID), mount points (mnt), networking (net), user IDs (user), etc., constraining an application’s view.
  - cgroups: enforce resource limits/quotas for CPU and memory.
  - Union-capable filesystems: layered image/overlay mechanisms (e.g., OverlayFS) provide copy-on-write container filesystems.
- Runtime backends:
  - Initially used LXC; since v0.9, Docker includes libcontainer (Go), interfacing directly with kernel facilities.
  - Supports abstracted interfaces such as libvirt, LXC, and systemd-nspawn in addition to libcontainer.
- macOS: containers run inside a Linux virtual machine managed by Docker.
- Windows: native engine integration on Windows Server and client support; extensive compatibility via WSL2 on Windows 10/11.

## Components and Objects

- Software:
  - dockerd (daemon): persistent process managing images, containers, networks, and volumes; exposes the Docker Engine API and handles requests.
  - docker (CLI): client that communicates with dockerd to build, run, and manage objects.
- Objects:
  - Image: read-only, layered template containing the filesystem and metadata to create containers; primary unit for packaging/shipping apps.
  - Container: a runnable, isolated instance created from an image; lifecycle is controlled via the Docker API/CLI.
  - Service: a higher-level definition enabling scaling across multiple Docker daemons; services form a swarm, i.e., cooperating daemons communicating via the Docker API.

## Registries and Distribution

- Registry: repository for storing and distributing images; supports push (upload) and pull (download).
  - Public or private; Docker Hub is the default public registry used by Docker clients.
  - Registries can emit notifications based on events (e.g., image push).

## Images and Build (Dockerfile)

- Dockerfile: declarative build script specifying base images, environment, dependencies, and commands. Typical directives include FROM, RUN, COPY/ADD, ENV, EXPOSE, VOLUME, and ARG.
- Example Dockerfile from source:

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

## Multi-Container Applications (Docker Compose)

- Compose: YAML-based tool to define and run multi-container applications.
  - The docker compose CLI can coordinate operations across services: build images, scale containers, start/stop groups of containers, etc.
  - docker-compose.yml options include:
    - build: controls build context and Dockerfile path.
    - command: overrides an image’s default command.
  - Image-manipulation and interactive, single-container options are generally out of scope for Compose workflows.

## Platforms and Deployment

- Operating systems: Linux, Windows, macOS.
- Architectures: x86-64, ARM, s390x, ppc64le.
- Environments: on-premises systems, public cloud, and private cloud.
- Edge/embedded: installable on single-board computers like Raspberry Pi.
- Windows specifics:
  - Native engine support on Windows Server and Windows 10 (announced in 2014–2016).
  - WSL2-based Docker on Windows enables use on Windows 10 Home; backported WSL2 support to Windows 10 versions 1903/1909 expanded availability.

## History and Adoption (Context)

- Origins: Began as an internal project at dotCloud (PaaS), founded by Kamel Founadi, Solomon Hykes, and Sebastien Pahl (YC S2010); open-sourced March 2013; public debut at PyCon 2013; company renamed Docker, Inc. in 2013.
- Runtime evolution: Default from LXC to libcontainer in v0.9 (Go-based).
- Moby project: Launched 2017 for open research and development.
- Recognition: Featured as the cover article in Communications of the ACM (March 2026 retrospective).
- Ecosystem/adoption milestones:
  - 2013–2015: Collaborations with Red Hat (Fedora/RHEL/OpenShift), Microsoft (Windows Server engine integration and Windows client), AWS EC2 container services, IBM Cloud integration; industry effort toward a vendor/OS-independent container standard.
  - 2015: Oracle Cloud added support after acquiring StackEngine.
  - 2016: Docker for Mac/Windows betas; Windocks ported the open-source project to Windows Server 2012 R2/2016 with SQL Server support; Microsoft announced native use on Windows 10.
  - 2017: Significant workforce adoption growth noted via LinkedIn mentions.
  - 2019–2020: WSL2 announced and backported, enabling broader Windows 10 support; Docker availability followed.
  - 2021: Docker Desktop licensing change—no longer free for enterprise use; Personal Plan introduced; Linux Docker Engine unaffected.
  - 2023: Docker acquired AtomicJar to strengthen testing capabilities.

## Licensing and Release

- Engine (Linux): Apache-2.0 licensed.
- Docker Desktop (Windows/macOS): distributed under an end-user license agreement (EULA); tiers include free and paid plans with differing entitlements.
- Implementation language: Go.
- Stable release (from source): 29.4.1 (20 April 2026).

## Operational Characteristics

- High-level API: Docker exposes abstractions for building, distributing, and running isolated processes.
- Resource efficiency: Avoids VM boot overhead; containers start quickly and share the host kernel.
- Communication: Containers interact via defined channels (e.g., networks, ports, volumes); still isolated by namespaces/cgroups.

## Related Tools and Projects

- Swarm mode: enables service deployment and scaling across multiple daemons (a “swarm”).
- Alternative interfaces: In addition to libcontainer, Docker has supported libvirt, LXC, and systemd-nspawn to access kernel virtualization facilities.

## Key Points

- Docker containers are lightweight, kernel-sharing environments that isolate processes via namespaces and cgroups, with layered filesystems (e.g., OverlayFS).
- Docker’s core components are dockerd (daemon/API) and docker (CLI); primary objects are images, containers, and services (for swarm-based scaling).
- Images are built from Dockerfiles; distribution occurs via registries (Docker Hub by default), which can emit event notifications.
- Compose defines multi-container applications in YAML, coordinating build, scale, and lifecycle across services.
- Cross-platform support includes Linux (native), macOS (via a Linux VM), and Windows (native/WSL2), with demonstrated high container density per host.