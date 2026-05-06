---
title: Connecting containers to multiple networks
slug: connecting-multiple-networks
source: network
confidence: high
tags: [docker, container-networking, multi-network, gw-priority, ipam]
---

# Connecting containers to multiple networks

Connecting a container to multiple networks is analogous to plugging a host into multiple Ethernet segments: the container gains one interface per attached Docker network, an IP address on each, and routes traffic directly to connected subnets or via a single selected default gateway.

This page summarizes how to attach containers to multiple networks, control routing via gateway priority, manage IP addressing (IPv4/IPv6), name resolution, and port accessibility, using Docker Engine’s built-in networking.

## Concepts and drivers

- Default bridge:
  - On first start (Linux), Docker creates a built-in “default bridge” network.
  - Containers attached to it can reach external services via NAT masquerading if the host has Internet access.
  - Containers on the default bridge can reach each other by IP, not by name.

- User-defined networks:
  - Create isolated Layer-2 segments with service discovery.
  - Containers on the same user-defined network can communicate by IP or by container name (via Docker’s embedded DNS).
  - Example:
    ```
    docker network create -d bridge my-net
    docker run --network=my-net -it busybox
    ```

- Network drivers (Linux, built-in):
  - bridge: default, single-host L2 segments with NAT to host.
  - host: removes network isolation, container shares host’s network stack.
  - none: isolates container from host and other containers.
  - overlay: Swarm overlay; connects multiple Docker daemons.
  - ipvlan: attaches containers to external VLANs with IPv4/IPv6 at L2 using host parent.
  - macvlan: containers appear as unique MACs on the physical network.
  - Note: Native Windows containers use different drivers.

## Why multiple networks

- Segmentation and access control:
  - Frontend on a bridge network with external access + an internal user-defined network (created with --internal) to reach backends that do not need external connectivity.
- Mixed driver attachment:
  - For example, connect a container to:
    - an ipvlan network (as the Internet-facing path), and
    - a bridge network for access to local services.

## Attaching a container to multiple networks

- At container creation (multiple --network flags):
  - You can pass --network multiple times. Per-network options like gateway priority can be provided.
  - Example with default gateway preference:
    ```
    docker run \
      --network name=gwnet,gw-priority=1 \
      --network anet1 \
      --name myctr myimage
    ```
- After container start (docker network connect):
  - Attach a running container to additional networks.
  - Supports per-network IP and alias.
  - Examples:
    ```
    docker network connect anet2 myctr
    docker network connect --ip 192.0.2.10 anet2 myctr
    docker network connect --ip6 2001:db8::10 --alias api anet2 myctr
    ```

- Per-network addressing and identity:
  - A container receives one IP per attached network from that network’s subnet.
  - You can set the container’s IP on a network using --ip (IPv4) or --ip6 (IPv6) when creating or connecting.
  - Hostname defaults to the container ID; override with --hostname.
  - When connecting with docker network connect, --alias adds a network-scoped DNS alias.

## Routing and default gateway selection

- Routing behavior:
  - Traffic to directly connected subnets is sent out the corresponding interface.
  - Other traffic uses the selected default gateway.

- Default gateway selection:
  - Docker selects the default gateway based on gateway priority across attached networks.
  - The default may change whenever a container’s network attachments change.
  - Control with gw-priority:
    - Default priority is 0.
    - The gateway on the network with the highest gw-priority becomes the default.
    - Set the intended egress network’s gw-priority to 1 to ensure it wins.
  - Example pattern:
    - If using an ipvlan network for Internet egress and a bridge network for local services, ensure the ipvlan network has the highest gw-priority so its gateway becomes default.

## Port accessibility and publishing across networks

- On bridge networks:
  - All container ports are reachable from the Docker host and from containers on the same bridge network.
  - By default, ports are not reachable from outside the host or, typically, from containers attached to other networks.
- Publishing ports:
  - Use --publish/-p to expose a port externally and to containers on other bridge networks.
  - For direct routing options (and disabling port mapping), see port publishing reference.

