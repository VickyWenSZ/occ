---
title: User-defined networks
slug: user-defined-networks
source: network
confidence: high
tags: [docker, networking, bridge, ipam, dns]
---

# User-defined networks

User-defined networks in Docker let you create isolated, logical L2 domains that group containers with controlled connectivity and service discovery. Unlike the default bridge network (to which containers attach when no --network is specified), user-defined networks add name-based discovery via Docker’s embedded DNS, scoped IPAM, and clearer isolation boundaries across groups of containers.

## Default bridge vs. user-defined networks

- Default bridge:
  - Containers attach here when you omit --network.
  - Containers can reach external services via NAT/masquerading if the host has internet access.
  - Containers on the default bridge can connect to each other by IP but cannot resolve each other by name.
- User-defined networks:
  - You create them explicitly and attach containers that should fully communicate with each other.
  - Containers on the same user-defined network can communicate by IP and by container name/aliases (embedded DNS).
  - Provide clearer isolation from containers on other networks by default.

Example:
```bash
# Create a user-defined bridge network
docker network create -d bridge my-net

# Run a container attached to that network
docker run --network=my-net -it busybox
```

## Network drivers

Docker Engine includes multiple built-in drivers (Linux):

- bridge: Default local container L2 overlay on the host; standard choice for user-defined local networks.
- host: Removes network isolation; container shares the host’s network namespace.
- none: Fully isolates a container from host and other containers (no networking).
- overlay: Swarm overlay networks that span multiple Docker daemons.
- ipvlan: Connect containers to external VLANs using IPvlan semantics.
- macvlan: Containers appear as distinct MAC addresses on the host LAN.

Note: Native Windows containers have a different driver set (see Windows container network drivers).

## Connecting containers to networks

- A container can attach to one or more networks (analogous to plugging multiple NICs into different Ethernet segments).
- Common patterns:
  - Frontend container on a bridge network with outbound access.
  - Backend-only internal network (no external access) for service-to-service traffic.
  - Mixed driver use (e.g., ipvlan for external reachability and bridge for local services).

Attach at create time or later:
```bash
# At create/run time; can be repeated
docker run --network netA --network netB --name myctr myimage

# Attach a running container to another network
docker network connect anet2 myctr
```

## Default gateway selection and gw-priority

- Docker selects the container’s default gateway from attached networks; this may change when network attachments change.
- To force a specific default gateway, set gateway priority:
  - Default gw-priority is 0.
  - The network with the highest gw-priority becomes the default gateway.
  - Set gw-priority=1 on a network that should always be default.

Example:
```bash
docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
docker network connect anet2 myctr
```

## Port accessibility and publishing

- On bridge networks (including user-defined bridge):
  - Container ports are accessible from the Docker host and from containers on the same network.
  - Ports are not accessible from outside the host or from containers on other networks by default.
- Use port publishing to expose ports externally (and to containers in other bridge networks):
```bash
docker run -p 8080:80 myimage
```
- See port publishing docs for disabling userland proxy or using direct routing.

## IP addressing, IPv4/IPv6, and hostname control

- When creating a network:
  - IPv4 address allocation is enabled by default; can be disabled with --ipv4=false.
  - Enable IPv6 with --ipv6.
```bash
docker network create --ipv6 --ipv4=false v6net
```
- Containers receive an IP per attached network from that network’s subnet. Docker provides dynamic subnetting and IP allocation; each network has its own subnet mask and gateway.
- You can pin container addresses per network:
```bash
docker run --network mynet --ip 192.0.2.10 --name web myimage
docker run --network myv6net --ip6 2001:db8::10 --name api myimage
```
- Hostname:
  - Defaults to the container ID.
  - Override with --hostname.
- Network-scoped aliases:
  - When using docker network connect, add --alias to provide additional resolvable names on that network.

## Subnet allocation (IPAM)

