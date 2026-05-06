---
title: OSI Seven-Layer Model
slug: osi-model
source: computer-networking-basics
confidence: high
tags: [networking, osi, layers, tcp/ip]
---

# OSI Seven-Layer Model

The OSI (Open Systems Interconnection) model is a seven-layer conceptual framework for reasoning about computer networking. It separates responsibilities into layers that provide services upward and consume services downward. The modern Internet is designed and operated according to the TCP/IP model, not as a literal implementation of OSI; however, OSI remains a valuable taxonomy for vocabulary, education, and systematic troubleshooting.

## Purpose and scope

- Provide a shared vocabulary: “Layer 2 issue” vs “Layer 3 issue,” etc.
- Enable modular reasoning: each layer solves a class of problems and exposes a service boundary.
- Support troubleshooting: test from lower layers upward or isolate the failing layer from symptoms downward.
- Caveat: real-world protocols frequently cross or blur OSI boundaries; treat OSI as a teaching model, not an exact blueprint.

## The seven layers (responsibilities, data units, examples)

- Layer 1 — Physical
  - Responsibility: transmission of raw bits over media (copper, fiber, RF). Signaling, line coding, power levels, frequency/bandwidth, connectors, PHY link status.
  - Data unit (informal): bits.
  - Examples: 100/1000BASE-T over twisted pair; optical Ethernet PHYs; Wi‑Fi RF PHY; cable/DSL/ONT physical interfaces; link up/down LEDs.
  - Notes: errors here manifest as no link, high error rates, or unstable connectivity before framing.

- Layer 2 — Data Link
  - Responsibility: local link framing, addressing, media access, error detection, and delivery within a broadcast domain. VLAN tagging, MTU, FCS.
  - Data unit: frame.
  - Examples: Ethernet 802.3, Wi‑Fi 802.11, MAC addressing, VLAN (802.1Q), switches/bridges, AP association, IGMP snooping.
  - Adjacent mechanisms: ARP (IPv4) resolves L3->L2 addresses over L2; Neighbor Discovery (IPv6) replaces ARP using ICMPv6.

- Layer 3 — Network
  - Responsibility: logical addressing and routing between networks; forwarding, subnetting, default gateways, path selection.
  - Data unit: packet (IP).
  - Examples: IPv4, IPv6, ICMP/ICMPv6, routers, longest-prefix match, default route 0.0.0.0/0, SLAAC, DHCPv6, CIDR.
  - Notes: NAT alters addressing at L3/L4 boundaries in many IPv4 deployments; IPv6 favors end-to-end routability with firewalls for policy.

- Layer 4 — Transport
  - Responsibility: process-to-process communication; ports; multiplexing; reliability, ordering, flow control, congestion control (depending on protocol).
  - Data unit: segment (TCP), datagram (UDP).
  - Examples: TCP (reliable byte stream, three-way handshake, flow + congestion control), UDP (connectionless datagrams), QUIC (transport-like reliability/security over UDP).
  - Notes: port numbers demultiplex services; “TCP is reliable” means bytes are delivered to the peer stack, not that the application succeeded.

- Layer 5 — Session (conceptual in OSI)
  - Responsibility: session establishment/management/teardown, checkpoints, dialog control.
  - Practical mapping: not a distinct layer in TCP/IP. Some “session-like” behaviors exist in application protocols and security layers.
  - Examples often cited: TLS “sessions” (resumption, tickets), RPC session semantics; in practice these straddle traditional layers.

- Layer 6 — Presentation (conceptual in OSI)
  - Responsibility: data representation, serialization, compression, encryption, character sets.
  - Practical mapping: encoding/serialization (e.g., JSON, Protobuf) and security (e.g., TLS) often live near applications.
  - Examples often cited: ASN.1, BER/DER, TLS; in TCP/IP, TLS commonly sits “between” L4 and L7 in stacks but is operationally managed with applications.

