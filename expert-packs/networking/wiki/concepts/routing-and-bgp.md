---
title: Routing and BGP
slug: routing-and-bgp
source: computer-networking-basics
confidence: high
tags: [routing, bgp, internet, nat, troubleshooting]
---

# Routing and BGP

Routing moves IP packets between networks using forwarding decisions derived from routing tables. On the public Internet, inter-domain routing policy is coordinated with BGP (Border Gateway Protocol). This page compiles the fundamentals of routing (local and Internet-scale), NAT interactions, troubleshooting, and BGP’s role and risks, anchored to the source material.

## IP Routing Fundamentals

- Core concepts
  - Router: device with interfaces in multiple IP networks; forwards packets between them based on a routing table. Often includes firewall, NAT, VPN, DHCP, DNS forwarding, QoS, and monitoring.
  - Default gateway: next-hop router used when no more-specific route exists.
  - Routing table (RIB/FIB): collection of routes; forwarding uses longest prefix match (LPM). The most specific matching prefix wins (e.g., 10.1.2.0/24 over 10.0.0.0/8 over 0.0.0.0/0).
  - Hosts also have routing tables: local subnet route(s), default route, loopback, VPN and virtual network routes.
  - On-link vs off-link decisions:
    - If destination IP is in the local subnet, resolve the neighbor’s L2 address (ARP for IPv4; Neighbor Discovery for IPv6) and send directly.
    - If remote, resolve the default gateway’s L2 address and forward to it.
  - Subnetting: determines which addresses are considered local at L3; incorrect masks cause misclassification (e.g., ARP for off-link targets).

- IPv4 vs IPv6 routing behavior
  - IPv4 uses ARP for L2 resolution; IPv6 uses ICMPv6 Neighbor Discovery and Router Advertisements (no broadcast in IPv6).
  - ICMPv6 is essential; blocking it impairs IPv6 operation (neighbor discovery, router discovery, PMTUD).
  - IPv6 commonly uses /64 LAN prefixes; SLAAC and/or DHCPv6 assign/configure addresses and options.

- Longest prefix match examples
  - Given these routes:
    ```
    0.0.0.0/0 via 192.168.1.1 dev eth0
    10.0.0.0/8 via 192.168.1.254 dev eth0
    10.1.2.0/24 via 192.168.1.253 dev eth0
    ```
    - Destination 10.2.3.4 → 10.0.0.0/8
    - Destination 10.1.2.55 → 10.1.2.0/24
    - Destination 8.8.8.8 → 0.0.0.0/0

- NAT and routing
  - NAT/PAT alters IPs (and often ports) at boundaries. Source NAT (PAT) enables many private IPv4 hosts to share a public IP. Port forwarding maps inbound connections on a public IP:port to an internal IP:port.
  - NAT is distinct from firewalling; many devices combine both (stateful filtering plus translation), creating the impression NAT is the control. Inbound connections are typically blocked unless a mapping/state/forwarding rule exists.
  - Complications: double NAT, carrier-grade NAT, overlapping private ranges, NAT traversal (VoIP, P2P, VPNs), protocols embedding addresses in payloads.

- Internet routing characteristics
  - The Internet is a network of autonomous systems (ASes) with independent policies. Paths are typically asymmetric; the path from A→B may differ from B→A.
  - End-users do not control inter-domain routing; observed issues manifest as reachability holes, loss, latency spikes, or regional unavailability.

- VPNs affect routing on endpoints
  - Full-tunnel routes most or all traffic into the VPN; split-tunnel routes only selected prefixes while preserving direct Internet paths otherwise.
  - Common failure modes: missing split routes, DNS split-horizon issues, overlapping CIDRs, MTU blackholing due to tunnel overhead.

- Path MTU Discovery (PMTUD) and routing
  - Tunnels reduce effective MTU; blocking ICMP (IPv4 Frag Needed, IPv6 PTB) can cause stalls where small pings work but large transfers/HTTPS hang.

