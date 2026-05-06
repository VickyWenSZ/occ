---
title: Container networking overview
slug: container-networking-overview
source: network
confidence: high
tags: [docker, networking, containers, bridge, dns]
---

# Container networking overview

Container networking enables containers to connect to and communicate with each other and with non-Docker services. Networking is enabled by default: containers can make outbound connections and see a standard network interface, IP address, gateway, routing table, and DNS—without knowledge of the underlying network type or whether peers are containers.

## Default bridge network (Linux)

- On first start, Docker Engine creates a single built-in network: the default bridge.
- Containers run without --network attach to this default bridge.
- Egress: Containers on the default bridge access external networks via NAT “masquerading.” If the host has Internet access, containers do too, without extra configuration.
- Intra-bridge connectivity:
  - Containers on the default bridge can reach each other by IP with no isolation.
  - They cannot resolve each other by name on the default bridge.
- Port reachability:
  - All container ports on bridge networks are reachable from the Docker host and from other containers on the same bridge network.
  - They are not reachable from outside the host or from containers on other networks unless explicitly published.

Example (egress via NAT):
```bash
docker run --rm -ti busybox ping -c1 docker.com
PING docker.com (23.185.0.4): 56 data bytes
64 bytes from 23.185.0.4: seq=0 ttl=62 time=6.564 ms
--- docker.com ping statistics ---
1 packets transmitted, 1 packets received, 0% packet loss
round-trip min/avg/max = 6.564/6.564/6.564 ms
```

## User-defined networks

- Motivation: segment groups of containers to allow full intra-group access while restricting cross-group access.
- Behavior:
  - Containers on the same user-defined network can communicate via container IP or container name.
  - Supports network-level isolation from other networks.
- Create and use a user-defined bridge:
```bash
docker network create -d bridge my-net
docker run --network=my-net -it busybox
```
- You can also create “internal” networks (no external access) for backend-only communication (use the --internal network mode).

## Network drivers (Linux)

Built-in drivers:
- bridge: Default network driver (Linux bridging and NAT).
- host: Removes network isolation between container and host (container uses host’s network stack).
- none: No networking for the container (fully isolated).
- overlay: Swarm overlay networks connecting multiple Docker daemons.
- ipvlan: Connect containers directly to external L2/L3 networks/VLANs using ipvlan.
- macvlan: Containers appear as distinct MAC addresses on the host’s L2 network.

Note: Native Windows containers use different drivers (see Windows container network drivers).

## Connecting a container to multiple networks

- Analogy: like plugging multiple Ethernet cables into a host. A container can be attached to multiple Docker networks, even of different types.
- Examples:
  - Frontend on a bridge with external access plus an --internal network to reach backends without exposing them externally.
  - An ipvlan network for Internet access plus a bridge network to reach local services.
- Routing and default gateway:
  - Packets to directly connected subnets go out that interface; all others go to the default gateway.
  - Docker selects the default gateway and may change it if network attachments change.
  - Control gateway selection with gw-priority. The default is 0; the highest priority network’s gateway becomes the default. Set gw-priority=1 to force a network to be default.

Examples:
```bash
# Create container with multiple networks, preferring gwnet as default gateway
docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage

# Connect an additional network after start
docker network connect anet2 myctr
```

## Ports and publishing

- By default on bridge networks:
  - Ports are reachable from the host and peers on the same bridge network.
  - Ports are not reachable from outside the host or from containers on other networks.
- Use -p/--publish to expose a container port outside the host and to containers in other bridge networks.
- For advanced behaviors (e.g., disable port mapping or use direct routing), see port publishing documentation.

## IP addressing, hostname, and aliases

- Network IP versions:
  - IPv4 addressing is enabled by default on new networks; disable with --ipv4=false.
  - Enable IPv6 addressing with --ipv6.
```bash
docker network create --ipv6 --ipv4=false v6net
```
- Addressing:
  - A container gets one IP per attached network.
  - Subnets and IPs are dynamically allocated by Docker IPAM unless explicitly configured.
  - Each network has a subnet mask and gateway.