- Layer 7 — Application
  - Responsibility: application-specific semantics and protocols.
  - Examples: DNS, HTTP/1.1, HTTP/2, HTTP/3, SMTP, IMAP, SSH, NTP, DHCP, API protocols, service discovery interfaces.
  - Notes: failures here can be independent of lower layers (e.g., 403/404/5xx despite working TCP/TLS).

## Encapsulation example

An application message is progressively encapsulated as it moves down the stack; each layer adds its own header (and sometimes trailer):

```
HTTP request (L7)
 └─ inside TLS records (often placed between L4 and L7 in practice)
    └─ inside TCP segments (L4)
       └─ inside IP packets (L3)
          └─ inside Ethernet or Wi‑Fi frames (L2)
             └─ over electrical/optical/radio signaling (L1)
```

At each router hop, L2 framing changes; L3/L4 headers typically remain intact end-to-end (except where NAT or middleboxes modify them).

## Addressing and identity by layer

- L2: MAC addresses (48-bit traditional; randomization common on Wi‑Fi). Scope: local broadcast domain only; changed per-hop by routers.
- L3: IP addresses (IPv4 32-bit, IPv6 128-bit). Scope: routed across networks; assigned to interfaces; subnetting defines on-link reachability.
- L4: Ports (TCP/UDP). Scope: process/service demultiplexing; well-known vs ephemeral; stateful firewalls track connection/flow state.
- L7: Names and protocol identifiers (DNS hostnames, URLs, service names, API paths). Scope: application semantics, virtual hosting, policy.

## Devices and functions through the OSI lens

- L1: hubs/repeaters (historical), PHYs, cables, optics, antennas.
- L2: switches/bridges, APs, VLANs, STP, link aggregation.
- L3: routers, default gateways, ICMP, route tables.
- L3/L4: NAT/PAT devices, stateful firewalls (track TCP/UDP state), CGNAT.
- L4/L7: load balancers (TCP/UDP L4; HTTP-aware L7), reverse proxies, API gateways, WAFs.
- Cross-layer: DPI firewalls (L3/4/7), service meshes (L7-sidecars operating over L4), CDNs (L7 with distributed L3 reachability).

## Operational use: troubleshooting by layer

Work bottom-up or by isolating the failing layer:

- L1/L2: link up? Wi‑Fi associated? VLAN correct? MTU consistent? ARP/ND resolving?
- L3: valid IP, correct subnet/gateway, route present, can reach gateway and external IP?
- L4: can connect to required port? “Refused” vs “timed out”? Firewall/NAT state?
- “Between” L4–L7: TLS handshake succeeds? Certificate validity/hostname/SNI? Client clock?
- L7: DNS resolves? Expected records (A/AAAA/CNAME/MX/TXT)? HTTP status codes (2xx/3xx/4xx/5xx)? Proxy/load balancer health and routing?

Common diagnostic interpretations:
- “Layer 2 issue” → switching, VLANs, Wi‑Fi association, MAC learning/flooding.
- “Layer 3 issue” → IP addressing, subnet mask, default route, routing asymmetry.
- “Layer 4 issue” → TCP/UDP ports, handshake states, stateful filtering, NAT traversal.

## Limits and cross-layer realities

The OSI model is not a strict map of modern Internet behavior:

- TLS placement: often described as L5/L6, but operationally sits between application and transport in TCP/IP stacks; interacts with SNI/ALPN at “L7.”
- QUIC over UDP: implements transport-like reliability, congestion control, and integrated TLS above UDP, blurring classical TCP-vs-UDP roles.
- MPLS “Layer 2.5”: label switching doesn’t fit cleanly into L2/L3.
- DNS is L7 but foundational to almost all applications; DNS failures can block L3/L4 tests that rely on names.
- Firewalls/load balancers/proxies: inspect and act at L3, L4, and L7 simultaneously; some decisions depend on combined context (IP, port, SNI, HTTP headers).
- Over-simplifications to avoid:
  - “L3 means only IP” (ignores ICMP essentials, IPv6 ND dependence on ICMPv6).
  - “L4 means ports” (also includes TCP state, retransmissions, congestion/flow control).
  - “L7 means everything else” (interacts tightly with TLS, DNS, proxies, identity, CDNs).