## Host Routing Behavior and Diagnostics

- What to verify on a host
  - IP address, mask/prefix, default gateway, DNS servers, VPN virtual interfaces, and per-interface routes.
  - Neighbor resolution: ARP cache or IPv6 neighbor table for gateway and local peers.
  - Listening services and local firewalls (for inbound testing).

- Representative commands
  - Windows: ipconfig /all, route print, tracert, Test-NetConnection.
  - Linux: ip addr, ip route (ip -6 route), ip neigh, ss -lntup, traceroute.
  - macOS/BSD: ifconfig, netstat -rn, traceroute.

- Minimal troubleshooting cascade
  1. Link up? (Wi-Fi association or Ethernet link)
  2. Valid IP? Correct subnet and gateway?
  3. Ping gateway (L2+L3 local check)
  4. Reach a known external IP (tests upstream routing/NAT)
  5. Resolve DNS and reach service IP/port (transport)
  6. TLS and application checks as applicable
  - Remember: ping results can be misleading (ICMP blocked or de-prioritized); traceroute shows only forward-path behavior for the probe type.

## NAT, Port Forwarding, and Return Path Considerations

- Outbound with PAT
  - Internal src (192.168.1.50:51544) → NAT maps to public (203.0.113.10:40001); NAT holds state for return traffic.
  - Failures: no NAT state (unsolicited inbound), NAT table exhaustion, wrong egress/default route, upstream/ISP blocks.

- Inbound with port forwarding
  - Public IP:443 → forward to 192.168.1.20:443
  - Preconditions: public reachability (no CGNAT or correct upstream forward), correct rule/protocol, stable internal IP, listening service, host firewall allowance, no ISP port block, correct return routing.
  - Security: exposing services increases risk; consider VPN, authenticated reverse proxies, zero-trust access.

## Internet-Scale Routing with BGP

- Role of BGP
  - Border Gateway Protocol is the primary inter-domain routing protocol. It distributes reachability for IP prefixes among autonomous systems and enables policy-based path selection.
  - It is not shortest-path routing; business relationships and configured preferences dominate.

- Policy and attributes (high-level)
  - Path decisions are driven by attributes and operator policy. Important concepts include:
    - AS path (sequence of ASNs traversed)
    - Local preference (operator-chosen intra-AS preference)
    - Multi-Exit Discriminator (MED; relative entry preference between neighbors)
    - NEXT_HOP, origin, and BGP communities (metadata signaling for policy)
  - Operators implement filtering, prefer customer routes over peers/transit, and may do traffic engineering (e.g., prepending, selective advertisement).

- Operational realities and risks
  - Asymmetry is normal; BGP determines only reachability and policy, not performance guarantees.
  - Incidents: route leaks, prefix hijacks, fat-fingered announcements, over-broad deaggregation. Effects: outages, misdirection, regional impact.
  - Defenses and hygiene:
    - Prefix filtering and max-prefix limits
    - Route origin validation (ROV) with RPKI
    - Monitoring/alerting, change control, staged rollouts, and careful operational controls

- Scope
  - Ordinary hosts and most enterprise edges do not run inter-domain BGP. BGP is run by ISPs, large networks, and between domains with independent policy. Enterprises may run interior routing (e.g., OSPF/IS-IS) and use static/defaults toward providers; some enterprises and data centers run BGP internally for scale/policy.

## Routing Interactions with Firewalls, Proxies, and Load Balancers

- Firewalls
  - Stateful filtering tracks flow state (TCP or pseudo-state for UDP). Asymmetric routing can break stateful enforcement; failover requires state sync to avoid session drops.

- Proxies and load balancers
  - Reverse proxies and L7/L4 load balancers alter observability and failure modes:
    - Health checks must match protocol/port/path/host.
    - Backend listening only on loopback or wrong port causes 502/503.
    - Security groups/NACLs must permit frontend→backend flows.
  - TLS termination points redefine trust boundaries; re-encryption and SNI/ALPN alignment matter.

