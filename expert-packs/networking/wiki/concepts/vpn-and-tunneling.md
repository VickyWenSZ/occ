---
title: VPNs and Tunneling
slug: vpn-and-tunneling
source: computer-networking-basics
confidence: high
tags: [networking, vpn, tunneling, security, dns]
---

# VPNs and Tunneling

Virtual Private Networks (VPNs) and tunnels encapsulate one protocol within another to create virtual links across intermediate networks. VPNs typically add encryption and authentication to protect traffic over untrusted paths, while tunneling more generally refers to encapsulation with or without cryptographic protections. VPNs alter routing, address visibility, MTU, and DNS behavior; they can connect users to private networks (remote access) or connect networks to networks (site-to-site). VPNs secure traffic only between tunnel endpoints; beyond the endpoint, ordinary network rules and security apply.

## Core concepts

- Tunneling: encapsulation of one protocol inside another. Examples include carrying IP packets inside another IP or UDP flow, or encapsulating multi-protocol traffic within a protected session.
- VPN: a tunnel with security properties (encryption, integrity, endpoint authentication) connecting hosts or networks over untrusted media.
- Layer placement:
  - Network-layer tunnels (typical VPNs): carry IP traffic over IP/UDP/TCP-based transports; behave as virtual interfaces with IP routing.
  - Application-layer “VPN-like” access: clients connect through identity-aware proxies or gateways; traffic is proxied at Layer 7 rather than creating a general-purpose IP tunnel.
- Encapsulation overhead: headers/trailers from the outer transport reduce effective MTU, affecting large-packet behavior unless PMTUD/MSS clamping works.
- Security scope: a VPN secures traffic between the client and its VPN gateway. After decryption at the gateway, traffic follows normal routing/firewall policy, and may be unencrypted unless separately protected.

## Types and topologies

- Remote-access VPN (host-to-site)
  - Per-user/device connectivity into private resources.
  - Integrates authN/Z and posture (certificates, MFA, device checks, group policy).
  - Can be full-tunnel (default route via VPN) or split-tunnel (only selected prefixes via VPN).
- Site-to-site VPN (network-to-network)
  - Connects IP subnets across WAN/Internet.
  - Requires coordinated routing on both sides; firewalls must allow negotiated traffic classes.
- Host-to-host tunnels
  - Point-to-point protected links between two hosts for specific traffic.

## Full tunnel vs split tunnel

- Full tunnel
  - Most/all traffic uses the VPN as the default route.
  - Pros: centralized inspection/policy, uniform egress.
  - Cons: higher latency to public services, gateway load, bandwidth costs.
- Split tunnel
  - Only selected prefixes (internal subnets) traverse the VPN; other traffic exits locally.
  - Pros: better performance to public Internet, lower VPN load.
  - Cons: monitoring/DFIR complexity, policy gaps if routes/DNS are incomplete.
- DNS split tunneling
  - Internal domains resolve via corporate resolvers; public domains resolve normally.
  - Misconfiguration often breaks internal names even when IP routes exist.
  - Note: Some apps/browsers may use DNS-over-HTTPS independent of OS/VPN settings, bypassing split-DNS if not controlled.

## Protocol families and transports

- Common designs use: TLS-based tunnels, IPsec-like suites, WireGuard-like designs, or proprietary mechanisms.
- Transport considerations:
  - UDP transports are common; devices/firewalls maintain pseudo-state with timeouts that vary by platform.
  - TCP-over-TCP tunneling can suffer head-of-line blocking and “TCP meltdown” under loss; VPNs often prefer UDP underlays to avoid stacking congestion control.
  - Firewalls that block UDP can force protocol fallbacks or break tunnels depending on vendor/design.

## Routing behavior

- VPNs modify host and/or network routing tables:
  - Install routes for internal prefixes (split) or a default route (full).
  - Create a virtual interface bound to VPN-assigned addresses.
  - Longest-prefix match still applies; local connected routes usually win over less specific VPN routes.
- Return-path symmetry and state:
  - Statefully filtered edges must see both directions of a flow; asymmetric routing breaks state tracking.
- Cloud/security groups:
  - Cloud route tables, security groups, and NACLs are separate enforcement points; all must be aligned for reachability.

## Addressing and overlaps

- Overlapping private ranges break reachability:
  - Example: home LAN 192.168.1.0/24 and corporate 192.168.1.0/24 conflict; the local connected route typically wins, blackholing corporate peers.
  - Mitigations: renumbering, less-common pools, NAT within VPN design, or application-level access gateways.
- CGNAT/double NAT:
  - Carrier-grade NAT upstream or consumer double NAT complicates inbound connectivity and some VPN behaviors.
  - NAT traversal reliability depends on NAT type and policy.

## MTU, fragmentation, and MSS

- Encapsulation reduces effective MTU (e.g., Ethernet 1500 minus tunnel headers).
- Failure signatures:
  - Small packets (DNS, pings) work; large HTTPS/TLS flows stall or time out.
  - TCP handshakes may succeed; bulk transfers hang.
- Mitigations:
  - Ensure Path MTU Discovery works (ICMP Fragmentation Needed / ICMPv6 Packet Too Big must pass).
  - Apply TCP MSS clamping or set tunnel interface MTUs appropriately.

## DNS with VPNs

- VPNs often push DNS resolver IPs and search domains to clients.
- Split-horizon DNS:
  - Internal and external views differ by resolver; always test resolution through the client’s active resolver.
