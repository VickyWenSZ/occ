---
title: Custom hosts and /etc/hosts behavior
slug: custom-hosts-and-etc-hosts
source: network
confidence: high
tags: [docker, networking, dns, hosts, containers]
---

# Custom hosts and /etc/hosts behavior

This page explains how Docker populates and manages /etc/hosts inside containers, how to add custom host mappings, and how this interacts with Docker’s DNS behavior and networking modes.

## What Docker writes to /etc/hosts inside containers
- Each container gets an /etc/hosts file managed by Docker.
- It always includes:
  - The container’s own hostname.
  - localhost and a few other common entries.
- The container’s hostname defaults to the container ID; override with --hostname.
- These entries are per-container and are not inherited from the host.

## Host /etc/hosts is not inherited
- Entries from the host’s /etc/hosts are not propagated into containers.
- To pass additional host→IP mappings to a container, you must explicitly add them to the container’s hosts file via Docker (see below).

## Adding custom host entries to a container
- Use --add-host with docker run or docker create to inject static name→IP mappings into the container’s /etc/hosts.
- General form:
  - docker run --add-host NAME:IP ...
  - Multiple --add-host flags are allowed to add multiple entries.
- These entries are static and only affect the target container.

Example:
```
docker run --rm -it \
  --add-host example.internal:203.0.113.10 \
  busybox cat /etc/hosts
```

Note: --add-host is not supported when using the container: networking mode (see “Networking mode constraints”).

## DNS vs /etc/hosts in Docker
- Default bridge network:
  - Containers inherit DNS settings from the host’s /etc/resolv.conf (a copy is placed in the container).
- User-defined networks:
  - Containers use Docker’s embedded DNS server at 127.0.0.11.
  - The embedded DNS forwards external lookups to the host-configured DNS servers.
  - There is no IPv6 equivalent; use 127.0.0.11 even for IPv6-only containers.
- Name resolution between containers:
  - On the default bridge, containers cannot refer to each other by name.
  - On user-defined networks, containers can resolve each other by container name via the embedded DNS.
- Per-container DNS configuration:
  - --dns: Add one or more DNS server IPs. Resolution occurs from the container’s network namespace (so --dns=127.0.0.1 targets the container’s own loopback).
  - --dns-search: Add one or more search domains.
  - --dns-opt: Add resolv.conf options.
- Distinction:
  - /etc/hosts provides static, container-scoped mappings you explicitly set (or those Docker injects for the container’s own identity).
  - resolv.conf and the embedded DNS provide dynamic name resolution within user-defined networks and for external domains.

## Hostname and aliases
- Hostname:
  - Defaults to the container ID; override with --hostname at container creation.
  - The chosen hostname is reflected in the container’s /etc/hosts.
- Network aliases:
  - When connecting a running container to a network, use docker network connect --alias to assign additional network-scoped aliases.
  - Aliases participate in DNS resolution on that network via the embedded DNS, not via /etc/hosts.

Example:
```
docker network create my-net
docker run -d --name api --network my-net busybox sleep 1d
docker network connect --alias api-v1 my-net api
# Other containers on my-net can resolve "api" and "api-v1" via 127.0.0.11
```

## Networking mode constraints
- Using --network container:<name|id> shares the target container’s network stack.
- In container: mode, the following flags are not supported:
  - --add-host
  - --hostname
  - --dns
  - --dns-search
  - --dns-option
  - --mac-address
  - --publish, --publish-all, --expose
- Implication: you cannot inject custom /etc/hosts entries (via --add-host) or change hostname/DNS in this mode.

## When to use custom hosts vs DNS
- Prefer user-defined networks for container-to-container name resolution (dynamic via embedded DNS).
- Use --add-host to:
  - Pin a specific name to a specific IP inside a container (e.g., to reach non-Docker services or when you need a static override).
  - Work around the lack of name resolution on the default bridge, if you cannot migrate to a user-defined network.

## Key Points
- Docker manages /etc/hosts per container; host /etc/hosts is not inherited.
- Add static name→IP mappings with --add-host (not supported in container: networking mode).
- On user-defined networks, container names and aliases resolve via the embedded DNS at 127.0.0.11.
- Default bridge containers copy the host’s /etc/resolv.conf; user-defined networks use embedded DNS.
- --hostname sets the container’s hostname (reflected in /etc/hosts); --alias adds DNS-scoped names on specific networks.