## OSI vs TCP/IP model

- TCP/IP (4–5 layers) more closely reflects the Internet protocol suite:
  - Link (L1+L2), Internet (IP/ICMP), Transport (TCP/UDP/QUIC), Application (DNS/HTTP/SMTP/etc.). Some treatments split Physical and Data Link.
- Practical guidance:
  - Use OSI to structure thought and vocabulary.
  - Use TCP/IP when mapping real deployments, implementations, and tooling.

## Failure patterns mapped to layers (brief)

- L1/L2: no link, bad cable/RF, wrong VLAN/SSID, ARP/ND failures, MTU mismatch.
- L3: wrong IP/subnet/gateway, missing route, asymmetric routing, blocked ICMPv6 (breaks IPv6).
- L4: port blocked, stateful firewall timeout, NAT mapping absent, “refused” vs “timed out.”
- L5–L6 (conceptual): TLS negotiation/cert errors, SNI mismatch, cipher/protocol version mismatch.
- L7: DNS NXDOMAIN/SERVFAIL/split-horizon issues, HTTP 403/404/5xx, proxy/WAF policy, backend health.

## Example: layered path for opening an HTTPS site

- L7: Browser composes HTTPS request (method/path/headers), may use caches/policies.
- L7: DNS resolution for host to A/AAAA (recursive resolver, CNAME following, TTL/cache).
- L3: Routing decision; default gateway chosen for remote networks.
- L2: ARP (IPv4) or Neighbor Discovery (IPv6) to resolve next-hop MAC; frame sent.
- L3: Routers forward IP packets hop-by-hop; NAT may translate addresses/ports (IPv4).
- L4: TCP three-way handshake to port 443 (or QUIC over UDP 443 for HTTP/3).
- L5/L6: TLS handshake with SNI/ALPN; certificate validation (trust, dates, name).
- L7: HTTP exchange; reverse proxy/load balancer/CDN may route to backends; response returned.

## Common misconceptions (clarified)

- “The Internet is built on the OSI stack.” Reality: the Internet follows TCP/IP; OSI is a teaching model.
- “L7 success implies lower layers are fine end-to-end.” Often true, but middleboxes can alter content; DNS and TLS issues can cause application-visible errors even if TCP connects.
- “NAT is a firewall.” NAT translates addresses; stateful filtering/policy decides allow/deny. Many devices combine both, causing confusion.

## Practical vocabulary cheatsheet

- PDUs by layer (informal): bits (L1), frames (L2), packets (L3), segments/datagrams (L4), data/messages (L5–L7).
- Addressing scopes: MAC (L2 local), IP (L3 routed), ports (L4 process), names/URLs (L7 app).
- Typical devices: hubs/PHYs (L1), switches/APs (L2), routers (L3), NAT/stateful firewalls (L3/4), load balancers/proxies/WAFs (L4/7).

## Key Points

- OSI is a seven-layer conceptual model useful for vocabulary and troubleshooting; the Internet implements TCP/IP, not literal OSI.
- Each layer encapsulates data from the layer above and provides specific services: L1 bits, L2 frames/MAC, L3 IP/routing, L4 ports/reliability, L5–L6 session/presentation (conceptual), L7 application semantics.
- Real-world protocols often blur OSI boundaries (TLS placement, QUIC over UDP, MPLS “2.5”); treat OSI as taxonomy, not strict implementation.
- Troubleshoot methodically by layer: verify link, addressing/routes, ports/state, TLS, then application (DNS/HTTP/proxy/backend).
- Addressing scopes differ by layer: MAC local-only (L2), IP routed (L3), ports per-host (L4), names and protocol semantics (L7).