---
title: Container (software)
slug: container
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Container (software)

A software container is an OS-level virtualization construct that encapsulates an application together with its runtime dependencies (binaries, libraries, configuration) into an isolated, standardized execution environment. Containers share the services of a single operating system kernel, which makes them significantly more resource-efficient than full virtual machines, while providing process, filesystem, network, and user namespace isolation. Modern container platforms automate packaging, distribution, and lifecycle management so applications run consistently across diverse environments (on-premises, public cloud, private cloud, and developer workstations).

While multiple implementations exist, Docker is a widely adopted container platform and reference implementation for many container workflows.

## Architecture and isolation

- OS-level virtualization:
  - Containers run as isolated processes on a host OS kernel; there is no guest kernel per container.
  - Isolation primitives (Linux):
    - Namespaces: isolate an application’s view of process trees (PID), networking (net), user IDs (user), and mounted filesystems (mount), among others.
    - Control groups (cgroups): enforce resource limits and accounting (e.g., memory and CPU).
  - Storage: union-capable filesystems (e.g., OverlayFS) provide layered, copy-on-write images and efficient container filesystems.
- Platform behavior:
  - Linux: containers directly use kernel isolation and cgroups.
  - macOS: container platforms run a Linux virtual machine to host containers.
  - Windows: integration exists for Windows Server and developer workflows (e.g., via WSL 2), enabling Docker-based containerization on Windows hosts.
- Communication: containers are isolated from one another, but can communicate over well-defined channels (e.g., virtual networks, published ports, IPC) as configured by the platform.

## Runtime, engine, and execution drivers

Container platforms expose a high-level API and CLI to create, start, stop, and manage containers and related objects.

- Docker Engine:
  - Core daemon (dockerd) manages container objects and listens for requests via the Docker Engine API.
  - Client (docker) provides a CLI to interact with the daemon locally or remotely.
  - Written in Go; supports Linux, Windows, and macOS hosts; CPU architectures include x86-64, ARM, s390x, and ppc64le.
  - Licensing: Docker Engine for Linux is under the Apache-2.0 license; Docker Desktop is distributed under an end-user license agreement, with free and paid tiers.
- Execution environment evolution (Linux):
  - Initial releases used LXC as the default container execution environment.
  - Since Docker 0.9, libcontainer (in Go) interfaces directly with Linux kernel facilities.
  - Other supported/related interfaces include libvirt and systemd-nspawn.
- Distribution: Docker was first released in March 2013 and continues active development (e.g., stable release 29.4.1 on 2026-04-20).

## Core objects and lifecycle

- Image:
  - A read-only, layered template that defines a filesystem and metadata for containers.
  - Built from a specification (e.g., a Dockerfile), stored in registries, and used to instantiate containers.
- Container:
  - A runtime instance of an image with a writable layer and configured isolation, networking, and resource limits.
  - Managed via the Engine API or CLI.
- Service and swarm:
  - A service defines desired state for replicated containers across multiple daemons.
  - A swarm is a set of cooperating daemons (nodes) that coordinate via the Docker API for scaling and orchestration.

## Image distribution and registries

- Registry:
  - Repository for container images supporting push (upload) and pull (download) operations.
  - Can be public or private; Docker Hub is the default public registry for Docker clients.
  - Registries can emit event-based notifications for automation (e.g., CI/CD triggers).
- Typical workflow:
  - Build image from Dockerfile → tag → push to registry → pull on target hosts → run as containers.

## Building images (Dockerfile)

A Dockerfile declares how to construct an image, including base OS, dependency installation, environment variables, copies, exposed ports, and declared volumes.

Example:

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

## Multi-container applications (Compose)

- Docker Compose:
  - A tool to define and run multi-container applications using YAML manifests.
  - The docker compose CLI can build images, scale services, start/stop groups of containers, and manage multi-service lifecycles with a single command.
  - Compose targets multi-container coordination; per-container interactive options or image-manipulation commands outside this scope are not part of Compose’s responsibilities.
  - Common options:
    - build: configure build context and Dockerfile path.
    - command: override the image’s default command.

## Deployment environments and usage characteristics

- Environments: containers can run on on-premises servers, distributed systems, and public/private clouds.
- Hardware footprint: containers are lightweight; many can run concurrently on a single server or VM.
  - Observed density (2018 analysis): typical deployments run ~8 containers per host; ~25% of organizations run 18 or more containers per host.
- Edge/embedded: container engines can run on small devices such as the Raspberry Pi.

## Ecosystem and adoption highlights

- 2013:
  - Public debut at PyCon; released as open source (initially using LXC).
  - Red Hat collaboration around Fedora, RHEL, and OpenShift (Sep 19).
- 2014:
  - Microsoft announced Docker Engine integration into Windows Server and native Docker client support on Windows (Oct 15).
  - Amazon EC2 announced Docker container services (Nov).
  - Partnership announcements: Stratoscale (Nov 10) and IBM Cloud integration (Dec 4).
- 2015:
  - Multi-vendor effort toward a vendor- and OS-independent container standard (Jun 22).
- 2015–2016:
  - Oracle Cloud added Docker container support after acquiring StackEngine (Dec 2015).
  - Docker for Mac and Windows betas (Mar–Apr 2016).
  - Windocks released a port of Docker’s open-source project to Windows Server 2012 R2/2016 with SQL Server 2008+ (Apr 2016).
  - Contributor landscape included teams from Docker, Cisco, Google, Huawei, IBM, Microsoft, and Red Hat (May 2016).
  - Microsoft announced native Docker use on Windows 10 (Jun 8, 2016).
- 2017:
  - Docker created the Moby project for open research and development.
- 2019–2020:
  - Windows Subsystem for Linux 2 (WSL 2) announced; Docker for Windows adapted to run atop WSL 2, enabling Windows 10 Home support.
  - WSL 2 backported to Windows 10 1903/1909; Docker availability followed.
- 2021:
  - Docker Desktop for Windows/macOS licensing changed: no longer free for enterprise users; Free Plan replaced by Personal Plan (Docker Engine on Linux unaffected).
- 2023:
  - Docker acquired AtomicJar to expand testing capabilities.
- 2026:
  - Communications of the ACM featured Docker in a decade retrospective (Mar).

## Security and isolation semantics

- Namespace isolation limits visibility and access to:
  - Process IDs and trees
  - Network interfaces and addressing
  - User and group IDs
  - Mounted filesystems
- Resource governance:
  - cgroups constrain CPU and memory consumption per container.
- Communication:
  - Cross-container and external communications are explicitly configured via networking constructs and published interfaces.

## Licensing and distribution (Docker reference)

- Docker Engine (Linux): Apache-2.0 license.
- Docker Desktop: distributed under an end-user license agreement; offered in free and paid tiers, with enterprise-use restrictions for the free tier as of 2021.
- Active development and releases continue (e.g., 29.4.1 on 2026-04-20).

## Key Points

- Containers provide OS-level virtualization: isolated processes sharing a single kernel, offering higher efficiency than VMs.
- Linux containers rely on namespaces, cgroups, and union filesystems (e.g., OverlayFS); macOS hosts run containers within a Linux VM; Windows integrates via Windows Server and WSL 2.
- Docker popularized the model with an Engine (dockerd), CLI (docker), images, registries (Docker Hub), services/swarm, and Compose for multi-container apps.
- Images are built from Dockerfiles, distributed via registries, and instantiated as containers; registries support event-driven automation.
- Typical deployments achieve high density (multiple containers per host) and run consistently across on-prem, cloud, and even small devices like Raspberry Pi.