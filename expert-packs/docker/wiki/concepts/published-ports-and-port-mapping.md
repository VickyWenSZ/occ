---
title: Published ports and port mapping
slug: published-ports-and-port-mapping
source: network
confidence: high
tags: [docker, networking, ports, bridge, nat]
---

# Published ports and port mapping

Published ports and port mapping control inbound reachability to container services. On Docker’s bridge networks, container ports are always reachable from the host and from containers on the same network. By default, they are not reachable from outside the host or from containers attached to other networks. Publishing a port with --publish/-p binds a host port to a container port, making the service accessible externally and to containers on other bridge networks.

## Default reachability (bridge networks)

- Outbound: Containers have outbound connectivity by default (via masquerading/NAT on the Docker host).
- Inbound, no publishing:
  - Reachable from the Docker host: All container ports on bridge networks are accessible from the host (e.g., via the container’s IP on the bridge).
  - Reachable from peers on the same bridge network: Containers can connect to each other using container IPs (and names for user-defined bridges).
  - Not reachable from outside the host: No inbound access from external networks.
  - Not reachable from containers on other networks (by default): Network isolation prevents cross-network container-to-container access.
- Network context: These behaviors apply to containers joined to bridge networks (default or user-defined). Other drivers have different semantics.

## Publishing ports with --publish/-p

- Purpose: Expose a container port beyond the host-bridge boundary.
- Effect:
  - Makes the target container port available “outside the host” (e.g., to external clients) by binding a host port to the container port.
  - Enables access from containers on other bridge networks (they can reach the published host port).
- Usage scope: Supported when creating or running containers via docker create or docker run.
- Control:
  - Use --publish or -p flags to publish ports.
  - For additional details, disabling port mapping, or using direct routing to containers, see “port publishing” documentation (not covered here).

Example (basic):
```
docker run -d --name web -p 8080:80 myimage
# Host port 8080 is published and mapped to container port 80.
# External clients and containers on other bridge networks can reach the service via host:8080.
```

## Interactions with network modes

- Container network namespace sharing (container: mode):
  - When using --network container:<name|id>, the following flags are not supported: --publish, --publish-all, --expose (among others).
  - Implication: You cannot publish or expose ports directly for containers that share another container’s network stack.
- Host and other drivers:
  - Docker provides multiple network drivers (e.g., bridge, host, none, overlay, ipvlan, macvlan). Published port behavior described here is scoped to bridge networks; semantics differ for other drivers. Refer to their driver-specific documentation.

## Access patterns summary

- Without publishing:
  - Host → Container: yes (on bridge)
  - Same bridge network → Container: yes
  - Other networks → Container: no (by default)
  - External hosts → Container: no
- With publishing:
  - Host/external hosts/other networks → Host published port → Container port: yes

## Examples

- Run a service reachable only from the host and same-network containers:
```
docker run -d --name api myimage
# Ports are not exposed outside the host. Host and same bridge peers can reach the container’s IP:port.
```

- Publish a service to external clients and other networks:
```
docker run -d --name api -p 8443:443 myimage
# Now available on host:8443 from external networks and from containers on other bridge networks.
```

- Using container network namespace sharing (cannot publish):
```
docker run -d --name redis redis --bind 127.0.0.1
docker run --rm -it --network container:redis redis redis-cli -h 127.0.0.1
# --publish/--publish-all/--expose are not supported with --network container:...
```

## Key Points

- On bridge networks, all container ports are reachable from the Docker host and same-network containers without publishing.
- By default, container ports are not reachable from outside the host or from containers on other networks.
- Use --publish/-p to bind a host port to a container port, enabling access from external clients and other bridge networks.
- Publishing/exposing ports is not supported in --network container:<name|id> mode.
- Published port behavior described here applies to bridge networks; other drivers have different connectivity models.