## Common Routing Failure Modes from the Source

- Wrong or missing default gateway: local hosts reachable but Internet unreachable.
- Mis-subnetting: host ARPs for off-link destinations (fails) or sends on-link traffic via gateway.
- DNS vs routing confusion: IP reachability exists but names fail; or AAAA exists while IPv6 path/firewall is broken.
- NAT problems: double NAT, CGNAT blocking inbound, stale mappings, overlapping private ranges.
- Firewall problems: rule direction/protocol mismatch, rule shadowing, state table exhaustion, asymmetric routing across firewalls.
- MTU blackholes: small pings work; large HTTPS/TLS stalls due to blocked ICMP Frag Needed/IPv6 PTB or tunnel overhead.
- Internet routing asymmetry: traceroute asterisks or spikes at intermediate hops don’t prove data-plane loss; routers may rate-limit control-plane replies.

## Diagnostic Patterns and Playbooks

- Longest-prefix sanity
  - Inspect host route table for an unexpected more-specific route (e.g., added by VPN, container, or policy agent) shadowing the default.

- Timeout vs refused
  - Refused: target actively rejects (RST); likely no listener or host firewall reject.
  - Timeout: drop or blackhole; investigate security groups/NACLs, upstream ACLs, wrong IP, broken return path.

- Asymmetric behavior
  - Works IPv4, fails IPv6: check AAAA presence, IPv6 listener, firewall for IPv6, ICMPv6 allowance.
  - Works off VPN, fails on VPN: split tunnel routes and split DNS; overlapping subnets; MTU.

- Traceroute interpretation
  - Asterisks at a hop can be control-plane rate-limiting; if later hops respond normally, the hop likely forwards fine.
  - Final hop non-response with earlier responses can indicate destination filtering.

- NAT/forwarding
  - Inbound failure behind NAT: verify public IP presence (no CGNAT), forwarding rule, internal host bind address, and return route via the NAT device.

## Minimal Examples

- Linux host routing essentials
  ```
  # Show routes (IPv4/IPv6)
  ip route
  ip -6 route

  # Add a specific static route (example)
  sudo ip route add 10.20.0.0/16 via 192.168.1.254 dev eth0

  # Check neighbor resolution (IPv4/IPv6)
  ip neigh
  ip -6 neigh
  ```

- Distinguishing DNS vs routing vs transport
  ```
  # Name resolution
  dig www.example.com +short

  # Reach IP without DNS
  ping -c3 203.0.113.10

  # Test TCP reachability to 443
  # On Linux with tcptraceroute installed or traceroute -T
  traceroute -T -p 443 www.example.com
  ```

## Security and Integrity Considerations

- IPv6 operations require ICMPv6; blocking it breaks essential control (ND, RA, PTB).
- BGP integrity:
  - Deploy route filtering and RPKI-based Route Origin Validation where possible.
  - Monitor for leaks/hijacks; design cautious change control.
- Least privilege
  - Only permit necessary inter-subnet and inter-zone flows; avoid implicit any-any between user, server, and DMZ networks.

## Key Points

- Routing decisions use longest prefix match; correct subnetting and default gateway configuration are foundational to basic reachability.
- NAT is translation, not a firewall; inbound reachability through NAT requires explicit port forwarding and correct return paths.
- Internet routing is policy-driven and asymmetric; BGP coordinates inter-domain reachability and can fail via route leaks/hijacks; RPKI and filtering mitigate risk.
- IPv6 routing differs operationally (no ARP/broadcast; ICMPv6 and Neighbor Discovery are essential), and dual-stack misconfigurations are common.
- Effective troubleshooting isolates layers: validate link and local routing, then upstream routing/NAT, then DNS, transport, TLS, and application; interpret ping/traceroute with caution.