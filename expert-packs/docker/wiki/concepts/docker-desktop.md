---
title: Docker Desktop
slug: docker-desktop
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker Desktop

Docker Desktop is Docker, Inc.’s end-user distribution for running Docker on developer workstations, primarily targeting Windows and macOS. It packages the Docker Engine (daemon and CLI) with a local virtualization backend and tooling (e.g., Docker Compose), enabling the build, run, and orchestration of containers on non-Linux hosts while exposing the standard Docker Engine API and CLI.

## Overview

- Purpose: Provide a consistent, local container runtime and developer experience on Windows and macOS for building, running, and composing multi-container applications.
- Relation to Docker Engine: Bundles the Docker daemon (dockerd) and Docker CLI (docker), presenting the same Engine API used on Linux.
- Virtualization model: Containers rely on Linux kernel features; thus Docker Desktop supplies or integrates with a Linux environment on non-Linux hosts (Linux VM on macOS; WSL 2 on Windows).
- Licensing: Distributed under a Docker Desktop end-user license agreement (EULA). By contrast, Docker Engine for Linux is under the Apache-2.0 license.
- Tiers: Docker offers both free and paid tiers. As of August 2021, Docker Desktop for Windows and macOS is no longer available free of charge for enterprise users; Docker replaced the Free Plan with a Personal Plan. Docker Engine on Linux distributions remained unaffected.

## Architecture and Runtime Backends

- Linux kernel dependency:
  - Containers use Linux kernel isolation mechanisms (namespaces for process trees, network, user IDs, mounts; cgroups for CPU/memory limits) and a union-capable filesystem (e.g., OverlayFS).
  - Docker implements a high-level API for managing these lightweight, isolated processes.

- macOS:
  - Runs containers inside a Linux virtual machine because macOS does not provide the required Linux kernel features natively.

- Windows:
  - Historical: Early Windows support used Hyper-V, limiting availability to Windows 10 Pro/Enterprise.
  - WSL 2 integration: With Windows Subsystem for Linux 2 (announced May 2019), Docker Desktop runs on Windows 10 Home, since WSL 2 supplies a Linux kernel. In August 2020, Microsoft backported WSL 2 to Windows 10 versions 1903/1909, and Docker developers announced Docker availability for these platforms.

## Components Exposed via Docker Desktop

- Docker daemon (dockerd):
  - Persistent process managing images, containers, and services; listens on the Docker Engine API.
- Docker CLI (docker):
  - Command-line interface to interact with the daemon (build, pull/push, run, logs, etc.).
- Docker objects:
  - Images: read-only templates for application packaging and distribution.
  - Containers: standardized, encapsulated environments that run application processes; managed via CLI or API.
  - Services and swarms: scale containers across multiple daemons (useful knowledge for distributed scenarios; Desktop primarily provides a single-host environment).
- Registries:
  - Repositories for images; can be public or private. Docker Hub is the default public registry used by Docker tools.
  - Registries can emit notifications on events (e.g., image pushes).
- Docker Compose:
  - Tooling to define and run multi-container applications using YAML configuration.
  - The docker compose CLI operates on multiple services together (e.g., build images, scale containers, start/stop groups of services).
  - Compose focuses on multi-container orchestration; single-container, image-manipulation, or interactive commands are generally outside its scope.
  - docker-compose.yml options include, for example:
    - build: configure image build parameters (e.g., Dockerfile path).
    - command: override a container’s default command.

## Development Workflow on Desktop

- Build:
  - Use Dockerfiles to define images. Desktop’s Engine builds images identically to Linux hosts, ensuring environment parity.

- Example Dockerfile (from source):
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

- Run:
  - Start containers via docker run or Docker Compose (docker compose up) to bring up multi-service applications.
  - Desktop leverages the host’s networking/volume integration via its VM (macOS) or WSL 2 (Windows) to provide file sharing and port exposure.

- Ship:
  - Push built images to a registry (e.g., Docker Hub by default) for distribution to other environments (on-premises or cloud).

## Platform Timeline Relevant to Desktop

- March 2016: Public betas of Docker for Mac and Docker for Windows released.
- May 2019: Microsoft announced WSL 2; Docker, Inc. began a Windows version running on WSL 2, enabling Docker on Windows 10 Home (previously limited to Pro/Enterprise due to Hyper-V).
- August 2020: Microsoft backported WSL 2 to Windows 10 versions 1903/1909; Docker availability on these platforms announced.
- August 2021: Licensing change—Docker Desktop for Windows and macOS no longer free for enterprise; Free Plan replaced by Personal Plan (Linux Engine unaffected).

## Licensing

- Docker Desktop: End-user license agreement (EULA).
- Docker Engine (Linux): Apache-2.0 license.
- Impact: Organizations must observe Docker Desktop’s licensing for Windows/macOS usage; Linux Engine usage remains under open-source terms.

## Key Points

- Docker Desktop packages Docker Engine and tooling for Windows and macOS, supplying a Linux runtime via a VM (macOS) or WSL 2 (Windows).
- It exposes the standard Docker Engine API/CLI and supports images, containers, services, registries (Docker Hub by default), and Docker Compose.
- Containers rely on Linux kernel features (namespaces, cgroups, union filesystems); Desktop bridges this requirement on non-Linux hosts.
- As of August 2021, Docker Desktop is not free for enterprise users; Linux Docker Engine licensing is unchanged (Apache-2.0).
- Windows support evolved from Hyper-V to WSL 2, enabling Docker on Windows 10 Home and on backported Windows 10 releases.