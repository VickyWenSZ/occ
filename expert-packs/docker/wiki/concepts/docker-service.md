---
title: Docker service
slug: docker-service
source: docker--software
confidence: high
tags: [tag1, tag2, tag3]
---

# Docker service

A Docker service is a Docker object used to assemble applications that enables containers to be scaled across multiple Docker daemons. When containers are scaled across daemons through services, the cooperating daemons form a swarm, communicating via the Docker Engine API. Services are interacted with through the same client and API primitives as other Docker objects.

## Position in Docker architecture

- Docker Engine: Core runtime that runs and manages containers.
  - dockerd (daemon): Persistent process that manages containers and handles container objects; listens for requests via the Docker Engine API.
  - docker (CLI): Command-line client used to interact with Docker daemons via the API.
- Docker objects (used to assemble applications):
  - Images: Read-only templates used to build containers; store and ship application filesystem and metadata.
  - Containers: Standardized, encapsulated environments that run applications; managed via the API or CLI.
  - Services: Orchestration objects allowing containers to be scaled across multiple Docker daemons; produce a swarm (set of cooperating daemons communicating through the Docker API).

## Services and swarm

- A Docker service coordinates the scaling of containers across multiple Docker daemons.
- The aggregate of daemons participating in a service deployment is a swarm: a set of cooperating daemons communicating through the Docker API.
- Services function as higher-level objects over containers and images, using the Engine API for control and coordination.

## Containerization foundations relevant to services

- OS-level virtualization:
  - Isolation via Linux kernel namespaces (process trees, network, user IDs, mounted filesystems).
  - Resource control via cgroups (CPU, memory).
  - Union-capable filesystems (e.g., OverlayFS) layer image and container filesystems efficiently.
- Efficiency:
  - Containers share a single OS kernel, using fewer resources than virtual machines; many containers can run concurrently on a host.
  - Empirical use (2018 analysis): typical deployments ran ~8 containers per host; ~25% of organizations ran 18+ per host.
- Platform notes:
  - On Linux, Docker uses kernel facilities directly (since v0.9, via libcontainer), and can also interface via libvirt, LXC, or systemd-nspawn.
  - On macOS, Docker runs containers inside a Linux virtual machine.

These properties underpin the scalability that services leverage across multiple daemons.

## Images and registries in service deployments

- Services consume images:
  - Images encapsulate application code and dependencies.
  - Images are pulled from or pushed to registries.
- Registries:
  - Public or private repositories for images; Docker Hub is the default public registry used by Docker clients.
  - Registries support notifications based on events (e.g., image push), which can integrate with automation around service lifecycles.

Example Dockerfile (building an image that a service could deploy):
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

## Compose and services at the application level

- Docker Compose defines and runs multi-container applications and operates across multiple containers with a single command.
- The docker compose CLI can:
  - Build images.
  - Scale containers.
  - Run containers that were previously stopped.
- docker-compose.yml defines an application’s services and supports options such as:
  - build: Configure how images are built (e.g., Dockerfile path).
  - command: Override default container commands.
- Notes:
  - Commands related to image manipulation or user-interactive options targeting a single container are not relevant in Docker Compose because Compose coordinates multiple containers.

## Operational flow (conceptual)

- Build or obtain an image (e.g., via Dockerfile and registry).
- Define application components:
  - As Docker services (to scale containers across multiple daemons, forming a swarm).
  - Or via Compose services in docker-compose.yml (to coordinate multiple containers and scale them from a single host interface).
- Use the Docker Engine API/CLI to create and manage services and the underlying containers across participating daemons.

## Key Points

- A Docker service is a Docker object that enables scaling containers across multiple Docker daemons; the cooperating daemons form a swarm.
- Services are managed through the Docker Engine API, with dockerd handling objects and docker providing the CLI interface.
- Images (from registries such as Docker Hub) are the templates services deploy as containers.
- Linux kernel features (namespaces, cgroups, union filesystems) make containers lightweight, supporting the scalability that services orchestrate.
- Docker Compose defines application services in YAML and can scale multiple containers with a single command.