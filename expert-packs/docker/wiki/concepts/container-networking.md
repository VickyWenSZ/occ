---
title: Container networking
slug: container-networking
source: network
confidence: high
tags: [docker, networking, bridge, dns, ipam]
---

# Container networking

Container networking is the capability for containers to connect to and communicate with each other and with external (non-Docker) services. Containers have networking enabled by default and can make outbound connections. From inside a container, the network appears as a standard stack: interfaces with IP addresses, a gateway, routing table, DNS, and related details. Containers are unaware of whether peers are other containers or traditional hosts.

## Default bridge network (Linux)

- On first start, Docker Engine (Linux) creates a built-in “default bridge” network.
- Running a container without --network attaches it to this default bridge.
- Containers on the default bridge:
  - Have outbound connectivity via masquerading (NAT). If the host has Internet access, no extra config is required.
  - Can reach each other by IP with no isolation by default.
  - Cannot discover each other by name (no embedded service discovery on the default bridge).

Example (outbound connectivity via default bridge):
```
$ docker run --rm -ti busybox ping -c1 docker.com
PING docker.com (23.185.0.4): 56 data bytes
64 bytes from 23.185.0.4: seq=0 ttl=62 time=6.564 ms
--- docker.com ping statistics ---
1 packets transmitted, 1 packets received, 0% packet loss
round-trip min/avg/max = 6.564/6.564/6.564 ms
```

## User-defined networks

- Create custom networks to group containers with full intra-group access and constrained inter-group access.
- Containers on the same user-defined network can communicate by IP and by container name (embedded DNS).
- Example:
```
$ docker network create -d bridge my-net
$ docker run --network=my-net -it busybox
```

## Network drivers (Linux)

Built-in drivers provide different connectivity models:

- bridge: Default driver; isolates containers at Layer 2 per network and NATs egress by default.
- host: Removes network isolation; container uses the host’s network namespace.
- none: Fully isolates; no external network connectivity.
- overlay: Swarm overlay networks span multiple Docker daemons.
- ipvlan: Connects containers to external VLANs using IPv4/IPv6 L3 separation.
- macvlan: Exposes containers as MAC-addressed devices on the physical network.

Note: Native Windows containers have a different set of drivers.

## Connecting containers to multiple networks

- A container can attach to multiple Docker networks (akin to multiple NICs on a host).
- Common pattern:
  - One bridge network with external access for frontends.
  - One --internal user-defined network for backends that must not have external connectivity.
- Containers may mix driver types (e.g., ipvlan for Internet access and bridge for local services).

Routing and default gateway selection:
- Packets to directly connected subnets are sent directly; others go to the default gateway.
- Docker selects the default gateway and may change it if the container’s network attachments change.
- To influence gateway selection, set a gateway priority on a network attachment. The network with the highest gw-priority becomes the default gateway (default gw-priority is 0).
- Examples:
```
# Ensure 'gwnet' is the default gateway for this container
$ docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage

# Later attach another network
$ docker network connect anet2 myctr
```

## Port accessibility and publishing

- By default (bridge networks), all container ports are reachable:
  - From the Docker host.
  - From other containers on the same network.
- By default, ports are NOT reachable:
  - From outside the host.
  - From containers on other networks (unless published).
- Use --publish or -p to map container ports to host ports, making them reachable from outside the host and from containers on other bridge networks.
- Port publishing can be disabled or direct routing configured; see “port publishing” reference for advanced cases.

## IP addressing, hostnames, and aliases

- Address families per network:
  - IPv4 is enabled by default; can be disabled with --ipv4=false on docker network create.
  - IPv6 can be enabled with --ipv6.
- Example (IPv6-only network):
```
$ docker network create --ipv6 --ipv4=false v6net
```
- IP allocation:
  - Each attached network assigns an address from its subnet to the container.
  - Docker IPAM handles dynamic subnetting and per-network gateway/subnet mask.
- Attaching to multiple networks:
  - At create time: pass --network multiple times.
  - At runtime: use docker network connect.
  - You can request specific IPs per-network with --ip (IPv4) and --ip6 (IPv6).
- Hostnames:
  - Default hostname is the container ID.
  - Override with --hostname.
- Network-scoped aliases:
  - When using docker network connect, --alias adds extra DNS aliases on that network.

## Subnet allocation and default address pools

- Explicit subnet configuration:
```
$ docker network create --ipv6 --subnet 192.0.2.0/24 --subnet 2001:db8::/64 mynet
```

