---
title: Linux namespaces and cgroups
slug: linux-namespaces-and-cgroups
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Linux namespaces and cgroups

Linux namespaces and control groups (cgroups) are core Linux kernel primitives that underpin OS-level virtualization. Container platforms (notably Docker) use them to isolate processes’ views of the system and to constrain resource consumption within a single shared kernel, avoiding the overhead of full virtual machines.

## Role in OS-level virtualization

- OS-level virtualization packages applications and dependencies into containers that share the host’s kernel.
- On Linux, containers achieve:
  - Isolation via kernel namespaces (separate views of system resources).
  - Resource governance via cgroups (limits/quotas).
  - Layered storage via a union-capable filesystem (e.g., OverlayFS).
- This model enables many containers to run concurrently on one Linux instance, typically with significantly lower resource overhead than VMs.

## Namespace isolation (Linux kernel)

The Linux kernel’s support for namespaces mostly isolates an application’s view of the operating environment. In the context of containers, namespaces provide per-container views of:

- Process trees
- Network
- User IDs
- Mounted file systems

This isolation allows multiple containers to run side-by-side with separate process hierarchies, networking stacks, identity mappings, and mount tables, while still sharing the same kernel.

## Control groups (cgroups)

Cgroups provide fine-grained resource limiting and accounting to keep containers from monopolizing host resources. In the container context, cgroups apply constraints such as:

- Memory usage limits
- CPU usage limits

Using cgroups, container runtimes can enforce per-container resource budgets so workloads remain predictable and mutually non-disruptive.

## How Docker uses namespaces and cgroups

- When running on Linux, Docker uses the Linux kernel’s namespaces and cgroups to isolate and constrain containers within a single OS instance.
- Union-capable filesystems (such as OverlayFS) back container images and writable layers, enabling efficient image sharing and copy-on-write semantics.
- Implementation evolution:
  - Initially used LXC as the default execution environment.
  - Since Docker 0.9, uses its own component, libcontainer, to interact directly with kernel facilities; it can also integrate with libvirt, LXC, and systemd-nspawn.
- Docker implements a high-level API and daemon (dockerd) that create and manage containers, applying namespace isolation and cgroup policies to containerized processes.

## Cross-platform considerations

- Linux: containers run natively using namespaces and cgroups.
- macOS: Docker runs containers inside a Linux virtual machine to access Linux kernel features (namespaces, cgroups).
- Windows: the Docker engine is integrated with Windows Server, with broader Windows support evolving alongside technologies like WSL 2 to enable Linux container workflows on Windows systems.

## Operational characteristics

- Because containers are lightweight, a single server or VM can host many containers concurrently.
- Reported usage patterns have shown typical deployments running around eight containers per host, with a significant fraction running 18 or more per host.
- Containers can also run on constrained hardware (e.g., single-board computers like Raspberry Pi), benefiting from the efficiency of shared-kernel isolation.

## Conceptual summary

```
Linux container isolation on a shared kernel:

- Namespaces (isolation of views)
  - Process trees
  - Network
  - User IDs
  - Mounted file systems

- Cgroups (resource control)
  - Memory limiting
  - CPU limiting

- Union-capable filesystem
  - Layered images (e.g., OverlayFS)
  - Copy-on-write container layers
```

## Relationship to higher-level tooling

- Docker’s CLI and API orchestrate the creation of containers that are isolated by namespaces and constrained by cgroups.
- Docker images and registries enable distribution of container filesystems that are mounted into namespace-isolated processes and governed by cgroup limits.
- Multi-container definitions (e.g., with Docker Compose) coordinate multiple such isolated/cgrouped processes into an application stack.

## Key Points

- Linux namespaces isolate process trees, networking, user IDs, and mount tables per container, while sharing a single kernel.
- Cgroups apply container-level resource limits for memory and CPU, ensuring predictable multi-tenant behavior.
- Docker on Linux directly uses namespaces, cgroups, and union filesystems (e.g., OverlayFS) to implement lightweight containers.
- Docker initially relied on LXC, then moved to libcontainer (v0.9) to interface directly with kernel features.
- On macOS, Docker runs a Linux VM to access namespaces and cgroups; Windows support integrates with the OS and WSL 2 for Linux container workflows.