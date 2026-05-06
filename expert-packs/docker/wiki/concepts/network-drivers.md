---
title: Network drivers
slug: network-drivers
source: network
confidence: high
tags: [docker, networking, drivers, bridge, overlay]
---

# Network drivers

## Overview
- Container networking enables containers to communicate with each other and with non-Docker services. Containers have networking enabled by default and can make outbound connections.
- From inside a container, networking appears as a standard stack: an interface with an IP address, gateway, routing table, DNS, and related details.
- On first start (Linux), Docker Engine creates a built-in “default bridge” network. Containers run without --network attach to this default bridge and, via NAT/masquerading, inherit outbound Internet access if the host has it.
- Example:
  ```
  docker run --rm -ti busybox ping -c1 docker.com
  ```

## Built-in network drivers (Linux)
- bridge (default): Layer-3 bridge-based networking on the host. Suitable for single-host networking.
- host: Removes network namespace isolation; container shares the host’s network stack (no virtual interface).
- none: Disables networking; container is fully isolated at the network level.
- overlay: Multi-host networking for Docker Swarm; connects services across multiple Docker daemons.
- ipvlan: Connects containers directly to external L2 domains using IPv4/IPv6 with VLAN-like separation; IPs from external network.
- macvlan: Assigns MAC addresses so containers appear as physical devices on the host network; integrates with existing L2 domains.

Note: Native Windows containers use a different set of drivers (see Windows container network drivers).

## Default bridge vs. user-defined networks
- Default bridge:
  - Containers have unrestricted access to each other via container IPs.
  - No built-in name resolution between containers; communication is IP-only by default.
  - Ports are accessible from the host and containers on the same bridge, but not from outside the host or other networks unless published.
- User-defined networks:
  - Create with a specific driver (commonly bridge) to group containers with full mutual access and restricted access to other groups.
  - Provide automatic name-based service discovery; containers can reach peers by name or IP.
  - Example:
    ```
    docker network create -d bridge my-net
    docker run --network=my-net -it busybox
    ```

## Connecting containers to multiple networks and gateway selection
- A container can connect to multiple Docker networks (akin to plugging multiple NICs).
- Practical patterns:
  - Frontend on a bridge network with external access plus an --internal network for backend-only communication.
  - Combine different driver types (e.g., ipvlan for internet access and bridge for local services).
- Routing:
  - Traffic to directly-connected subnets goes out that interface; otherwise via the default gateway.
  - When attached to multiple networks, Docker selects one gateway as default and may change it as connectivity changes.
  - Control default gateway selection with gateway priorities (gw-priority). Highest priority wins (default 0; set 1 to force default).
  - Examples:
    ```
    docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
    docker network connect anet2 myctr
    ```

## Published ports
- By default on bridge networks:
  - All container ports are reachable from the Docker host and peer containers on the same bridge network.
  - Ports aren’t reachable from outside the host or from containers on other networks.
- Use --publish/-p to expose ports externally and to containers on other bridge networks.
- Port publishing can be disabled or replaced with direct routing approaches (see port publishing reference).

## IP addresses, hostnames, and aliases
- IP allocation:
  - IPv4 address allocation is enabled by default per network; disable at creation with --ipv4=false.
  - Enable IPv6 per network with --ipv6. Example:
    ```
    docker network create --ipv6 --ipv4=false v6net
    ```
  - Containers receive one IP address per attached network from that network’s subnet. Each network also has a default subnet mask and gateway.
- Static assignment:
  - Specify per-network addresses on attach: --ip for IPv4, --ip6 for IPv6.
  - Attach multiple networks by repeating --network at container creation or using docker network connect on a running container.
- Hostnames and aliases:
  - Default hostname is the container ID; override with --hostname.
  - When connecting to an existing network, add per-network aliases with --alias.

## Subnet allocation and IPAM
- Explicit subnets:
  - Provide exact subnets (v4 and/or v6) at network creation:
    ```
    docker network create --ipv6 --subnet 192.0.2.0/24 --subnet 2001:db8::/64 mynet
    ```
- Automatic allocation (default-address-pools):
  - If --subnet isn’t given, Docker picks from configurable pools in /etc/docker/daemon.json. Built-in defaults are equivalent to:
    ```json
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
  - base: source supernet; size: prefix length of each allocated subnet.
  - Docker tries to avoid prefixes already in use on the host, but customize pools to prevent conflicts in your environment.
  - Split large bases into smaller allocations to increase the number of possible Docker networks. Example creating 256 /24 subnets from a /16:
    ```json
    { "default-address-pools": [ { "base": "172.17.0.0/16", "size": 24 } ] }
    ```
- Unspecified addresses (requesting a prefix length from pools):
  - You can request subnets by prefix length using unspecified addresses (from Docker 29.0.0+):
    ```
    docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
    docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
    ```
    Outputs (example):
    ```
    [
      {"Subnet":"172.19.0.0/24","Gateway":"172.19.0.1"},
      {"Subnet":"fdd3:6f80:972c::/56","Gateway":"fdd3:6f80:972c::1"}
    ]
    ```
  - Downgrading Docker below 29.0.0 renders such networks unusable until removed/recreated or the daemon is restored to 29.0.0+.
- IPv6 ULA fallback:
  - If no IPv6 pools are configured, Docker allocates from a Unique Local Address (ULA) prefix for IPv6. To control IPv6, add explicit IPv6 pools to default-address-pools.

## DNS and name resolution
- Defaults:
  - Containers inherit DNS settings from the host’s /etc/resolv.conf.
  - Containers on the default bridge receive a copy of host resolv.conf.
- Embedded DNS for user-defined networks:
  - Docker provides an embedded DNS server at 127.0.0.11 for containers on user-defined networks. It:
    - Resolves container names/aliases on the same network.
    - Forwards external queries to the host-configured DNS servers.
  - No IPv6 equivalent address; 127.0.0.11 works even in IPv6-only containers.
  - If applications require an explicit DNS server address, use 127.0.0.11.
- Per-container DNS configuration (docker run/docker create):
  - --dns: Add one or more DNS server IPs (originating from the container’s netns; 127.0.0.1 is the container loopback).
  - --dns-search: Add one or more search domains.
  - --dns-opt: Supply resolv.conf options (key=value per OS docs).
  - --hostname: Set container hostname.

## Hosts file management
- Containers include /etc/hosts entries for their own hostname, localhost, and common defaults.
- The host’s /etc/hosts is not inherited by containers.
- Add extra entries to a container’s /etc/hosts via --add-host (see docker run reference).

## Container network namespace sharing (container: mode)
- Attach a container to another container’s network stack with --network container:<name|id>.
- Unsupported with container: mode:
  - --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose
- Example (client shares Redis container’s loopback to reach 127.0.0.1):
  ```
  docker run -d --name redis redis --bind 127.0.0.1
  docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
  ```

## Key Points
- Linux provides multiple built-in drivers: bridge (default), host, none, overlay, ipvlan, macvlan; Windows uses different drivers.
- User-defined networks add name-based discovery and isolation; embedded DNS at 127.0.0.11 resolves peers and forwards external lookups.
- Containers can join multiple networks; control default gateway with gw-priority; publish ports (-p/--publish) for external reachability.
- IPAM supports explicit subnets and automatic pools; IPv6 is opt-in; unspecified-address subnet requests require Docker 29.0.0+.
- Default bridge enables outbound Internet via NAT; default bridge does not provide name-based discovery between containers.