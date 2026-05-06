---
title: Port publishing
slug: port-publishing
source: network
confidence: high
tags: [docker, networking, ports, bridge, publish]
---

# Port publishing

Port publishing in Docker makes container ports reachable beyond the local Docker host and across Docker bridge networks. By default, containers on bridge networks expose their ports only to the host itself and to peers on the same network. Publishing a port extends that reachability to external clients (outside the host) and to containers attached to other bridge networks.

## Default port reachability (no publishing)

- Scope: containers attached to bridge networks (default or user-defined).
- Without any publish flags:
  - The container’s ports are accessible from the Docker host (via the container’s IP).
  - The container’s ports are accessible to other containers on the same Docker network.
  - The container’s ports are not accessible from outside the Docker host.
  - With default configuration, the container’s ports are not accessible from containers on different Docker networks.

## Publishing ports

- Use the --publish or -p flag with docker create or docker run to make a port available:
  - Outside the Docker host (to external clients on networks reachable from the host).
  - To containers attached to other bridge networks on the host.

- CLI usage patterns:
  - docker run --publish <mapping> <image>
  - docker create --publish <mapping> <image>
  - Shorthand: -p <mapping>

- Notes:
  - Port publishing applies to containers on bridge networks.
  - For details on mapping behavior, disabling port mapping, or using direct routing to containers, see the dedicated port publishing documentation referenced by Docker.

## Interaction with network modes and drivers

- Container network namespace sharing (container:<name|id>):
  - The following flags are not supported: --publish, --publish-all, --expose (as well as --add-host, --hostname, --dns*, --mac-address).
  - Implication: you cannot publish ports from a container that shares another container’s networking stack.

- Bridge networks:
  - Default and user-defined bridge networks support the default intra-network accessibility described above.
  - Publishing is the mechanism to cross the host boundary and bridge-network boundaries.

## Practical usage patterns

- Expose a service externally while connected to a user-defined bridge:
  - Ensure containers that need full internal connectivity share the same user-defined bridge network.
  - Publish only the ports that must be reachable from outside the host or from containers on other networks.

- Example command skeletons:
  - docker run --network <bridge-net> --publish <host_port>:<container_port> <image>
  - docker create --publish <host_port>:<container_port> <image>

## Constraints and considerations

- Only containers attached to bridge networks have the default behavior where their ports are visible to the host and same-network peers without publishing.
- Publishing modifies the reachability surface; review firewall and access controls on the Docker host for externally reachable services.
- When using container network namespace sharing (network mode container:...), port publishing is not available.

## Key Points

- Without publishing, container ports on bridge networks are reachable from the host and same-network containers, but not from outside the host or other networks.
- Use --publish or -p to make a container port available outside the host and to containers on other bridge networks.
- Port publishing is unsupported when a container uses another container’s network stack (network mode container:...).
- Publishing is the standard mechanism to cross network boundaries; advanced alternatives include disabling port mapping and using direct routing (see Docker’s port publishing docs).