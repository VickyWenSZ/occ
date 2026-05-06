# Wiki Index

Last updated: 2026-05-04  
Total pages: 39

## Pages

| File | Title | Summary |
|------|-------|---------|
| concepts/compose-cli.md | Compose CLI (docker compose) |  |
| concepts/compose-configs.md | Configs |  |
| concepts/compose-file.md | Compose file (compose.yaml) |  |
| concepts/compose-file-merging.md | Multiple Compose files and merging |  |
| concepts/compose-fragments-and-extensions.md | Fragments, includes, and extensions |  |
| concepts/compose-networks.md | Networks |  |
| concepts/compose-project.md | Project and resource isolation |  |
| concepts/compose-secrets.md | Secrets |  |
| concepts/compose-services.md | Services |  |
| concepts/compose-specification.md | Compose Specification |  |
| concepts/compose-volumes.md | Volumes |  |
| concepts/connecting-multiple-networks.md | Connecting containers to multiple networks | Attaching a container to multiple networks (possibly of different driver types), how routing chooses destinations and the concept of gateway selection and gw-priority to control the default gateway. |
| concepts/connecting-to-multiple-networks.md | Connecting containers to multiple networks |  |
| concepts/container-network-sharing-mode.md | Container network sharing mode | The container:<name/id> networking mode that attaches a container to another container's network namespace and the limitations on which docker run flags can be used in this mode. |
| concepts/container-networking.md | Container networking |  |
| concepts/container-networking-overview.md | Container networking overview | High-level description of how containers connect and communicate with each other and external network services, and what networking primitives a container sees (interfaces, IPs, gateways, routing, DNS). |
| concepts/custom-hosts-and-etc-hosts.md | Custom hosts and /etc/hosts behavior |  |
| concepts/default-bridge-network.md | Default bridge network | The built-in bridge network created when Docker Engine starts that provides containers with outbound network access via IP masquerading when no --network option is specified. |
| concepts/dns-resolution-and-embedded-dns.md | DNS resolution and embedded DNS | How containers inherit or override DNS settings, Docker's embedded DNS server at 127.0.0.11 for custom networks, and docker run flags (--dns, --dns-search, --dns-opt) to control resolution. |
| concepts/dns-services.md | DNS services in containers |  |
| concepts/docker-cli.md | Docker client (docker CLI) |  |
| concepts/docker-container.md | Docker container |  |
| concepts/docker-desktop.md | Docker Desktop |  |
| concepts/docker-engine.md | Docker Engine |  |
| concepts/docker-image.md | Docker image |  |
| concepts/docker-service.md | Docker service |  |
| concepts/docker-software.md | Docker (software) |  |
| concepts/docker-swarm.md | Docker Swarm |  |
| concepts/dockerd-daemon.md | Docker daemon (dockerd) |  |
| concepts/ip-addresses-and-hostnames.md | IP addresses and hostnames | IP address allocation per network (IPv4/IPv6), specifying addresses with --ip/--ip6, container hostname defaults and overrides with --hostname, and network aliases with --alias. |
| concepts/libcontainer.md | libcontainer |  |
| concepts/linux-kernel-features-for-containers.md | Linux kernel features for containers |  |
| concepts/moby-project.md | Moby project |  |
| concepts/network-drivers.md | Network drivers | Built-in and platform-specific drivers (e.g., bridge, host, none, overlay, ipvlan, macvlan) that define how Docker networks behave and integrate with host and external networks. |
| concepts/port-publishing.md | Port publishing |  |
| concepts/published-ports-and-port-mapping.md | Published ports and port mapping | How container ports on bridge networks are exposed to the Docker host and other containers, and how to use --publish/-p to make ports accessible outside the host or across networks. |
| concepts/subnet-allocation.md | Subnet allocation and default address pools |  |
| concepts/subnet-allocation-and-address-pools.md | Subnet allocation and address pools | Explicit and automatic subnet assignment for networks, Docker's default-address-pools configuration, how Docker selects subnets, and considerations for dynamic IPv6 allocation and unspecified-address requests. |
| concepts/user-defined-networks.md | User-defined networks | Custom networks you create to group containers, enabling name-based discovery and controlled inter-container communication compared to the default bridge. |
