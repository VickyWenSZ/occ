---
title: Linux kernel features for containers
slug: linux-kernel-features-for-containers
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Linux kernel features for containers

This page summarizes the Linux kernel primitives and related interfaces that underpin containerization as used by Docker (software). Docker implements OS-level virtualization by orchestrating kernel features to isolate processes, constrain resources, and provide layered, copy-on-write filesystems within a single Linux kernel instance.

## Overview

- OS-level virtualization: Containers share a single operating system kernel and run application processes in isolated environments, rather than emulating hardware as in traditional virtual machines.
- Kernel integration: Docker can use different interfaces to access Linux kernel virtualization features. When running on Linux, it directly leverages kernel namespaces and control groups (cgroups), and pairs them with a union-capable filesystem (e.g., OverlayFS).
- Cross-platform note: On macOS, Docker runs containers inside a Linux virtual machine to obtain these Linux kernel capabilities.

## Core Linux kernel primitives

### Namespaces (process isolation)

The Linux kernel’s namespace mechanisms mostly isolate an application’s view of the operating environment. In the context of containers, isolation spans:
- Process trees (PID view/isolation)
- Network (separate networking stacks)
- User IDs (UID/GID mappings and isolation)
- Mounted file systems (independent mount points)

These namespaces ensure processes in one container have an isolated perspective of system resources and do not, by default, see or control those in another container or in the host.

### Control Groups (cgroups; resource governance)

Linux cgroups provide accounting and constraints for host resources consumed by processes in a containerized workload, including:
- Memory limits
- CPU shares/quotas

This enables predictable multi-tenant utilization on a single kernel by preventing any one container from exhausting system resources.

### Union-capable filesystems (layered, copy-on-write storage)

Containers commonly use a union-capable filesystem to compose a container’s root filesystem from layers:
- OverlayFS is a prominent example used by Docker on Linux.
- The layering model enables images (read-only templates) to be stacked with a writable layer for a running container, optimizing storage and distribution.

Example (illustrative image layering via a Dockerfile, which builds stacked filesystem layers):

```
ARG CODE_VERSION=latest
FROM ubuntu:${CODE_VERSION}
COPY ./examplefile.txt /examplefile.txt
ENV MY_ENV_VARIABLE="example_value"
RUN apt-get update
VOLUME ["/myvolume"]
EXPOSE 22
```

Each directive typically contributes a new layer in the resulting image, which is materialized using a union-capable filesystem such as OverlayFS.

## Execution environments and kernel-facing interfaces

Docker has historically supported multiple ways to interface with Linux kernel container facilities:

- LXC (Linux Containers): Initially the default execution environment in early Docker releases.
- libcontainer: Introduced in Docker 0.9, implemented in Go; it uses Linux kernel facilities directly, supplanting LXC as the default.
- Additional interfaces: Support has existed via libvirt, LXC, and systemd-nspawn abstractions in addition to direct kernel usage through libcontainer.

These backends ultimately orchestrate the same kernel primitives (namespaces, cgroups, union filesystems) to realize containers.

## Isolation and lifecycle within a single kernel

- Single-kernel model: Multiple containers co-exist on the same Linux kernel instance, with isolation primarily enforced by namespaces and resource limits enforced by cgroups.
- Inter-container communication: Containers communicate through well-defined channels (e.g., virtual networking) configured by the runtime, still enforced by kernel isolation.
- Overhead profile: Because they avoid booting guest kernels, containers are lightweight compared to VMs; a single host can run many containers concurrently.

Empirical density (from reported analyses):
- Typical deployments have run on the order of 8 containers per host.
- A substantial fraction of organizations have reported 18 or more containers per host.

## Platform notes

- Linux hosts: Direct use of kernel namespaces, cgroups, and OverlayFS through Docker Engine’s runtime layer (libcontainer and/or other supported interfaces).
- macOS hosts: Containers execute in a Linux VM to access Linux kernel features that are not natively available on macOS.

## High-level runtime model (as exposed by Docker)

- Docker Engine provides a high-level API and CLI to create and manage containers, abstracting direct interaction with namespaces, cgroups, and union filesystems.
- The daemon (dockerd) orchestrates container objects and applies kernel-level isolation and resource controls.
- Images (read-only, layered templates) are pulled from registries and instantiated as containers with an additional writable layer, leveraging OverlayFS or similar union mechanisms underneath.

## Conceptual contrasts: containers vs. virtual machines

- Containers: Share the host kernel; isolation via namespaces; resource governance via cgroups; storage via union-capable filesystems; low start-up overhead.
- Virtual machines: Each guest runs its own kernel; stronger hardware-level isolation but higher resource overhead.

## Key Points

- Docker on Linux relies on kernel namespaces (process, network, user IDs, mounts) for isolation and cgroups for CPU/memory resource limits.
- Union-capable filesystems such as OverlayFS provide layered, copy-on-write container images and writable runtime layers.
- Docker initially used LXC, then switched to libcontainer (from v0.9) to interact directly with Linux kernel features; libvirt and systemd-nspawn are also supported interfaces.
- Containers share a single Linux kernel instance; on macOS, Docker runs containers inside a Linux VM to access required kernel capabilities.
- The combination of namespaces, cgroups, and union filesystems yields lightweight, high-density deployment compared to virtual machines.