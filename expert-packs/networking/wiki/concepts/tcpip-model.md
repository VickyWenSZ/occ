---
title: TCP/IP Model
slug: tcpip-model
source: computer-networking-basics
confidence: high
tags: [networking, layering, tcp, ip, troubleshooting]
---

# TCP/IP Model

## Overview
The TCP/IP model is the practical layering framework that reflects the Internet protocol suite as deployed. It organizes network functions into layers that provide services upward and consume services from below. Unlike the OSI seven-layer model (primarily pedagogical), the TCP/IP model aligns with real protocols and operational components, making it the preferred mental model for modern Internet architecture and troubleshooting.

Key properties:
- Encapsulation: each layer wraps payloads with its own headers (and sometimes trailers), enabling modularity and multiplexing.
- Independence: layers can evolve independently (e.g., IP over Ethernet or Wi‑Fi; HTTP over TCP or QUIC).
- Diagnostics: isolating faults by layer (link, IP, transport, application) is an effective troubleshooting approach.
- Cross-layer realities: some protocols blur boundaries (e.g., TLS between app/transport; QUIC implements transport over UDP; DNS is application-layer yet foundational).

## Layer taxonomy
Two common presentations exist:

- Four-layer model:
  - Link layer: local network access and delivery over a medium (e.g., Ethernet, Wi‑Fi, PPP).
  - Internet layer: logical addressing and routing across networks (IP; IPv4/IPv6; ICMP).
  - Transport layer: end-to-end process communication (TCP, UDP; QUIC runs over UDP).
  - Application layer: end-user and infrastructure protocols (DNS, HTTP, SMTP, SSH, DHCP, NTP, etc.).

- Five-layer variant (teaching convenience):
  - Physical
  - Data link
  - Network (maps to Internet layer)
  - Transport
  - Application

The 4-layer TCP/IP model is most accurate for operational networking; the 5-layer split clarifies media/signaling versus link framing.

## Layer responsibilities and common protocols

### Link layer (local delivery)
Responsibilities:
- Framing, link addressing, medium access, local error detection, VLAN tagging, and on-link neighbor resolution interactions.
- Local-only scope; routers decapsulate/recapsulate per-hop.

Technologies and mechanisms:
- Ethernet (802.3), Wi‑Fi (802.11), PPP; switches; VLANs (802.1Q); MAC addresses; ARP (for IPv4); ICMPv6 Neighbor Discovery interactions (for IPv6).
- MTU considerations (e.g., 1500 bytes typical for Ethernet IP payload; jumbo frames in controlled domains).
- Wi‑Fi differs from Ethernet: shared half-duplex medium, contention, interference.

Diagnostics/failures:
- Link down, wrong VLAN, ARP/ND failure, duplex/MTU mismatch, Wi‑Fi association/auth failures, interference/roaming issues.

### Internet layer (IP routing)
Responsibilities:
- Logical addressing, subnetting, routing, fragmentation behavior (IPv4), error signaling (ICMP/ICMPv6), cross-network forwarding.
- Determines next-hop and whether destination is local vs remote.

Core protocols:
- IPv4 (32-bit addressing; private RFC1918 ranges; NAT common due to address scarcity).
- IPv6 (128-bit addressing; no broadcast; ICMPv6 is essential; SLAAC/DHCPv6; global unicast, ULA, link-local; RAs/ND).
- ICMP/ICMPv6 for control and diagnostics.

Diagnostics/failures:
- Wrong/missing IP/gateway, no default route, asymmetric routing, blocked ICMPv6, overlapping subnets (esp. VPN/home), NAT traversal issues, MTU blackholing.

### Transport layer (end-to-end process communication)
Responsibilities:
- Multiplexing by ports; connection establishment/teardown; reliability, ordering, flow control (TCP); congestion control (network-friendly rate adaptation).

Core protocols:
- TCP: connection-oriented, reliable byte-stream; three-way handshake; sequence/ACKs; flow and congestion control (Reno, CUBIC, BBR, etc.).
- UDP: connectionless datagrams; no built-in reliability/ordering; widely used by DNS, NTP, media, tunneling.
- QUIC: transport-like behavior over UDP, integrating security and reliability; used by HTTP/3 over UDP 443.

Diagnostics/failures:
- Connection refused (RST), timed out (filtered/blackhole), port blocked, stateful firewall/NAT timeouts, protocol/cipher mismatches (TLS on top), excessive loss/RTT limiting throughput.

### Application layer (protocol semantics)
Responsibilities:
- Define data semantics and workflows (naming, web, mail, auth, time, config).

Examples:
- DNS (A/AAAA/CNAME/MX/TXT; recursive vs authoritative; TTL/caching; split DNS).
- HTTP/HTTPS (HTTP/1.1, HTTP/2, HTTP/3 over QUIC; status codes; proxying; CDNs).
- TLS for channel security and authentication (certificates, SNI, ALPN).
- DHCP/DHCPv6; NTP; SMTP/IMAP/POP3; SSH; and many others.

Diagnostics/failures:
- DNS resolution errors (NXDOMAIN/SERVFAIL/REFUSED/timeout), certificate validation failures (expiry, hostname, chain, trust), proxy/WAF policy blocks, L7 load balancer routing/health-check misconfig.