- Explicit subnet configuration:
```bash
docker network create --ipv6 \
  --subnet 192.0.2.0/24 \
  --subnet 2001:db8::/64 \
  mynet
```
- Automatic subnet allocation:
  - If --subnet is omitted, Docker allocates from default-address-pools in /etc/docker/daemon.json.
  - Built-in default pools are equivalent to:
    - 172.17.0.0/16, 172.18.0.0/16, 172.19.0.0/16, 172.20.0.0/14, 172.24.0.0/14, 172.28.0.0/14, 192.168.0.0/16 with per-network size=16 (or configured size).
  - Keys:
    - base: the supernet to allocate from.
    - size: prefix length for each allocated network.
  - Docker tries to avoid conflicts with routes/addresses in use on the host, but customizing pools may be required in complex environments.
  - To increase the number of creatable networks, divide bases into smaller per-network prefixes (e.g., size: 24 to get up to 256 /24 networks from 172.17.0.0/16):
```json
{
  "default-address-pools": [
    { "base": "172.17.0.0/16", "size": 24 }
  ]
}
```
- Requesting a specific prefix length via unspecified addresses (Docker 29.0.0+):
```bash
docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
# =>
# [
#   { "Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1" },
#   { "Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1" }
# ]
```
- IPv6 note: If no IPv6 pools are configured, Docker auto-allocates from a ULA prefix. Add explicit IPv6 pools to control addressing.
- Downgrade caveat: Networks created with unspecified addresses require Docker 29.0.0+; downgrading makes them unusable until re-created or the daemon is restored to 29.0.0+.

## Name resolution and embedded DNS

- Default behavior:
  - Containers inherit host DNS from /etc/resolv.conf.
  - Containers on the default bridge get a copy of that file.
- User-defined/custom networks use Docker’s embedded DNS server:
  - Embedded DNS address: 127.0.0.11 (IPv4 only; usable even in IPv6-only containers).
  - Forwards external lookups to the host’s configured DNS servers.
  - Enables container-to-container name and alias resolution within the same user-defined network.
- Per-container DNS overrides (docker run/docker create):
  - --dns: Add one or more DNS server IPs. Requests originate from the container namespace; --dns=127.0.0.1 targets the container loopback.
  - --dns-search: Add search domains (can be repeated).
  - --dns-opt: Set resolv.conf options (key=value).
  - --hostname: Override container hostname.

## Custom hosts entries

- A container’s /etc/hosts includes entries for its hostname and standard localhost mappings.
- Host’s /etc/hosts is not inherited by containers.
- Use docker run --add-host to append entries to the container’s hosts file (see run reference).

## Container networking stack sharing (container: mode)

- Alternative to user-defined networks: attach a container to another container’s network stack:
```bash
docker run -d --name redis redis --bind 127.0.0.1
docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
```
- Unsupported with --network container:<name|id>:
  - --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address,
  - --publish, --publish-all, --expose

## Security and isolation considerations

- Isolation scope:
  - Containers on the same user-defined bridge can freely communicate unless blocked by container-level policies; isolation from other networks is by default.
- Name resolution scope:
  - Name/alias-based discovery is scoped to each user-defined network, reducing cross-network coupling.
- Gateway control:
  - gw-priority lets you deterministically set egress path when multihomed.

## Operational examples

- Create an IPv6-only user-defined network:
```bash
docker network create --ipv6 --ipv4=false v6net
```

- Attach multiple networks with a fixed default gateway:
```bash
docker run --network name=extnet,gw-priority=1 --network intnet --name app myimage
```

- Allocate from default pools with specific prefix lengths (29.0.0+):
```bash
docker network create --subnet 0.0.0.0/24 --subnet ::/56 mynet
```

- Publish a service externally from a user-defined bridge:
```bash
docker run --network appnet -p 8443:443 --name web mywebimage
```

## Key Points

- User-defined networks enable container name-based discovery (127.0.0.11 embedded DNS) and scoped isolation, unlike the default bridge.
- Containers can attach to multiple networks; gw-priority controls the default gateway across attachments.
- IPAM supports explicit subnets and automatic allocation from configurable default-address-pools, including IPv6 with ULA fallback.
- On bridge networks, ports are only host- and same-network-accessible by default; publish ports with -p for external/other-network access.
- Per-container DNS, hostname, IP assignment, and network-scoped aliases are configurable at create/connect time.