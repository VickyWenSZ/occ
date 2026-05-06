---
title: Container network sharing mode
slug: container-network-sharing-mode
source: network
confidence: high
tags: [docker, networking, namespace, bridge, dns]
---

# Container network sharing mode

Container network sharing mode refers to running a container in the same networking stack (network namespace) as another container, so they share all network interfaces, IP addresses, routing, and DNS configuration. In Docker, this is enabled with --network container:<name|id>. It is distinct from other drivers (bridge, host, none, overlay, ipvlan, macvlan) but interoperates with them because the “primary” container may be attached to one or more such networks. All containers that share a stack inherit those attachments and behaviors.

## Core semantics

- Namespace sharing:
  - The joining container uses the target container’s network namespace.
  - Shared artifacts include: all interfaces (e.g., eth0, lo), assigned IP addresses per attached network, subnet mask, gateway, routing table, and DNS resolver behavior.
  - Loopback reachability: processes in both containers can communicate over 127.0.0.1 because they share the same lo device.
- Network membership:
  - The joining container inherits membership in every Docker network to which the target is connected (default bridge, user-defined bridge, overlay, ipvlan, macvlan, etc.).
  - Any future changes to the target’s network connections (attach/detach) affect all containers sharing the stack.
- Addressing:
  - The shared namespace has exactly one IP per attached network; all sharing containers present the same IPs externally.
- Isolation properties:
  - Network isolation among containers is eliminated only within the group sharing the namespace. Isolation relative to other networks/hosts depends on the target’s network attachments and drivers (e.g., bridge vs none).

## Unsupported flags in container network mode

When a container uses --network container:<name|id>, the following flags are not supported because networking is inherited and cannot be altered independently:

- --add-host
- --hostname
- --dns
- --dns-search
- --dns-option
- --mac-address
- --publish, --publish-all
- --expose

Implications:
- Port publishing must be performed on the target (primary) container or via its network(s); the sharing container cannot publish or expose ports on its own.
- DNS and hostname cannot be overridden per sharing container.

## Example: Sharing loopback for intra-namespace access

- Start a Redis server bound to 127.0.0.1 in its network namespace:
  ```
  docker run -d --name redis redis --bind 127.0.0.1
  ```
- Run a second container that shares redis’s networking stack and connect via 127.0.0.1:
  ```
  docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
  ```
Because both containers share the same network namespace, 127.0.0.1 resolves to the same loopback and reaches the Redis server.

## Interactions with Docker network types and topology

- Drivers (Linux):
  - bridge (default): standard container networking with NAT/masquerading to reach external services.
  - host: removes network isolation from the Docker host (shares the host’s stack).
  - none: full network isolation (no interfaces beyond loopback).
  - overlay: connects multiple Docker daemons (Swarm overlay).
  - ipvlan: attaches containers to external VLANs using L3/L2 semantics.
  - macvlan: containers appear as devices on the host’s network.
- Default behavior:
  - Without --network, containers join the default bridge.
  - Containers on the default bridge have outbound Internet access if the host has it (via masquerading).
- User-defined networks:
  - Provide container-name-based discovery and isolation domains.
  - Containers on the same user-defined network can reach each other by IP or name.
- Multiple networks per namespace:
  - A (primary) container can be attached to multiple networks; the sharing container inherits all of them.
  - Outbound routing chooses a directly connected destination if available; otherwise uses a default gateway.

## Default gateway selection and gw-priority

- Docker selects a default gateway for the namespace and may change it when network attachments change.
- You can influence selection by assigning a gateway priority per network attachment:
  - The default gw-priority is 0.
  - The gateway of the network with the highest gw-priority becomes the default.
  - Example: ensure gwnet is always the default gateway:
    ```
    docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
    docker network connect anet2 myctr
    ```
- All containers sharing the namespace use the same resulting default gateway.

## Published ports and reachability

- On bridge networks:
  - Container ports are reachable from the Docker host and other containers on the same bridge.
  - They are not reachable from outside the host (or other bridge networks) unless published.
- Use --publish/-p to make ports available outside the host and to containers on other bridge networks.
- In container network sharing mode:
  - --publish/--expose are not allowed for the sharing container.
  - Publish ports on the target (primary) container or rely on intra-network routing on user-defined networks.

## IP address, hostname, and DNS behavior

- IP allocation:
  - By default, IPv4 is enabled on networks; IPv6 can be enabled per network (--ipv6).
  - The Docker daemon dynamically allocates subnets and IPs per network; each network has a default subnet mask and gateway.
  - A container may be connected to multiple networks and can be assigned explicit IPs on each via --ip/--ip6 (applies to the primary container’s attachments).
- Hostname:
  - A container’s hostname defaults to its container ID; --hostname can override it in normal modes.
  - In container network sharing mode, --hostname is not supported for the sharing container.
- DNS resolution:
  - By default, containers use the host’s DNS settings from /etc/resolv.conf.
  - On the default bridge, containers receive a copy of the host’s resolv.conf.
  - On user-defined networks, containers use Docker’s embedded DNS server at 127.0.0.11, which forwards to the host-configured servers. This IPv4 address is valid even in IPv6-only containers.
  - Per-container DNS customization flags (--dns, --dns-search, --dns-opt) are unavailable in container network sharing mode for the sharing container.

## Subnet allocation (context for shared stacks)

- Networks can be created with explicit subnets:
  ```
  docker network create --ipv6 --subnet 192.0.2.0/24 --subnet 2001:db8::/64 mynet
  ```
- Or Docker auto-allocates from default-address-pools (configurable in /etc/docker/daemon.json). Defaults include:
  - 172.17.0.0/16, 172.18.0.0/16, 172.19.0.0/16, 172.20.0.0/14, 172.24.0.0/14, 172.28.0.0/14, 192.168.0.0/16 (with pool “size” determining per-network prefix length).
- You can request a subnet size from pools using unspecified addresses:
  ```
  docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
  docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
  [
    {"Subnet":"172.19.0.0/24","Gateway":"172.19.0.1"},
    {"Subnet":"fdd3:6f80:972c::/56","Gateway":"fdd3:6f80:972c::1"}
  ]
  ```
- IPv6 ULAs are used for dynamic IPv6 subnets if none are configured in default-address-pools.
- All containers sharing a stack are subject to the same per-network subnet allocations and gateways determined by the target container’s attachments.

## Operational considerations

- Lifecycle coupling: Networking behavior of sharing containers depends entirely on the target container; stopping or reconfiguring the target’s networks impacts all sharers.
- Naming and discovery:
  - On user-defined networks, embedded DNS provides name-to-IP resolution among peers.
  - The sharing container does not get independent network aliases on inherited networks; aliases apply to the primary container’s attachments.
- Security/isolation:
  - Sharing a network namespace merges network-level isolation between those containers; apply least privilege and minimize the set of processes sharing a stack.

## Key Points

- Use --network container:<name|id> to run a container in another container’s network namespace, sharing all interfaces, IPs, routes, and DNS behavior.
- Port publishing, DNS/hostname customization, MAC address, and exposure flags are not supported for the sharing container; publish/configure networking on the primary container.
- Both containers can communicate over 127.0.0.1 because they share the same loopback device.
- Default gateway selection follows the primary container’s network attachments and gw-priority; all sharers use the same result.
- On user-defined networks, Docker’s embedded DNS (127.0.0.11) handles name resolution; on the default bridge, containers inherit the host’s resolv.conf.