## DNS and name resolution

- DNS defaults:
  - Containers inherit host DNS from /etc/resolv.conf by default.
  - On the default bridge, containers receive a copy of this file.

- Embedded DNS on user-defined networks:
  - Docker’s embedded DNS (127.0.0.11) provides container-name-based resolution scoped to each user-defined network and forwards external queries to host-configured resolvers.
  - There is no IPv6 DNS server address; 127.0.0.11 also works in IPv6-only containers.

- Per-container DNS configuration (docker run/create):
  - --dns: add one or more DNS server IPs (127.0.0.1 refers to the container’s loopback).
  - --dns-search: add search domains (repeatable).
  - --dns-opt: supply resolv.conf options.
  - --hostname: override the container hostname.

- /etc/hosts:
  - Containers get default entries (self hostname, localhost, etc.).
  - Host’s /etc/hosts is not inherited; add entries via --add-host.

## IP addressing, IPv4/IPv6, and subnet allocation (IPAM)

- Enabling IPv6 and disabling IPv4 per network:
  ```
  docker network create --ipv6 --ipv4=false v6net
  ```

- Address allocation:
  - Each network has a subnet, mask, and gateway.
  - By default, Docker dynamically allocates subnets and IPs from default address pools; you can also define explicit subnets.

- Explicit subnets at network create:
  ```
  docker network create \
    --ipv6 \
    --subnet 192.0.2.0/24 \
    --subnet 2001:db8::/64 \
    mynet
  ```

- Automatic subnet allocation and default pools (daemon.json):
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
  - base: pool to allocate from.
  - size: prefix length of each allocated subnet.
  - Docker attempts to avoid conflicts with host routes, but customize pools if your environment overlaps.
  - Large default pools limit number of networks; use smaller size (longer prefixes) to support more networks.
    - Example to create up to 256 /24 networks from 172.17.0.0/16:
      ```
      { "default-address-pools": [{"base": "172.17.0.0/16", "size": 24}] }
      ```

- Requesting a prefix length from default pools with unspecified addresses (Docker 29.0.0+):
  ```
  docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
  docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
  [
    {"Subnet": "172.19.0.0/24", "Gateway": "172.19.0.1"},
    {"Subnet": "fdd3:6f80:972c::/56", "Gateway": "fdd3:6f80:972c::1"}
  ]
  ```
  - Downgrading Docker below 29.0.0 renders such networks unusable until removed or the daemon is restored to 29.0.0+.

- IPv6 ULA fallback:
  - If IPv6 subnets are required but not configured in default-address-pools, Docker allocates from a ULA prefix automatically. Add specific IPv6 pools for deterministic prefixes.

## Alternative: sharing another container’s network stack

- Use --network container:<name|id> to join another container’s network namespace directly.
- Unsupported with container: mode:
  - --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose
- Example:
  ```
  docker run -d --name redis redis --bind 127.0.0.1
  docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
  ```

## Examples

- Create networks and set a preferred default gateway:
  ```
  docker network create -d bridge publicnet
  docker network create --internal privnet

  docker run -d --name app \
    --network name=publicnet,gw-priority=1 \
    --network privnet \
    myimage
  ```

- Add a third network at runtime with an alias and static IP:
  ```
  docker network create -d bridge tools
  docker network connect --ip 192.0.2.50 --alias metrics tools app
  ```

## Key Points

- A container can attach to multiple Docker networks, receiving one IP per network and routing via the highest gw-priority default gateway.
- Control egress by setting gw-priority (default 0); the network with the highest priority supplies the container’s default route.
- On user-defined networks, Docker’s embedded DNS (127.0.0.11) enables name-based discovery; specify per-network IPs and aliases on connect.
- On bridge networks, ports are reachable from the host and same-network containers; use --publish to expose to external clients and other bridge networks.
- Subnets are allocated per network via explicit --subnet or from configurable default address pools; IPv6 can be enabled per network with --ipv6.