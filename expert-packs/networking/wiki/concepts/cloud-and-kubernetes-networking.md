---
title: Cloud and Kubernetes Networking
slug: cloud-and-kubernetes-networking
source: computer-networking-basics
confidence: high
tags: [cloud, kubernetes, networking, cni, ingress]
---

# Cloud and Kubernetes Networking

## Overview

Cloud and Kubernetes networking reuse IP, routing, and transport fundamentals while adding virtualization, software-defined control planes, dynamic service discovery, overlay/underlay decoupling, and identity-aware security. Key themes:
- Cloud virtual networks (VPC/VNet) provide private address space, subnets, route tables, gateways, NAT, and filtering (security groups, network ACLs). Public reachability is an explicit configuration of addressing + routes + L4/L7 policies.
- Load balancers and proxies front services, terminate TLS, route, enforce WAF/policy, and health-check backends. Health and routing abstractions decouple stable entry points from ephemeral compute.
- Containers isolate network stacks via namespaces; Kubernetes gives each pod an IP, exposes pods through Services, and integrates with cloud LBs/ingress for external access. A CNI plugin programs pod interfaces, addressing, routes/overlays, and NetworkPolicy where supported.
- DNS is central for service discovery (public, private, and cluster-internal). Split-horizon/DoH/enterprise resolvers and short TTLs interact with dynamic backends.
- Security spans multiple planes: cloud SGs/NACLs, host firewalls, Kubernetes NetworkPolicy, service mesh or reverse proxies, and zero-trust/identity gates. Least-privilege must be enforced at each layer.

This page compiles cloud and Kubernetes–specific designs, flows, failure modes, and troubleshooting from the source report and annex.

## Cloud Virtual Networks

### Model and primitives
- Logical isolation: provider-specific constructs (e.g., VPC/VNet) deliver L3 address space, subnets, routing domains, and attachment points for compute, load balancers, gateways, and private endpoints.
- Addressing/subnets:
  - Private IPv4 (RFC 1918) is typical; public IPv4 is scarce and policy-restricted; IPv6 global unicast increasingly available.
  - Subnets are routing boundaries; route tables define next hops (local, Internet gateway, NAT gateway, VPN/DirectConnect/ExpressRoute, transit/peering, firewall appliances, blackhole).
  - Overlapping CIDRs across environments (on-prem/home/VPN/cloud) break deterministic routing.
- Gateways:
  - Internet gateway: public ingress/egress for public IP–addressed resources per route/SG policy.
  - NAT gateway/instance: outbound IPv4 for private subnets without unsolicited inbound; return traffic allowed by state.
- Filtering:
  - Security groups (SGs): stateful, attached to ENIs/resources; describe allowed inbound/outbound flows (source/dest, protocol, port). Return traffic auto-permitted for established flows.
  - Network ACLs/subnet ACLs: often stateless; evaluated in order; can drop before SGs see packets.
  - Host firewalls: OS-level controls still apply.
- Private endpoints and private links:
  - Attach managed services (DB, object storage, queues) to private addresses inside the VPC/VNet.
  - DNS must resolve service FQDN to the private endpoint; bind private zones to the correct networks; ensure resolvers forward appropriately.
- Peering, transit, and hybrid:
  - VPC peering is commonly non-transitive; use transit gateways/hubs for hub-and-spoke.
  - Route propagation and filtering are explicit; overlapping prefixes prevent peering.
  - Hybrid links (VPN, private circuits) require coordinated routing/DNS/firewall policies.

### Load balancers and proxies
- L4 vs L7:
  - L4 LB forwards TCP/UDP flows based on 5-tuple; preserves application transparency; health checks often TCP-level or basic HTTP.
  - L7 LB/reverse proxy understands HTTP(S); routes on host/path/headers, terminates TLS, compresses/caches, enforces WAF/rate limits, and injects observability.
- TLS termination:
  - Terminates at the edge; optional re-encryption to backends; SNI/ALPN select cert/upstream. Misaligned termination causes protocol/cert/redirect issues.
- Health checks:
  - TCP-level proves port open only; HTTP-level verifies path/status; deep checks validate dependencies but risk cascading outages if too strict.
- Common LB failure patterns (from source):
  - Wrong listener port/protocol or missing/incorrect certificate.
  - Target group port mismatch; backend listening only on localhost; wrong host header.
  - Health check path/status/Host/TLS mismatch.
  - SGs/NACLs block LB-to-backend or backend-to-LB return.
  - Subnet/AZ attachment incomplete; no healthy targets; redirects to internal hostnames.

### Egress and DNS design
- Egress control:
  - Outbound access may require SG/NACL allows, NAT gateway presence, proxies, and domain-based allowlists; enforce least privilege at egress.
- DNS:
  - Choose resolvers (cloud-provided, enterprise, DoH) per network segment.
  - Implement split-horizon/private zones for private endpoints/services.
  - Beware negative caching, TTL planning, and app-side caching with dynamic backends.

## Container Networking

