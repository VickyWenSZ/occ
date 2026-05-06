---
title: IP addresses and hostnames
slug: ip-addresses-and-hostnames
source: network
confidence: high
tags: [docker, networking, ip, dns, hostname]
---

# IP addresses and hostnames

This page summarizes how Docker assigns and manages container IP addresses, hostnames, DNS, and related subnet allocation mechanisms.

## Addressing model and per-network IPs

- IPv4 addressing is enabled by default when creating a Docker network; disable with --ipv4=false. Enable IPv6 per-network with --ipv6.
  - Example: docker network create --ipv6 --ipv4=false v6net
- By default, a container receives an IP address for every Docker network it attaches to:
  - The address is drawn from that network’s IP subnet via Docker’s IPAM (dynamic subnetting and address allocation).
  - Each network also has a default subnet mask and gateway.
- Containers can be attached to multiple networks:
  - At create time: pass --network multiple times.
  - At runtime: docker network connect.
  - For each attachment, you may request a specific address with --ip (IPv4) or --ip6 (IPv6).

Examples:
```
# Attach to two networks with fixed per-network IPs
docker run -d --name web \
  --network app-net --ip 192.0.2.10 \
  --network v6-net --ip6 2001:db8::10 \
  nginx

# Connect a running container to another network with a chosen IP
docker network connect --ip 192.0.2.11 app-net web
```

## Hostnames and network aliases

- A container’s hostname defaults to its container ID. Override with --hostname.
  - Example: docker run --hostname api-1 alpine uname -n
- On the default bridge, containers cannot reach each other by name (only by IP).
- On user-defined networks, containers can communicate by IP or by container name. You can add additional names using network aliases:
  - docker network connect --alias alias1 my-net myctr

## DNS resolution

- Default behavior:
  - Containers on the default bridge receive a copy of the host’s /etc/resolv.conf (inherit host DNS).
  - Containers on user-defined networks use Docker’s embedded DNS server at 127.0.0.11, which:
    - Resolves container names and aliases on that network.
    - Forwards external lookups to the host-configured DNS servers.
    - Has no IPv6 address; 127.0.0.11 is used even in IPv6-only containers.
- Per-container DNS configuration (docker run/create):
  - --dns: IP address of a DNS server; multiple flags allowed. Requests originate from the container’s network namespace (so --dns=127.0.0.1 means the container’s own loopback).
  - --dns-search: Search domain(s) for short hostnames; multiple allowed.
  - --dns-opt: Options for resolv.conf (platform-specific).

## Custom hosts entries

- Containers include standard /etc/hosts entries (localhost, the container’s own hostname, etc.).
- Host /etc/hosts is not inherited by containers.
- To inject additional hosts into a container, use --add-host (see docker run reference).
  - Example: docker run --add-host db.local:192.0.2.50 app

## Subnet allocation

Docker networks can use explicitly provided subnets or be allocated automatically from default address pools.

- Explicit subnets:
  - docker network create --ipv6 --subnet 192.0.2.0/24 --subnet 2001:db8::/64 mynet

- Automatic allocation from default-address-pools (daemon-level, /etc/docker/daemon.json):
  - If --subnet is omitted, Docker picks from configured pools. Built-in default is equivalent to:
    ```
    {
      "default-address-pools": [
        { "base": "172.17.0.0/16", "size": 16 },
        { "base": "172.18.0.0/16", "size": 16 },
        { "base": "172.19.0.0/16", "size": 16 },
        { "base": "172.20.0.0/14", "size": 16 },
        { "base": "172.24.0.0/14", "size": 16 },
        { "base": "172.28.0.0/14", "size": 16 },
        { "base": "192.168.0.0/16", "size": 20 }
      ]
    }
    ```
    - base: supernet from which subnets are carved.
    - size: prefix length of each allocated subnet.
  - IPv6 automatic allocation:
    - If default-address-pools has no IPv6 entries and an IPv6 subnet is required, Docker allocates subnets from a ULA (Unique Local Address) prefix. To control IPv6 subnets, add IPv6 pools to default-address-pools.
  - Docker attempts to avoid conflict with prefixes already used on the host, but customizing pools may be required to prevent routing conflicts.

- Increasing network count by subdividing pools:
  - Example to produce 256 /24 networks from 172.17.0.0/16:
    ```
    {
      "default-address-pools": [
        { "base": "172.17.0.0/16", "size": 24 }
      ]
    }
    ```

- Requesting a specific prefix length from pools using unspecified addresses (Docker 29.0.0+):
  ```
  docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
  docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
  [
    { "Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1" },
    { "Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1" }
  ]
  ```
  - Note: Networks created this way become unusable if the daemon is downgraded below 29.0.0; remove/recreate or restore 29.0.0+.

## Gateways and multiple networks

- When a container is attached to multiple networks, IP routing follows standard behavior:
  - Packets to directly connected subnets go out that interface.
  - Others are sent to a default gateway chosen by Docker and may change if network attachments change.
- To influence the default gateway when creating/connecting networks, set a gateway priority (gw-priority) so the network with the highest priority becomes the default (default is 0; set to 1 to make a network the default).
  - Example: docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage

## Container network namespace sharing implications

- If a container uses --network container:<name|id> (shares another container’s network stack), the following flags are not supported: --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose.
- Example:
  ```
  docker run -d --name redis redis --bind 127.0.0.1
  docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
  ```

## Key Points

- Containers get one IP per attached network; you can request static per-network IPv4/IPv6 with --ip/--ip6, and override the hostname with --hostname.
- Default bridge inherits host resolv.conf; user-defined networks use embedded DNS at 127.0.0.11 (also in IPv6-only containers) and support name/alias resolution.
- Subnets can be explicit (--subnet) or auto-allocated from configurable default-address-pools; IPv6 falls back to ULA if no IPv6 pools exist.
- You can subdivide pools to create more networks and request specific prefix lengths with unspecified addresses (Docker 29.0.0+).
- Host /etc/hosts is not inherited; inject entries with --add-host. Sharing another container’s network stack disables hostname/DNS/hosts flags.