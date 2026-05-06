---
title: Subnet allocation and address pools
slug: subnet-allocation-and-address-pools
source: network
confidence: high
tags: [docker, networking, ipam, ipv4, ipv6]
---

# Subnet allocation and address pools

This page explains how Docker allocates IPv4/IPv6 subnets to user-defined networks, how container IPs are assigned, and how to configure and tune default address pools to avoid conflicts and scale the number of networks.

## Overview: IPAM behavior

- IPv4 allocation is enabled by default; disable with --ipv4=false. Enable IPv6 with --ipv6.
  - Example: create an IPv6-only network:
    ```
    docker network create --ipv6 --ipv4=false v6net
    ```
- Each network has:
  - A subnet (IPv4 and/or IPv6).
  - A default subnet mask and gateway.
- Containers receive an IP address for every network they join (from that network’s subnet).
  - You can pin a container’s IP on a network with --ip (IPv4) and/or --ip6 (IPv6) when creating or connecting the container.

## Explicit subnet configuration

Specify exact subnets at network creation time:

```
docker network create --ipv6 \
  --subnet 192.0.2.0/24 \
  --subnet 2001:db8::/64 \
  mynet
```

Result: the network “mynet” uses 192.0.2.0/24 for IPv4 and 2001:db8::/64 for IPv6. Gateways are created within these subnets (e.g., .1 or ::1 by default).

## Automatic subnet allocation

If you omit --subnet, Docker automatically allocates subnets from configured “default address pools”. Configure pools in /etc/docker/daemon.json. If not configured, Docker uses built-in defaults equivalent to:

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

- base: The supernet from which Docker allocates subnets.
- size: The prefix length of each allocated subnet derived from the base.

Behavior:
- Docker attempts to avoid prefixes already in use on the host, but you may need to customize default-address-pools to prevent routing conflicts in your environment.
- Each created network is assigned the next available subnet of length size from one of the base pools. Each network also gets a default gateway inside that subnet.

## Scaling the number of networks by tuning pool size

The default pools use large per-network subnets (e.g., /16), which limits the total number of networks you can create from a given base range. Use a larger prefix length to increase network count.

Example: carve 172.17.0.0/16 into /24 networks (256 networks):

```
{
  "default-address-pools": [
    { "base": "172.17.0.0/16", "size": 24 }
  ]
}
```

Docker will allocate 172.17.0.0/24, 172.17.1.0/24, … up to 172.17.255.0/24 for new networks.

## Requesting a specific prefix length at creation time

You can request a subnet with a specific prefix length from the default pools by using an “unspecified” address in --subnet. Docker selects a concrete subnet matching that prefix from the configured pools.

Example (request an IPv4 /24 and an IPv6 /56):

```
docker network create --ipv6 \
  --subnet 0.0.0.0/24 \
  --subnet ::/56 \
  mynet
```

Verify allocation:

```
docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
[
  { "Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1" },
  { "Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1" }
]
```

Notes:
- Support for unspecified addresses in --subnet was introduced in Docker 29.0.0.
- Downgrading Docker below 29.0.0 makes networks created this way unusable until they are removed and recreated, or the daemon is upgraded back to 29.0.0+.

## IPv6-specific allocation and ULA behavior

- If an IPv6 subnet is needed and default-address-pools does not include any IPv6 ranges, Docker automatically allocates from a Unique Local Address (ULA) prefix.
- To control IPv6 allocation, add explicit IPv6 base pools to default-address-pools so Docker draws from those instead of a generated ULA.
- As with IPv4, you can request a specific IPv6 prefix length using an unspecified address (e.g., ::/56), or provide an explicit subnet (e.g., 2001:db8::/64).

## Operational tips

- Customize default-address-pools to:
  - Avoid conflicts with host or upstream networks.
  - Increase the number of networks by choosing larger prefix lengths (e.g., /24 instead of /16).
  - Provide IPv6 pools to replace automatic ULA generation.
- Per-network IP assignment:
  - Use --ip/--ip6 to assign a fixed IP to a container on a given network.
  - Each network will have a default gateway address assigned by Docker’s IPAM.

## Key Points

- Docker allocates network subnets either explicitly (--subnet) or automatically from configurable default-address-pools.
- Pools are defined by base (supernet) and size (per-network prefix length); tuning size controls how many networks you can create.
- Docker avoids known host conflicts but customizing pools may be required to prevent routing overlaps.
- IPv6 subnets fall back to a generated ULA prefix unless IPv6 pools are configured; unspecified addresses allow prefix-length requests (Docker 29+).
- Each network gets a default gateway and mask; containers get per-network IPs and can be assigned static IPs with --ip/--ip6.