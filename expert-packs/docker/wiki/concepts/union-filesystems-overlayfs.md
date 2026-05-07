---
title: Union filesystems (OverlayFS)
slug: union-filesystems-overlayfs
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Union filesystems (OverlayFS)

Union-capable filesystems provide a merged, copy-on-write (CoW) view of multiple directory trees (layers). OverlayFS is the Linux kernel’s mainstream union filesystem used by container runtimes (including Docker) to compose read-only image layers with a thin writable layer per container. In Docker on Linux, OverlayFS is used in conjunction with kernel namespaces and cgroups to run many isolated containers inside a single kernel instance, avoiding the overhead of full virtual machines. On macOS, Docker runs a Linux virtual machine and uses OverlayFS inside that VM.

## Role in containerization (Docker context)

- OS-level virtualization: Docker implements containers by combining Linux kernel namespaces (isolation of process, mount, network, UTS, user IDs) and cgroups (resource limits) with a union-capable filesystem (such as OverlayFS) to assemble the container’s root filesystem from layered images.
- Image → container: A Docker image is a read-only template. A running container adds a writable upper layer on top, giving the appearance of a complete, writable filesystem while preserving image immutability and enabling fast, space-efficient clones.
- Efficiency: Layer sharing and CoW minimize disk usage and startup time. Multiple containers or images can share the same lower (read-only) layers; only changes are stored in the per-container upper layer.
- Cross-platform note: Docker on macOS uses a Linux virtual machine to host containers; OverlayFS operates inside that Linux VM. (Linux-native kernel features are required for OverlayFS.)

## OverlayFS fundamentals

- Layering model:
  - lowerdir: one or more read-only layers (e.g., image layers)
  - upperdir: a writable layer that records modifications
  - workdir: a required scratch directory for OverlayFS operations, residing on the same filesystem as upperdir
  - merged: the unified mountpoint exposing the composed view
- Copy-on-write (copy-up):
  - Reading prefers upperdir; if not present, falls back to lowerdir.
  - On first modification of a lowerdir file, OverlayFS copies it up into upperdir, then updates the upper copy.
- Deletions and directory semantics:
  - Deleting a file from lowerdir is represented in upperdir by special whiteout metadata, so the file disappears from the merged view.
  - Directory "opacity" can hide all entries from lower layers beneath an upperdir directory, ensuring expected semantics after replacements.
- Multi-lower support:
  - OverlayFS supports stacking multiple lower layers, enabling deep Docker image histories to appear as a single filesystem to the container.

## How Docker uses OverlayFS

- Storage driver: On Linux, Docker commonly uses the “overlay2” storage driver, which maps Docker image layers to lowerdirs and provides a per-container upperdir. This composes the container root filesystem without copying the entire image.
- Build and distribution:
  - Each image layer (e.g., results of build steps) becomes a lower layer. Shared layers are reused across images and containers.
  - Pull/push transfers layers independently, enabling deduplication across images in registries.
- Runtime:
  - Starting a container mounts an OverlayFS merged tree with the image layers as lowerdir and the container’s writable layer as upperdir/workdir.
  - Stopping a container leaves the upperdir intact (unless removed), preserving changes made at runtime in the container layer.

## Example: manual OverlayFS mount

Below is a minimal example illustrating OverlayFS mechanics (outside Docker):

```
# Prepare directories
mkdir -p /lower/base /upper/container /work/container /merged/container

# Populate a read-only base (simulating image layers)
echo "hello" > /lower/base/file.txt

# Mount OverlayFS
mount -t overlay overlay \
  -o lowerdir=/lower/base,upperdir=/upper/container,workdir=/work/container \
  /merged/container

# /merged/container now shows file.txt from lower
cat /merged/container/file.txt

# Modify file.txt (triggers copy-up into upper)
echo "world" > /merged/container/file.txt
```

## Interplay with namespaces and cgroups

- Namespaces:
  - mount namespace: isolates each container’s view of the filesystem mount table; OverlayFS mounts are private to the container’s namespace.
  - Other namespaces (PID, network, UTS, user) isolate process IDs, network stacks, hostnames, and user mappings.
- cgroups:
  - Limit and account for CPU and memory usage of processes running within the OverlayFS-backed container root.

## Advantages

- Space and bandwidth efficiency: CoW and layer sharing minimize duplication across containers and images; registries can distribute only the layers that differ.
- Performance: Fast container startup by assembling existing layers; metadata operations are generally cheaper than full copies.
- Immutability + mutability: Images remain immutable (reproducible), while containers remain writable via an upper layer.

## Considerations and limits

- Filesystem requirements: upperdir and workdir must reside on the same filesystem; not all backing filesystems have identical performance or feature support.
- Semantics: Some corner cases (e.g., special files, inotify behavior across layers) differ from a single, native filesystem; application expectations should be validated.
- Debuggability: Understanding the merged view versus actual on-disk upper/lower content is essential for troubleshooting (e.g., why a deleted lower file still appears due to missing whiteout).

## Relation to Docker platform components (from source)

- Docker Engine (dockerd) manages containers and images and exposes the Docker Engine API and CLI.
- Images (read-only templates) are stored/pulled from registries (e.g., Docker Hub) and assembled at runtime with a writable layer via OverlayFS on Linux.
- Containers are standardized, isolated environments (via namespaces and cgroups) that run on a single Linux kernel instance, leveraging OverlayFS to avoid virtual machine overhead. On macOS, a Linux VM hosts these features.

## Key Points

- Docker on Linux relies on a union-capable filesystem (such as OverlayFS) to compose read-only image layers with a per-container writable layer, enabling fast, space-efficient containers on a single kernel.
- OverlayFS merges lower (read-only) and upper (writable) directories via CoW semantics, exposing a unified merged mount.
- Kernel namespaces isolate the container’s view (processes, mounts, network), while cgroups limit resources; OverlayFS provides the layered root filesystem.
- Docker images are read-only templates stored in registries; containers add a writable layer on top. On macOS, these Linux kernel features (including OverlayFS) run inside a Linux VM.