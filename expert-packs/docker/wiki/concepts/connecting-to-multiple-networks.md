---
title: Connecting containers to multiple networks
slug: connecting-to-multiple-networks
source: network
confidence: high
tags: [docker, networking, bridge, ipvlan, gw-priority]
---

# Connecting containers to multiple networks

Connecting a container to multiple networks lets it participate in several L2/L3 domains concurrently (for example, external and internal segments), with independent addressing, routing, and name resolution per network. Docker supports multi-attach on Linux across user-defined networks and different drivers (bridge, overlay, ipvlan, macvlan), with dynamic routing behavior and configurable default-gateway selection.

## Concepts and behavior

- Containers have networking enabled by default and can initiate outbound connections. A container sees a standard network stack (interfaces, IPs, routes, gateway, DNS).
- Without --network, containers attach to the default bridge network. This provides outbound Internet via NAT (“masquerading”).
- User-defined networks provide isolation and service discovery:
  - Default bridge: containers can reach each other by IP only; not by name.
  - User-defined networks: containers can reach each other by IP and container name (and aliases) via Docker’s embedded DNS.
- A container can be attached to multiple networks simultaneously, including different driver types (e.g., ipvlan for Internet, bridge for local services).
- “Internal” networks (created with --internal) disable external egress; a container can combine an external network and an internal-only backend network.

## Drivers (Linux)

- bridge: Default local L2 overlay on host; NAT to external networks.
- host: Removes isolation; container shares host network stack.
- none: No external connectivity; loopback only.
- overlay: Multi-host (Swarm) networking.
- ipvlan: L2/L3 integration with upstream network/VLANs; host-independent MAC/IP model.
- macvlan: Containers appear as first-class hosts on the LAN with unique MACs.

Note: Native Windows containers have different drivers.

## Attaching a container to multiple networks

You can multi-attach at create/run time or after a container is running.

- At create/run time:
  - Pass --network multiple times to attach to several networks.
  - You can set per-network parameters (e.g., gw-priority, IPs).
- After start:
  - Use docker network connect to add more networks to a running container.

Examples:
```bash
# Create a user-defined bridge network
docker network create -d bridge my-net

# Run a container attached to a user-defined network
docker run --network=my-net -it busybox

# Run a container attached to multiple networks (set a default-gw preference)
docker run \
  --network name=gwnet,gw-priority=1 \
  --network anet1 \
  --name myctr myimage

# Connect an additional network to a running container
docker network connect anet2 myctr
```

## Addressing and per-network configuration

- Each attached network contributes its own interface and IP configuration:
  - By default, IPv4 is enabled; IPv6 can be enabled per network with --ipv6.
  - The container receives an IP from the network’s subnet.
  - You can request specific addresses with --ip and/or --ip6 (at run or connect time).
- Hostname defaults to the container ID; override with --hostname.
- docker network connect supports --alias to add extra DNS names for that container on the target network.

Examples:
```bash
# IPv6-only user-defined network
docker network create --ipv6 --ipv4=false v6net

# Explicit dual-stack subnets
docker network create --ipv6 \
  --subnet 192.0.2.0/24 \
  --subnet 2001:db8::/64 \
  mynet

# Assign specific per-network IPs and alias on connect
docker run -d --name app --network appnet --ip 192.0.2.10 myimage
docker network connect --ip 172.18.0.50 --alias app-backend backnet app
```

## Subnet allocation

- Explicit subnets: Provide fixed subnets via --subnet on network create.
- Automatic allocation: If no --subnet is provided, Docker picks subnets from default-address-pools (configurable in /etc/docker/daemon.json). Built-in defaults include multiple 172.16.0.0/12 and 192.168.0.0/16 slices.
- You can subdivide pools to support more networks by setting a smaller “size”.
- Request a subnet with a specific prefix length from the pools using unspecified addresses:
```bash
# Request IPv4 /24 and IPv6 /56 from configured pools
docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
# => Shows the allocated IPv4 /24 and IPv6 /56 plus gateways
```
Note: Unspecified --subnet support requires Docker 29.0.0+. Downgrading makes such networks unusable until the daemon is restored to 29.0.0+ or the networks are recreated.

## Routing and default gateway selection

- Packet routing preference:
  - Traffic to directly connected subnets is sent out the corresponding interface.
  - Other traffic uses the container’s default gateway.
- Docker automatically selects a default gateway among the attached networks and may change it when network attachments change.
- To control the default gateway, set gw-priority on attachment:
  - Higher gw-priority wins; default is 0.
  - Set gw-priority=1 on the network that must be the default gateway.
- Example use case: combine an ipvlan network for Internet egress (must be default gateway) with a bridge network for local services.

Examples:
```bash
# Ensure gwnet provides the default route
docker run \
  --network name=gwnet,gw-priority=1 \
  --network services \
  --name web myimage

# Later attach another network without changing default route
docker network connect --ip 172.19.0.22 services web
```

## Name resolution and DNS

- Default-bridge network: containers inherit /etc/resolv.conf from the host.
- User-defined networks: containers use Docker’s embedded DNS server (127.0.0.11), which forwards to the host’s DNS. There is no IPv6 DNS server address; 127.0.0.11 works even in IPv6-only containers.
- Per-container DNS configuration (docker run/create):
  - --dns: Add explicit DNS resolver(s). Multiple allowed; addresses are from the container’s namespace (127.0.0.1 refers to the container).
  - --dns-search: Add search domains (multiple allowed).
  - --dns-opt: Set resolv.conf options.
  - --hostname: Override container hostname.
- Additional host entries are not inherited from the host’s /etc/hosts; inject them via docker run --add-host (reference: “add entries to container hosts file” in run docs).

## Published ports with multiple networks

- By default (no -p/--publish), container ports on bridge networks are reachable from:
  - The Docker host, and
  - Other containers on the same bridge network.
  - They are not reachable from outside the host, nor from containers on other networks.
- --publish/-p exposes ports via the host stack, making them reachable from outside the host and from containers on other bridge networks.

## Container networking stack sharing

- A container can join another container’s network namespace with --network container:<name|id>. It then shares all of that container’s interfaces, routes, and network attachments.
- Unsupported with container: mode: --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose.
- Example:
```bash
docker run -d --name redis redis --bind 127.0.0.1
docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
```

## Usage patterns

- Frontend + backend segmentation:
  - Frontend on an external bridge (or ipvlan) with gw-priority=1.
  - Backend-only communication via an --internal user-defined network.
- Mixed driver attachment:
  - ipvlan for upstream-routed Internet access; bridge for local service discovery via embedded DNS.
- Deterministic addressing:
  - Assign stable per-network IPs (via --ip/--ip6) and DNS aliases (via --alias) for name-based discovery within a network.

## Key Points

- A container can attach to multiple user-defined networks (and different drivers), receiving an interface, IP, routes, and DNS per network.
- Docker auto-selects the default gateway; control it with gw-priority (highest wins) at run/connect time.
- On user-defined networks, Docker’s embedded DNS (127.0.0.11) enables name-based service discovery; default bridge does not.
- Use --ip/--ip6 and --alias for per-network addressing and naming; use -p/--publish to expose ports beyond the host and across bridge networks.
- Subnets can be explicit or auto-allocated from configurable pools; requesting unspecified subnets requires Docker 29.0.0+.