---
title: Subnet allocation and default address pools
slug: subnet-allocation
source: network
confidence: high
tags: [docker, networking, ipam, subnet, ipv6]
---

# Subnet allocation and default address pools

This page explains how Docker allocates subnets and IP addresses to networks and containers, how to explicitly configure subnets, and how to customize the daemon’s default address pools used for automatic allocation.

## Overview

- By default, IPv4 allocation is enabled for user-defined networks; IPv6 allocation can be enabled per-network with --ipv6, and IPv4 can be disabled with --ipv4=false.
- Each network receives an IP subnet (and default mask and gateway). Containers attached to a network receive an IP from that network’s subnet.
- Docker’s IPAM can:
  - Use explicitly provided subnets.
  - Automatically allocate subnets from configurable default address pools.

## Address allocation modes

### Explicit subnet configuration

Specify exact subnets at network creation time. You can provide both IPv4 and IPv6 subnets:

```bash
docker network create --ipv6 \
  --subnet 192.0.2.0/24 \
  --subnet 2001:db8::/64 \
  mynet
```

- The network will have both families enabled; containers connecting to it can receive both IPv4 and IPv6 addresses.
- You can pin a container’s address on a given network using --ip (IPv4) or --ip6 (IPv6) during docker run or docker network connect.

### Automatic subnet allocation

If you omit --subnet, Docker automatically selects a subnet from the daemon’s default-address-pools. This avoids manual selection and helps prevent conflicts with host routes.

- Docker attempts to avoid address prefixes already in use on the host, but customizing pools may still be required to prevent routing conflicts in some environments.

## Default address pools

Configure the pools in /etc/docker/daemon.json. Docker’s built-in default is equivalent to:

```json
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

- base: The supernet from which Docker may allocate network subnets.
- size: The prefix length for each allocated subnet from that base (for example, size 24 yields /24 subnets).

Notes:
- The default pools use large subnets (for example, /16 allocations), which limits the number of distinct networks you can create from a base.
- You can divide a base into smaller subnets by setting a larger size (longer prefix) to support more networks.

Example: allocate many /24 networks from a single /16 base:

```json
{
  "default-address-pools": [
    { "base": "172.17.0.0/16", "size": 24 }
  ]
}
```

With this configuration, Docker allocates:
- 172.17.0.0/24, 172.17.1.0/24, … up to 172.17.255.0/24 (256 networks).

## IPv6 automatic allocation and ULA

- If an IPv6 subnet is required and default-address-pools has no IPv6 entries, Docker allocates IPv6 subnets from a Unique Local Address (ULA) prefix automatically.
- To use specific IPv6 subnets instead of ULA-derived ones, add IPv6 bases to default-address-pools.
- See also: Dynamic IPv6 subnet allocation (for additional details referenced by the source).

## Requesting a specific prefix length using “unspecified” subnets

You can request that Docker choose a subnet of a specific size from the default pools by passing an “unspecified” address with the desired prefix to --subnet. Provide one for each address family you want:

```bash
docker network create --ipv6 \
  --subnet ::/56 \
  --subnet 0.0.0.0/24 \
  mynet
```

Inspect shows the concretely allocated subnets and gateways:

```bash
docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
[
  {
    "Subnet": "172.19.0.0/24",
    "Gateway": "172.19.0.1"
  },
  {
    "Subnet": "fdd3:6f80:972c::/56",
    "Gateway": "fdd3:6f80:972c::1"
  }
]
```

Versioning note:
- Support for unspecified addresses in --subnet was introduced in Docker 29.0.0.
- If the daemon is downgraded to an older version, networks created this way become unusable until removed/re-created or the daemon is restored to 29.0.0+.

## Operational flags and behavior summary

- --ipv6: Enable IPv6 allocation for the network.
- --ipv4=false: Disable IPv4 allocation for the network.
- --subnet: Provide one or more subnets (IPv4/IPv6). Can be explicit (e.g., 192.0.2.0/24) or unspecified for size requests (e.g., 0.0.0.0/24, ::/56).
- --ip / --ip6: Assign specific container IPs on a given network.
- On each network, Docker sets a default gateway; containers get an address, mask, and gateway from that network’s subnet.

## Practical guidance

- To avoid conflicts with corporate/site routing, customize default-address-pools to exclude in-use prefixes and to align with organizational IP plans.
- Increase network scale by choosing a larger size (longer prefix) for allocations within a given base.
- Add IPv6 bases to default-address-pools to control the IPv6 prefixes used and avoid ULA if not desired.

## Key Points

- Docker IPAM uses either explicit --subnet values or automatic allocation from default-address-pools.
- default-address-pools is configured in /etc/docker/daemon.json with base and size fields; Docker ships with sensible IPv4 defaults.
- If no IPv6 pools are configured, Docker allocates IPv6 from a ULA prefix; add IPv6 bases to control this.
- Use unspecified --subnet (e.g., 0.0.0.0/24, ::/56) to request a specific prefix length from pools (Docker 29.0.0+).
- Customize pools to prevent routing conflicts and to scale the number of networks by selecting appropriate allocation sizes.