## Encapsulation and data flow
Typical on-the-wire stack for a web transaction:
- Application: HTTP request/response
- Optional security framing: TLS records (HTTPS)
- Transport: TCP segments (or QUIC streams over UDP datagrams)
- Internet: IP packets (IPv4 or IPv6; ICMP/ICMPv6 for control)
- Link: Ethernet or 802.11 frames

Example (illustrative):
```
HTTP GET /                 ← application
TLS record                 ← security (HTTPS)
TCP src:49152 → dst:443    ← transport (or QUIC over UDP)
IP src:192.168.1.50 → 203.0.113.10 (or IPv6)  ← internet
Ethernet src:MAC_A → MAC_GW (hop-by-hop)       ← link
```
At each router hop: decapsulate link frame → forward IP packet → encapsulate for next link. IP src/dst remain stable across hops; link-layer addresses change.

## TCP/IP vs OSI (practical mapping and limits)
- The OSI model provides terminology (L2 issues: VLAN/Wi‑Fi; L3: IP/routing; L4: ports/connections). Real deployments align better with TCP/IP’s four layers.
- Cross-layer boundaries exist:
  - TLS often “between” transport and application.
  - QUIC implements transport-like features over UDP.
  - MPLS is often called “Layer 2.5” in OSI framing terms.
  - Firewalls/load balancers inspect L3/L4 and sometimes L7 simultaneously.
- Treat OSI as a taxonomy; use TCP/IP as the blueprint for operational Internet systems.

## Troubleshooting with the TCP/IP model
Systematic approach (bottom-up or symptom-driven):
1. Link layer:
   - Is the interface up/associated? Correct VLAN/SSID/auth? ARP/ND resolving? MTU sane?
2. Internet layer:
   - Valid IP? Correct subnet/gateway? Can reach default gateway? Can reach a known external IP? ICMPv6 permitted for IPv6?
3. Name resolution (app dependency):
   - Does DNS resolve via the client’s resolver path? Are A/AAAA both correct? Split DNS/VPN behavior?
4. Transport:
   - Is the target port reachable? Refused vs timed out? Firewall/security-group/NAT path intact? Asymmetric routing?
5. Security/application:
   - TLS certificate validity (expiry, SAN/hostname, chain, SNI, client clock)?
   - HTTP status and proxy/load balancer routing/health?

Useful tools by layer:
- Link: ip/ifconfig/ipconfig; ip link; Wi‑Fi tools; ping to default gateway.
- Internet: ip route; traceroute/tracert; ping/ICMPv6; ip neigh/ARP table.
- Transport: ss/netstat; Test-NetConnection; TCP traceroute; packet capture (tcpdump/Wireshark).
- Application/security: nslookup/dig; curl -v; browser dev tools; load balancer health/status.

## Common failure patterns across layers
- Link: wrong VLAN, Wi‑Fi interference/roaming, ARP/ND stale/poisoned entries, MTU mismatch.
- Internet: missing/wrong default gateway, blackholed route, blocked ICMPv6, overlapping private subnets (VPN vs home).
- Transport: firewall silently dropping (timeout) vs server rejecting (RST/refused), NAT table exhaustion/timeouts, UDP flow state expiry.
- Application/security: DNS NXDOMAIN/SERVFAIL, stale negative cache, TLS hostname mismatch/expired/untrusted chain/missing intermediate, SNI misroute, HTTP 502/503 from proxy/LB health failures.

## Security and middleboxes in the TCP/IP model
- NAT (IPv4): address/port translation (PAT) for egress; not inherently a firewall, though commonly paired with stateful filtering.
- Firewalls: L3/L4 stateful filtering; L7 inspection/policy in next-gen devices; cloud security groups/ACLs with state and directionality.
- Proxies/load balancers: forward vs reverse; L4 vs L7; TLS termination and re-encryption; health checks; header-based routing; preserve client IP via headers with care.
- VPNs/tunnels: add encapsulation and MTU overhead; full vs split tunnel; DNS split-horizon; overlapping address pitfalls.

## Selected standards references (from the suite)
- IP: IPv6 (RFC 8200); IPv4 original (RFC 791), with numerous updates.
- ICMPv6 and Neighbor Discovery: RFC 4861.
- TCP: RFC 9293.
- QUIC: RFC 9000; HTTP/3 mapping: RFC 9114.
- TLS 1.3: RFC 8446.
- HTTP semantics: RFC 9110; HTTP/2: RFC 9113.
- DNS: RFC 1034, RFC 1035.
- DHCPv4: RFC 2131; DHCPv6: RFC 8415.
- Ports: IANA Service Name and Port Number Registry.

## Key Points
- The TCP/IP model’s four layers (link, internet, transport, application) match real Internet architecture and are superior for practical troubleshooting.
- Encapsulation and per-hop link-layer rewrites enable IP routing while preserving end-to-end IP/transport identity.
- Many real protocols cross idealized boundaries (TLS, QUIC), so treat layers as guides, not rigid walls.
- A disciplined, layer-by-layer diagnostic method (link → IP → DNS → transport → TLS/app) isolates most network failures efficiently.
- OSI is useful vocabulary; TCP/IP is the operational blueprint for modern networks.