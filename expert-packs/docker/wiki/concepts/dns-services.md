---
title: DNS services in containers
slug: dns-services
source: network
confidence: high
tags: [docker, networking, dns, resolv.conf, service-discovery]
---

# DNS services in containers

This page explains how Domain Name System (DNS) resolution works from inside Docker containers, how it differs across network types, and how to configure it per container.

## Overview

- Containers see a normal Linux networking stack: interface(s), IP/gateway, routing, and DNS.
- By default, containers use the same DNS servers as the host (from the host’s /etc/resolv.conf), but behavior differs between the default bridge and user-defined networks.
- You can override DNS behavior per container using docker run/docker create flags.

## DNS behavior by network type

### Default bridge network
- When a container is attached to the default bridge network (implicit when no --network is specified), it receives a copy of the host’s /etc/resolv.conf.
- Containers on the default bridge:
  - Have unrestricted L3 connectivity to each other via IP.
  - Cannot resolve each other by name by default (no built-in service discovery).

### User-defined networks (bridge, overlay, etc.)
- Containers attached to a user-defined network use Docker’s embedded DNS server.
- Embedded DNS characteristics:
  - Address: 127.0.0.11 (IPv4 only; this IPv4 address also works in IPv6-only containers).
  - Forwards external lookups to the DNS servers configured on the host.
  - Provides name resolution for containers on the same user-defined network:
    - Container names resolve to the container’s IP on that network.
    - Network-scoped aliases (--alias on docker network connect, or --network-alias with compose) also resolve.
- Result: On user-defined networks, containers can communicate using container names or aliases.

## Per-container DNS configuration

Use these flags with docker run or docker create to change name resolution:

- --dns <IP>
  - Add a DNS server IP (use multiple --dns flags for multiple servers).
  - Resolution is performed from the container’s network namespace. For example, --dns=127.0.0.1 refers to the container’s own loopback, not the host’s.
- --dns-search <domain>
  - Add a search domain for non-FQDN lookups (repeatable).
- --dns-opt <key:value or key>
  - Add resolver options corresponding to resolv.conf options supported by your OS.
- --hostname <name>
  - Set the container’s hostname (defaults to the container ID if omitted).

Notes:
- If an application inside the container requires an explicit DNS server address, use 127.0.0.11 on user-defined networks to leverage Docker’s embedded DNS.
- On the default bridge network, resolv.conf inside the container typically lists the host’s DNS servers directly (copied from the host).

## /etc/hosts and custom host mappings

- Each container gets an /etc/hosts containing:
  - Its own hostname mapping.
  - Standard entries (127.0.0.1 localhost, etc.).
- The host’s /etc/hosts entries are not inherited by containers.
- To add static name-to-IP mappings inside a container, use:
  - docker run --add-host name:ip ...
- Limitation: When using --network container:<name|id> (sharing another container’s network stack), the following are not supported:
  - --add-host, --hostname, --dns, --dns-search, --dns-option (and several port exposure flags).

## Practical examples

- Use embedded DNS for app configs that need a DNS IP:
  - Configure the app to use 127.0.0.11 inside a container on a user-defined network.
- Override DNS servers:
  - docker run --rm --dns 1.1.1.1 --dns 8.8.8.8 -it busybox nslookup example.com
- Use container names on a user-defined network:
  - docker network create mynet
  - docker run -d --name svc --network mynet nginx
  - docker run --rm -it --network mynet busybox ping -c1 svc

## Behavioral summary

- Default bridge:
  - resolv.conf is copied from the host; no name-based service discovery between containers.
- User-defined networks:
  - Embedded DNS at 127.0.0.11 provides container/alias name resolution and forwards external queries to host DNS.
- IPv6:
  - No separate IPv6 address for the embedded DNS; 127.0.0.11 works even in IPv6-only containers.
- Per-container control:
  - --dns, --dns-search, --dns-opt, --hostname adjust resolver behavior and identity.
- Static hosts:
  - Use --add-host to inject entries into container /etc/hosts; host’s /etc/hosts is not inherited.
- Network namespace sharing:
  - In container: mode, DNS/hosts customization flags are not supported.

## Key Points

- Default bridge copies host /etc/resolv.conf; user-defined networks use Docker’s embedded DNS at 127.0.0.11.
- Embedded DNS resolves container names/aliases on the same user-defined network and forwards external lookups to the host’s DNS servers.
- There is no IPv6 address for embedded DNS; 127.0.0.11 works in IPv6-only containers.
- Per-container DNS behavior is configurable via --dns, --dns-search, --dns-opt, and hostname via --hostname.
- Host /etc/hosts is not inherited; use --add-host to inject static mappings (not available in --network container: mode).