- Multi-network attachment:
  - Attach during create with multiple --network flags, or later with docker network connect.
  - Set per-network IPs with --ip (IPv4) and --ip6 (IPv6).
- Hostname:
  - Defaults to the container ID; override with --hostname.
- Network aliases:
  - When using docker network connect, specify --alias to add extra DNS names on that network.

## Subnet allocation

Docker supports explicit IPAM configuration or automatic allocation from default address pools.

- Explicit subnet configuration:
```bash
docker network create --ipv6 \
  --subnet 192.0.2.0/24 \
  --subnet 2001:db8::/64 \
  mynet
```

- Automatic subnet allocation from default pools:
  - When --subnet is omitted, Docker selects a subnet from default-address-pools (daemon-level).
  - Default configuration is equivalent to:
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
  - base: Supernet from which subnets are allocated.
  - size: Prefix length (CIDR) for each allocated subnet.
  - IPv6: If no IPv6 pools are configured, Docker allocates from a ULA prefix. Add your IPv6 pools to default-address-pools to control prefixes.
  - Conflict avoidance: Docker attempts to avoid prefixes already in use on the host, but customize pools to prevent routing conflicts in complex environments.
  - Pool sizing: Large default subnets limit the number of networks. Use smaller sizes to increase network count.

Example (256 /24 networks from 172.17.0.0/16):
```json
{
  "default-address-pools": [
    { "base": "172.17.0.0/16", "size": 24 }
  ]
}
```

- Requesting a specific prefix length using unspecified addresses (Docker 29.0.0+):
```bash
docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
# Output:
# [
#   { "Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1" },
#   { "Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1" }
# ]
```
Note: Networks created with unspecified --subnet require Docker 29.0.0 or later. Downgrading makes them unusable until re-created or the daemon is restored to 29.0.0+.

## DNS services and custom hosts

- Defaults:
  - Containers inherit DNS settings from the host’s /etc/resolv.conf.
  - Containers on the default bridge get a copy of /etc/resolv.conf.
  - Containers on user-defined networks use Docker’s embedded DNS server at 127.0.0.11.
    - The embedded DNS forwards external lookups to the host’s configured DNS servers.
    - There is no IPv6 equivalent; 127.0.0.11 also works for IPv6-only containers.
    - If an application requires an explicit DNS server IP, use 127.0.0.11.
- Per-container DNS configuration (docker run/docker create):
  - --dns <IP>: Add a DNS server; repeatable. Resolution occurs from the container’s namespace (e.g., --dns=127.0.0.1 targets the container’s loopback).
  - --dns-search <domain>: Add DNS search domains; repeatable.
  - --dns-opt <key=value>: Set resolv.conf options (see OS resolv.conf docs).
  - --hostname <name>: Set the container’s hostname (defaults to container ID).
- /etc/hosts:
  - Containers get standard entries (e.g., hostname, localhost).
  - Host’s /etc/hosts entries are not inherited.
  - Add custom entries with --add-host.

## Container network namespace sharing (container: mode)

- Attach a container to another container’s networking stack:
```bash
docker run --rm -it --network container:<name|id> <image> <cmd>
```
- Unsupported with --network container:<name|id>:
  - --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose
- Example:
```bash
docker run -d --name redis redis --bind 127.0.0.1
docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
```
redis-cli connects to Redis via 127.0.0.1 because both share the same network namespace.

## Key Points

- Default bridge provides immediate egress via NAT; intra-bridge reachability is by IP only unless using user-defined networks with embedded DNS.
- Attach containers to multiple networks and control the default gateway with gw-priority; the highest priority wins.
- IPAM supports explicit subnets or automatic allocation from configurable default-address-pools; IPv6 ULA is used if no IPv6 pools exist.
- Use -p/--publish for external reachability; otherwise, container ports are confined to the host and peers on the same bridge.
- Docker’s embedded DNS at 127.0.0.11 serves user-defined networks and forwards to host DNS; customize per-container DNS with --dns, --dns-search, --dns-opt, and set --hostname as needed.