- Common pitfalls:
  - Missing DNS suffix prevents short names from resolving.
  - DoH-enabled apps ignore OS/VPN resolvers.
  - IPv6-only or IPv4-only answers create partial failures masked by Happy Eyeballs fallback.

## Security model and limitations

- A VPN:
  - Encrypts and authenticates the tunnel endpoints.
  - Does not guarantee service anonymity or endpoint trustworthiness beyond the tunnel.
  - Requires defense-in-depth: firewalls, least-privilege access, segmentation, identity-aware controls, and logging.
- Identity-aware access:
  - Remote access commonly integrates MFA, device posture, directory policy, and per-app authorization.
- Inspection scope:
  - Full-tunnel centralizes egress controls; split-tunnel requires distributed monitoring and clear policy boundaries.

## VPNs vs proxies

- Forward proxy:
  - Client sends requests to a proxy for egress control, filtering, and logging; can be explicit or intercepting.
  - TLS interception requires enterprise CA trust; otherwise, clients see certificate warnings.
- Reverse proxy/load balancer:
  - Fronts services for inbound access control, TLS termination, routing, WAF, and health checks.
- VPN:
  - Provides general IP connectivity (depending on policy) rather than application-specific proxying; both models can co-exist.

## Enterprise operations

- Common enterprise VPN issues:
  - Expired or misdeployed certificates, MFA failures, wrong group policy.
  - Missing split-tunnel routes, DNS suffix errors, overlapping home subnets.
  - MTU/PMTUD failures, overloaded gateways, blocked UDP.
- Policy and segmentation:
  - Grant least-privilege access to specific subnets/ports.
  - Enforce security groups/NACLs on ingress/egress of VPN gateways and workloads.
- Monitoring:
  - Track auth failures, route pushes, DNS overrides, tunnel lifetimes, UDP timeout behavior, and capacity.

## Troubleshooting playbooks

- Internal app fails while VPN “connects”
  - Confirm VPN interface and assigned IP.
  - Inspect routes for internal prefixes; ensure no conflicting local connected route.
  - Resolve the app hostname using the client’s active resolver; verify internal vs public answers.
  - Test TCP reachability to app port; capture packets to see SYN/SYN-ACK path.
  - Check MTU by testing with smaller packet sizes; apply MSS clamping if needed.
- DNS works at home but fails on VPN
  - Verify VPN-pushed DNS servers/suffixes; resolve fully qualified names.
  - Query internal names against corporate resolvers; compare with public/authoritative.
  - Check split-tunnel policies for DNS and routes; mitigate subnet overlaps.
- Ping works but HTTPS fails across VPN
  - ICMP success ≠ TCP success. Test TCP:443 to target.
  - Use verbose HTTP client to identify failure phase: DNS, TCP, TLS, or HTTP.
  - Verify certificate validity/SNI and proxy requirements.
- Timeouts vs refusals
  - Refused: target/host firewall actively rejects; often wrong port/bind/listener.
  - Timeout: likely silent drop (firewall/NAT), wrong route, or MTU blackhole.
- Tools and checks
  - ip/route table: confirm split/full-tunnel installation and longest-prefix effects.
  - Resolver checks (nslookup/dig) against the client’s configured resolver(s).
  - Traceroute (including TCP traceroute) to internal targets where allowed.
  - Packet capture (client/server) to verify encapsulated vs decapsulated flow and PMTUD signals.

## Textual flow: remote-access VPN

- Laptop connects to local network and gains IP (DHCPv4/SLAAC/DHCPv6).
- VPN client authenticates to VPN gateway; tunnel interface is created.
- Client receives internal IP, routes (split/full), and DNS settings.
- Packets to corporate prefixes enter the tunnel; gateway decapsulates and forwards according to corporate routing/firewalls.
- Responses return to the gateway, are encapsulated, sent over the Internet, and delivered to the client’s tunnel interface.

## Failure patterns to recognize

- Overlapping subnets: internal 192.168.1.0/24 conflicts with home 192.168.1.0/24; traffic misroutes locally.
- MTU blackholing: small requests work; large TLS/HTTP bodies fail.
- Split-DNS mismatch: internal names resolve publicly or not at all.
- UDP blocked/short timeouts: tunnels flap or long-lived idle sessions drop.
- Asymmetric routing/state loss: return traffic bypasses stateful filter, dropping legitimate flows.

## Design guidance (high-level)

- Prefer split vs full tunnel based on business need; match DNS policy accordingly.
- Plan address space to avoid overlaps with common home ranges; document VPN pools.
- Ensure PMTUD works end-to-end; clamp MSS where devices block ICMP.
- Treat VPN endpoints as security boundaries: enforce least-privilege security groups/ACLs, log, and monitor.
- Anticipate dual-stack: align IPv4/IPv6 routes, firewall policies, and load balancer behavior.

## Key Points

- VPNs are secure tunnels that modify routing, DNS, and MTU; they protect traffic only between tunnel endpoints, not beyond.
- Split tunneling and split DNS improve performance but increase operational complexity; misconfigurations are a leading cause of internal access failures.
- Encapsulation overhead commonly causes MTU/PMTUD issues; symptoms include small packets working while large transfers stall.
- Address overlap (e.g., 192.168.1.0/24 at home and corporate) and NAT behaviors (double NAT/CGNAT) frequently break reachability.
- Effective operations require aligned routes, DNS, firewall/security groups, and monitoring; common failures manifest as timeouts (drops/MTU) vs refusals (no listener/policy).