### Namespaces and bridges
- Network namespaces isolate interfaces/routes/firewall/sockets. “localhost” is per-namespace.
- Bridge networks connect containers on a host via a virtual L2 bridge; NAT/published ports expose services externally.
- Pitfalls:
  - Process listens on 127.0.0.1 inside container → not reachable from host/network unless proxied.
  - Image EXPOSE is metadata; explicit port publishing is required at runtime.

## Kubernetes Networking

### Pod networking model
- Each pod gets an IP in the cluster network. Containers in a pod share a namespace; inter-pod communication uses pod IPs (subject to policy).
- Pod IPs are ephemeral; do not depend on them for stable addressing.

### Service abstraction
- Service provides stable virtual access to pod backends by label selection:
  - ClusterIP: in-cluster virtual IP only.
  - NodePort: opens a port on every node, forwards to Service.
  - LoadBalancer: provisions a cloud/external LB to reach the Service.
  - ExternalName: DNS alias to external FQDN.
- Endpoints/EndpointSlice track pod IPs for a Service. Empty endpoints often mean selector-label mismatch or failing readiness.
- Health/readiness:
  - Readiness probes gate inclusion in Service endpoints; failing probes remove pods from LB rotation even if containers are running.

### Ingress
- Ingress is an API to manage external HTTP/HTTPS access by host/path rules; requires an ingress controller.
- Typical issues:
  - No controller or wrong ingressClass.
  - DNS points to wrong LB/endpoint.
  - TLS secret missing/wrong; SNI/cert mismatch.
  - Host/path rules don’t match request.
  - Backend Service name/port wrong or has no endpoints.

### Service discovery
- Cluster DNS (e.g., CoreDNS) resolves Services and pods:
  - Names: service, service.namespace, service.namespace.svc.cluster.local (cluster domain configurable).
- Failure modes:
  - CoreDNS down/misconfigured; DNS blocked by NetworkPolicy; wrong DNSPolicy; aggressive app caching; selectors yield no endpoints.

### CNI plugins and data plane
- CNI is the interface by which Kubernetes configures pod networking:
  - Responsibilities include IPAM, interface setup, routing/overlay/encapsulation, optional encryption, and NetworkPolicy enforcement.
  - Inter-node connectivity may be routed or encapsulated (overlay). MTU must account for encapsulation overhead.
- NetworkPolicy:
  - Label-based allow rules for ingress/egress at pod level; only effective if CNI enforces policies.
  - Common mistakes: wrong namespace/pod selectors, missing egress rules (including DNS), assuming global scope, or relying on unsupported features.

### Cloud integration
- Service type LoadBalancer maps to cloud LB; SGs must allow LB-to-node and node-to-pod paths; health checks must target correct ports/paths.
- Ingress controllers frequently program cloud LBs; correctness depends on controller class, annotations, and cloud provider integration.

## End-to-End Flows (diagram-ready)

### Kubernetes external exposure (from annex)
- Entities: External client → Cloud LB/Ingress endpoint → Ingress controller → Kubernetes Service → EndpointSlice → Pod → Container process.
- Flow:
  1) Client resolves external hostname and connects to LB/Ingress.
  2) TLS may terminate at LB or Ingress; host/path rules route to Service.
  3) Service selects pods via labels; endpoints provide backend IP:port.
  4) Pod receives traffic; response returns via cluster network to LB and client.
- Notes: Pod health gates endpoints; binding to localhost inside container breaks reachability; SG/NACL/NetworkPolicy must allow all segments.

### Internet gateway vs NAT gateway (from annex)
- Public subnets route 0.0.0.0/0 to Internet gateway; resources need public IP + SG to be reachable.
- Private subnets egress via NAT gateway; no unsolicited inbound. Lack of NAT route breaks package updates/egress APIs.

## IPv6 and Dual-Stack in Cloud/Kubernetes

- IPv6:
  - Global unicast preferred; no broadcast; Neighbor Discovery/ICMPv6 essential; blocking ICMPv6 breaks basic functions.
  - Firewalls replace NAT as exposure control; unsolicited inbound typically blocked by default policies.
- Dual-stack pitfalls:
  - AAAA exists but IPv6 routing/firewall absent; clients prefer IPv6 (Happy Eyeballs mitigates delays).
  - Backend not listening on IPv6; monitoring/security rules applied to IPv4 only.
  - K8s and cloud LB config must align for both families.

## MTU, Overlays, and VPNs

- Overlays (encapsulation) and VPNs reduce effective MTU. If PMTUD/ICMP is filtered, large transfers stall while small pings succeed.
- Symptoms: TCP handshakes succeed; TLS/HTTP stalls; inconsistent site reachability.
- Fixes: Adjust interface/tunnel MTU, enable MSS clamping, allow ICMP Fragmentation Needed / ICMPv6 Packet Too Big.

## Security Architecture

- Defense-in-depth across planes:
  - Cloud: SGs (stateful), NACLs (often stateless), private endpoints, WAF, DDoS controls.
  - Hosts: OS firewalls.
  - Kubernetes: NetworkPolicy, admission policies, identity-aware proxies/ingress authn, service meshes (if used).