- Automatic allocation from default-address-pools (configurable in /etc/docker/daemon.json). Docker’s built-in default is equivalent to:
```
{
  "default-address-pools": [
    {"base": "172.17.0.0/16", "size": 16},
    {"base": "172.18.0.0/16", "size": 16},
    {"base": "172.19.0.0/16", "size": 16},
    {"base": "172.20.0.0/14", "size": 16},
    {"base": "172.24.0.0/14", "size": 16},
    {"base": "172.28.0.0/14", "size": 16},
    {"base": "192.168.0.0/16", "size": 20}
  ]
}
```
- Definitions:
  - base: Supernet from which Docker allocates subnets.
  - size: Prefix length of each allocated subnet (e.g., 24 → /24 per network).
- Behavior and considerations:
  - Docker avoids address ranges already in use on the host when possible, but custom pools may be needed to prevent routing conflicts.
  - Large pool sizes reduce the number of distinct networks; subdivide to create more networks.
  - Example (allow 256 /24 networks from 172.17.0.0/16):
```
{
  "default-address-pools": [
    {"base": "172.17.0.0/16", "size": 24}
  ]
}
```
- Requesting subnets with specific prefix lengths from pools using unspecified addresses in --subnet (Docker 29.0.0+):
```
$ docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
$ docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
[
  {"Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1"},
  {"Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1"}
]
```
- IPv6 pool fallback:
  - If no IPv6 pools are configured, Docker allocates from a ULA prefix automatically for IPv6-enabled networks.
- Downgrade caveat:
  - Networks created with unspecified addresses require Docker 29.0.0+. Downgrading makes these networks unusable until removed/recreated or the daemon is restored to 29.0.0+.

## DNS services and name resolution

- Default behavior:
  - Containers inherit DNS settings from the host’s /etc/resolv.conf.
  - Containers on the default bridge receive a copy of the host’s resolv.conf.
- User-defined networks:
  - Containers use Docker’s embedded DNS server at 127.0.0.11.
  - The embedded DNS forwards external lookups to the host-configured resolvers.
  - There is no IPv6 DNS listener; 127.0.0.11 works even for IPv6-only containers.
  - If applications require an explicit DNS server, use 127.0.0.11.
- Per-container DNS configuration (docker run/create):
  - --dns: Add DNS server IP(s). Resolution occurs in the container’s netns; e.g., --dns=127.0.0.1 refers to the container’s loopback.
  - --dns-search: Add search domains (repeatable).
  - --dns-opt: Set resolver options (key=value) per resolv.conf semantics.
  - --hostname: Set container hostname (defaults to container ID).

## Hosts file management

- Containers populate /etc/hosts with entries for the container’s hostname, localhost, and common mappings.
- Host’s /etc/hosts entries are not inherited by containers.
- To add custom host-to-IP mappings inside a container, pass additional entries via docker run’s hosts-file options (e.g., --add-host).

## Container network namespace sharing (container: mode)

- A container can join another container’s network stack:
  - Use --network container:<name|id>.
  - The joining container shares interfaces, IPs, and ports with the target container.
- Unsupported flags with --network=container:...:
  - --add-host
  - --hostname
  - --dns
  - --dns-search
  - --dns-option
  - --mac-address
  - --publish
  - --publish-all
  - --expose
- Example (localhost-only Redis reachable via shared stack):
```
$ docker run -d --name redis redis --bind 127.0.0.1
$ docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
```

## Examples summary

- Create bridge network and run a container:
```
$ docker network create -d bridge my-net
$ docker run --network=my-net -it busybox
```
- IPv6-only network:
```
$ docker network create --ipv6 --ipv4=false v6net
```
- Prefer a specific default gateway on multi-network container:
```
$ docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
$ docker network connect anet2 myctr
```
- Allocate subnets from default pools with requested prefix lengths (Docker 29+):
```
$ docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
```

## Key Points

- The default bridge provides outbound connectivity via NAT; containers on it can reach each other by IP but not by name.
- User-defined networks enable name-based service discovery via Docker’s embedded DNS (127.0.0.11) and scoped isolation.
- Containers can attach to multiple networks; gateway selection can be controlled with per-attachment gw-priority.
- IPAM supports explicit subnets and automatic allocation from configurable default-address-pools (IPv4/IPv6).
- Use --publish to expose container ports beyond the host and across bridge networks; otherwise, ports remain local to the host and same-network containers.