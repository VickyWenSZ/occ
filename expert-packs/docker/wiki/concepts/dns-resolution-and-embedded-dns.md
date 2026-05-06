---
title: DNS resolution and embedded DNS
slug: dns-resolution-and-embedded-dns
source: network
confidence: high
tags: [docker, dns, networking, bridge, resolv.conf]
---

# DNS resolution and embedded DNS

## Overview
Containers have networking enabled by default and see standard network artifacts (interface, IP, gateway, routing table, DNS). DNS behavior depends on the network type:
- Default bridge network: containers get a copy of the host’s /etc/resolv.conf and use the host-configured DNS directly.
- User-defined networks: containers use Docker’s embedded DNS server for name resolution within the network and for forwarding external queries to the host’s DNS.

## Default bridge vs user-defined networks
- Default bridge:
  - Containers can reach external services if the host has Internet access (via NAT/masquerading).
  - Containers have unrestricted access to each other by IP, but cannot refer to each other by name.
  - DNS: /etc/resolv.conf is copied from the host; no embedded DNS.
- User-defined networks (for example, created with docker network create -d bridge my-net):
  - Containers can communicate by IP and by container name.
  - Supports additional per-network aliases via --alias when connecting.
  - DNS: uses Docker’s embedded DNS service for both intra-network name resolution and forwarding of external lookups.

## Embedded DNS server
- Address: 127.0.0.11 (IPv4 only; there is no IPv6 equivalent).
  - Works even in IPv6-only containers; continue to use 127.0.0.11 as the resolver address.
- Function:
  - Resolves container names and network aliases within the same user-defined network.
  - Forwards external (non-container) DNS queries to the DNS servers configured on the Docker host.
- Usage:
  - Many applications require an explicit DNS server; use 127.0.0.11 inside containers on user-defined networks.

## Per-container DNS configuration
You can override or augment DNS on a per-container basis with docker run or docker create:
- --dns IP
  - Specify a DNS server IP. Repeatable for multiple servers.
  - Resolution originates in the container’s network namespace. Therefore, --dns=127.0.0.1 targets the container’s own loopback, not the host.
- --dns-search DOMAIN
  - Add a search domain for unqualified hostnames. Repeatable.
- --dns-opt OPTION[=VALUE]
  - Set resolv.conf options. Valid values depend on the OS resolv.conf semantics.
- --hostname NAME
  - Set the container’s own hostname (defaults to container ID).

Examples:
```bash
# Override DNS servers and search domains
docker run --rm -it \
  --dns 1.1.1.1 --dns 8.8.8.8 \
  --dns-search example.com --dns-search svc.local \
  busybox nslookup www.example.com

# Set container hostname
docker run --rm -it --hostname web-1 busybox hostname
```

## Hostname, aliases, and /etc/hosts
- Hostname:
  - Defaults to the container ID; override with --hostname.
- Network aliases:
  - When attaching or connecting to a user-defined network, add extra names with --alias:
    ```bash
    docker network create my-net
    docker run -d --name api --network my-net myimage
    docker network connect --alias usersvc my-net api
    ```
  - Aliases are resolved by the embedded DNS within that network.
- /etc/hosts:
  - Containers get entries for localhost, the container’s own hostname, etc.
  - Host’s /etc/hosts is not inherited.
  - To add static name-to-IP mappings inside a container, use --add-host (see docker run reference).

## IPv4/IPv6 considerations
- Networks:
  - IPv4 allocation is enabled by default; disable with --ipv4=false at docker network create time.
  - Enable IPv6 with --ipv6.
- Embedded DNS:
  - The resolver address remains 127.0.0.11 even in IPv6-only containers; there is no separate IPv6 listener.

## Behavior on default vs embedded DNS in /etc/resolv.conf
- Default bridge network:
  - /etc/resolv.conf inside the container is a copy of the host’s file (same nameservers, search, options).
- User-defined networks:
  - /etc/resolv.conf points to 127.0.0.11, and the embedded DNS implements the combination of:
    - Internal name resolution (container names/aliases on the same user-defined network).
    - Forwarding to host-configured upstream DNS for external domains.

## Limitations in container network namespace sharing
When using --network container:<name|id> (sharing another container’s network stack), DNS-related flags are not supported:
- Unsupported flags include: --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose.

## Practical notes
- On the default bridge, name-to-IP resolution between containers is not available; prefer a user-defined network to enable name-based service discovery.
- When setting --dns, remember that 127.0.0.1 references the container’s own loopback, not the host’s DNS service.
- For applications requiring a hardcoded resolver inside user-defined networks, configure 127.0.0.11.
- Add per-network aliases with --alias to present multiple stable names for the same container on a given user-defined network.

## Key Points
- Default bridge uses the host’s /etc/resolv.conf; user-defined networks use Docker’s embedded DNS at 127.0.0.11.
- Embedded DNS provides container/alias name resolution within a user-defined network and forwards external queries to the host’s DNS.
- There is no IPv6 embedded DNS address; 127.0.0.11 is used even in IPv6-only containers.
- Per-container DNS is configurable via --dns, --dns-search, --dns-opt, and --hostname; 127.0.0.1 refers to the container’s loopback.
- DNS-related flags are unsupported when using --network container:<name|id>.