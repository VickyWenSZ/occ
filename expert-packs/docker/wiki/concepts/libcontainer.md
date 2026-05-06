---
title: libcontainer
slug: libcontainer
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# libcontainer

libcontainer is Docker’s native component for interfacing directly with Linux kernel containerization features. Introduced in Docker 0.9 (one year after Docker’s initial 2013 release), libcontainer replaced LXC as Docker’s default execution environment and is written in Go. Its role is to create and manage containers by invoking kernel primitives (e.g., namespaces and cgroups) without relying solely on abstracted interfaces such as libvirt, LXC, or systemd-nspawn.

## Overview

- Purpose: Provide direct access to Linux kernel facilities to run processes in isolated, lightweight containers managed by Docker Engine.
- Language: Go.
- Scope: Enables container lifecycle operations by setting up isolation (namespaces), resource control (cgroups), and a union-capable filesystem view within a single Linux kernel instance.
- Relationship to Docker Engine:
  - Docker Engine implements a high-level API for container operations.
  - The dockerd daemon manages container objects and handles requests via the Docker Engine API.
  - libcontainer underpins the low-level, Linux-specific container setup used by dockerd when running on Linux.

## History and Rationale

- Initial execution backend: LXC by default at Docker’s public debut (2013).
- Transition: With Docker 0.9, LXC was replaced by libcontainer to:
  - Reduce dependency on external container managers.
  - Interact directly with kernel features for finer control and portability within Docker’s Go-based codebase.
- Continued interoperability: While libcontainer enables direct kernel use, Docker can also work through abstracted interfaces (libvirt, LXC, systemd-nspawn) when needed.

## Kernel Interfaces and Isolation Primitives

When running on Linux, Docker (via libcontainer) uses:

- Namespaces: Isolate an application’s view of system resources, including:
  - Process trees (PID)
  - Network
  - User IDs
  - Mounted file systems
- Control groups (cgroups): Enforce resource limits and accounting, including memory and CPU.
- Union-capable filesystems (e.g., OverlayFS): Provide layered, copy-on-write filesystem views for container images and writable layers.

These primitives allow multiple containers to share a single Linux kernel instance, minimizing overhead compared to virtual machines.

## Integration in Docker

- High-level API: Docker implements a high-level API to run isolated processes in containers.
- Daemon and client:
  - dockerd: Persistent daemon that manages containers and other Docker objects, listening for Engine API requests.
  - docker CLI: Talks to dockerd via the Engine API to build images, create/run containers, and manage services.
- Objects and workflow context:
  - Images: Read-only templates for container filesystems.
  - Containers: Runtime instances created from images, isolated via namespaces/cgroups and backed by a union-capable filesystem.
  - Services/Swarm: Orchestration layer distributing containers across multiple daemons.
- Role of libcontainer: On Linux hosts, libcontainer is the component that configures namespaces, cgroups, and filesystem layers to realize container isolation as requested by dockerd.

## Platform Considerations

- Linux: Native operation using kernel features directly through libcontainer.
- macOS: Docker runs containers inside a Linux virtual machine; kernel-level isolation still occurs within that Linux VM.
- Resource efficiency: Containers are lightweight and can be densely packed on a host; empirical analyses show multiple containers per host are common.

## Related Interfaces

Even with libcontainer available, Docker can utilize other abstraction layers to access kernel containerization:

- libvirt
- LXC
- systemd-nspawn

This flexibility allows Docker to operate across environments and to integrate with existing container backends where appropriate.

## Key Points

- libcontainer is Docker’s Go-based, native component (introduced in Docker 0.9) that replaced LXC as the default execution backend.
- It provides direct use of Linux kernel features—namespaces for isolation and cgroups for resource control—plus union filesystems (e.g., OverlayFS).
- libcontainer operates under dockerd on Linux, realizing the high-level Docker Engine API’s container semantics.
- Docker can still leverage abstracted interfaces (libvirt, LXC, systemd-nspawn), but libcontainer enables tight, kernel-level integration.
- On non-Linux hosts like macOS, Docker runs containers inside a Linux VM; libcontainer’s kernel interactions occur within that VM.