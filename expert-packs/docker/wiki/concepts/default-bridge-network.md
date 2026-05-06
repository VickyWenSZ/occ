---
title: Default bridge network
slug: default-bridge-network
source: network
confidence: high
tags: [docker, networking, bridge, nat, dns]
---

# Default bridge network

The default bridge network is the built-in Linux bridge network that Docker Engine creates on first start. Containers run without an explicit --network option attach to this network by default. It provides basic, NATed egress connectivity, intra-network IP reachability, and host reachability of container ports, but lacks built-in service discovery by container name.

## Characteristics

- Platform scope: Created by Docker Engine on Linux when it starts for the first time. Native Windows containers use different drivers.
- Driver: bridge (the default network driver).
- Attachment default: docker run without --network attaches the container to the default bridge.
- Egress connectivity: Containers use masquerading (NAT) via the Docker host. If the host has Internet access, containers do too, without additional configuration.
- Intra-network connectivity:
  - Containers on the default bridge have unrestricted network access to each other using container IP addresses.
  - No name-based resolution between containers; they cannot refer to each other by name on the default bridge.
- Host/container reachability:
  - All ports of containers on bridge networks are reachable from the Docker host and from other containers on the same bridge network.
  - Ports are not reachable from outside the host, nor (by default) from containers on different networks, unless published.
- DNS configuration:
  - Containers on the default bridge receive a copy of the host’s /etc/resolv.conf (inherit the host’s DNS servers/search/options).
  - Docker’s embedded DNS server (127.0.0.11) is not used on the default bridge; it is used on user-defined networks.

Example egress from the default bridge:
```
docker run --rm -ti busybox ping -c1 docker.com
```

## Addressing and gateways

- IP allocation:
  - IPv4 enabled by default for networks; IPv6 can be enabled when creating a network with --ipv6.
  - Containers receive an IP from the attached network’s subnet; each network has a default subnet mask and gateway.
  - Docker performs dynamic subnetting and address allocation; subnets are taken from “default address pools” when not explicitly specified.
- Default gateway selection with multiple networks:
  - When a container is attached to multiple networks, the default gateway is selected by Docker and can change if attachments change.
  - Set gateway priority per network to influence the default gateway: gw-priority (default 0). The network with the highest priority becomes the default gateway. Setting gw-priority=1 on the intended default is sufficient.
  - Example:
    ```
    docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
    docker network connect anet2 myctr
    ```

## Port exposure and publishing

- On bridge networks (including the default bridge):
  - Container ports are reachable from the Docker host and from other containers on the same bridge network.
  - They are not reachable from outside the host or (by default) from other networks.
- Use --publish/-p to make a port available outside the host and to containers on other bridge networks.
- For direct-routing alternatives and how to disable NAT port mapping, see the port publishing feature set.

Examples:
```
# Publish container port 8080 to host port 8080
docker run -p 8080:8080 myapp
```

## DNS behavior

- Default bridge:
  - Inherits host DNS settings from /etc/resolv.conf.
  - If you need to override DNS servers/search/options for a container: use --dns, --dns-search, --dns-opt on docker run/create.
- User-defined networks (contrast):
  - Use Docker’s embedded DNS at 127.0.0.11, which forwards to the host’s configured DNS servers.
  - There is no IPv6 address for the embedded DNS; 127.0.0.11 works even in IPv6-only containers.

Relevant docker run flags:
- --dns: Add a DNS server (can be specified multiple times).
- --dns-search: Add DNS search domain(s).
- --dns-opt: Add resolv.conf options.
- --hostname: Override the container hostname (default is container ID).

Note on /etc/hosts:
- Containers maintain their own /etc/hosts. The host’s /etc/hosts entries are not inherited. Use --add-host to inject custom host entries at runtime.

## Subnet allocation and pools

- Automatic allocation (default-address-pools):
  - If no --subnet is specified at network creation, Docker draws subnets from default pools.
  - Built-in defaults (equivalent configuration):
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
  - base: Address space candidates; size: prefix length allocated per network.
  - Docker attempts to avoid prefixes already in use on the host, but customize pools to prevent conflicts in complex environments.
  - The default pools use large subnets, limiting the number of networks. Use smaller size to allow more networks.
  - Example to support 256 /24 networks from 172.17.0.0/16:
    ```
    {
      "default-address-pools": [
        {"base": "172.17.0.0/16", "size": 24}
      ]
    }
    ```
- IPv6 behavior:
  - If IPv6 subnets are needed and none are configured in default-address-pools, Docker allocates from a ULA prefix.
- Explicit and unspecified subnet requests:
  - Explicit:
    ```
    docker network create --ipv6 --subnet 192.0.2.0/24 --subnet 2001:db8::/64 mynet
    ```
  - Request specific prefix lengths from default pools using unspecified addresses (Docker 29.0.0+):
    ```
    docker network create --ipv6 --subnet ::/56 --subnet 0.0.0.0/24 mynet
    docker network inspect mynet -f '{{json .IPAM.Config}}' | jq .
    ```
    Note: Networks created with unspecified-address syntax require Docker 29.0.0+; downgrading renders them unusable until re-created or the daemon is restored to 29+.

## Contrasting user-defined bridge networks

- Creation:
  ```
  docker network create -d bridge my-net
  docker run --network=my-net -it busybox
  ```
- Differences vs default bridge:
  - Provide container-name-based service discovery (via embedded DNS 127.0.0.11).
  - Enable network-level isolation by grouping containers; containers in different user-defined networks cannot communicate unless explicitly attached.
  - Support network-scoped aliases (--alias) upon docker network connect.

## Other networking modes (context)

- Available drivers on Linux:
  - bridge (default), host (no isolation), none (fully isolated), overlay (multi-host via Swarm), ipvlan, macvlan.
- Container network stack sharing:
  - --network container:<name|id> attaches a container to another container’s network namespace.
  - Unsupported with container: mode: --add-host, --hostname, --dns, --dns-search, --dns-option, --mac-address, --publish, --publish-all, --expose.

## Practical commands

- Run on default bridge (implicit):
  ```
  docker run --rm -ti busybox ping -c1 docker.com
  ```
- Publish ports for external access:
  ```
  docker run -p 8080:8080 myapp
  ```
- Attach multiple networks and set default gateway preference:
  ```
  docker run --network name=gwnet,gw-priority=1 --network anet1 --name myctr myimage
  docker network connect anet2 myctr
  ```

## Key Points

- The default bridge is the Linux built-in Docker network used when no --network is specified; it provides NATed Internet egress and intra-network IP connectivity but no name-based service discovery.
- Container ports on bridge networks are reachable from the host and same-network containers; use -p/--publish to expose them outside the host or to other networks.
- On the default bridge, containers inherit DNS from the host’s /etc/resolv.conf; embedded DNS (127.0.0.11) is used only on user-defined networks.
- Docker auto-allocates subnets from configurable default-address-pools; customize pools to avoid conflicts and to scale the number of networks.
- With multiple attached networks, set gw-priority to control the container’s default gateway selection.