- Least privilege:
  - Constrain LB→app ports, app→DB ports; restrict admin to management networks or identity-aware gateways; tighten egress.
- Zero trust:
  - Network location is not trust; decisions incorporate user/device identity, context, MFA, posture, and continuous verification; TLS everywhere.

## Common Failure Modes (cloud/K8s-focused)

- Cloud networking
  - No NAT gateway route for private subnets; egress fails.
  - Public IP assigned but SG blocks inbound; or upstream ISP blocks.
  - Peering without route propagation; overlapping CIDRs prevent connectivity.
  - Private endpoint DNS still resolves to public address; private zone not linked; resolvers not forwarding.
  - LB 502/503: unhealthy targets, wrong health check, protocol or host header mismatch, backend listening on localhost.
- Container/Kubernetes
  - Service has no endpoints (label mismatch, readiness failing).
  - Container bound to 127.0.0.1; exposed but unreachable from network.
  - Ingress present but no controller/ingressClass; DNS points wrong; TLS secret invalid.
  - NetworkPolicy blocks DNS or backend ports; CNI doesn’t enforce policies; MTU with encap blackholes large packets.
  - Dual-stack asymmetry: AAAA published, IPv6 path/firewall missing.

## Troubleshooting Playbooks

- LB returns 502/503 (from annex)
  - Verify listener protocol/port and certificate/SNI.
  - Confirm target port and health check path/status/Host.
  - Check backend listens on correct interface/port; SG/NACL allow LB source; align HTTP vs HTTPS end-to-end.
- Service unreachable in Kubernetes
  - Check Service selector vs pod labels; endpoints not empty.
  - Verify readiness probes; failing pods removed from endpoints.
  - Confirm container bind address; verify NetworkPolicy allows traffic; ensure cluster DNS resolving service name.
- Ingress not routing
  - Ensure controller installed; ingressClass matches.
  - Check DNS → LB; TLS secret valid; rules match Host/path.
  - Validate backend Service/port exist and has endpoints.
- Private endpoint not working
  - Confirm DNS resolves to private IP; private zone linked; resolvers forward correctly.
  - Check SGs for endpoint interface; routes from client subnet to endpoint.
- Egress failing from private subnet
  - Validate route to NAT gateway; NAT in correct subnet/AZ; SG/NACL allow outbound and return.
  - If proxy required, configure app/system proxy and allow DNS/OCSP where applicable.
- MTU suspicion
  - Test with smaller payloads; observe stalls on large transfers.
  - Allow ICMP(IPv4/IPv6) PTB; clamp MSS or lower MTU on tunnel/overlay interfaces.

## Diagnostic Anchors (tools mapped to context)

- dig/nslookup: validate split DNS (public vs private vs cluster DNS), CNAME chains, TTLs.
- curl -v: phase-by-phase failures (DNS, TCP, TLS, HTTP); SNI/Host header testing; distinguish proxy vs origin errors.
- ping/traceroute: reachability/path hints; prefer TCP/UDP traceroute modes to match target protocol when possible.
- ss/netstat/ip: confirm listeners (bind address), routes/default gateway, neighbor/ARP/ND state.
- Packet capture (tcpdump/Wireshark): SYN seen? SYN-ACK returning? Health check requests/responses? ICMP PTB?

## Design Patterns and Guidance

- Public-facing apps:
  - DNS → cloud LB (TLS terminate, WAF) → Ingress/Service → pods; enforce SG/NACL/NetworkPolicy; implement readiness; instrument with health checks and logs.
- Private apps:
  - Private DNS and private endpoints; Ingress inside private networks or identity-aware proxies; egress controlled via NAT/proxy with least privilege.
- Hybrid:
  - Transit hub; explicit route propagation; non-overlapping CIDRs; private DNS sharing/forwarding; consistent policy across on-prem/cloud/cluster.
- Reliability:
  - Multi-AZ subnets and LBs; health checks with conservative depth; avoid cache-busting low TTLs unless necessary; plan MTU for overlays.

## Key Points
- Cloud networking composes VPC/VNet addressing, explicit routing, gateways (Internet vs NAT), and multi-layer filtering; public reachability requires all layers to align.
- Kubernetes decouples stable Service/Ingress frontends from ephemeral pods; CNI implements pod networking and (optionally) NetworkPolicy enforcement.
- DNS (public/private/cluster) and health checks are the control-plane glue; most outages are misroutes, mis-binds (localhost), mis-labeled Services, or policy blocks (SG/NACL/NetworkPolicy).
- Overlays, VPNs, and dual-stack add MTU and IPv6-specific dependencies (ICMPv6, AAAA readiness) that regularly cause partial failures.
- Troubleshoot by isolating planes: DNS → routing → transport → TLS → HTTP/app, checking every enforcement point (LB, SG/NACL, host firewall, NetworkPolicy, proxy) along the path.