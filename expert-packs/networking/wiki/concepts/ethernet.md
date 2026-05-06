---
title: Ethernet (Wired LAN)
slug: ethernet
source: computer-networking-basics
confidence: high
tags: [ethernet, lan, layer2, mac, switching]
---

# Ethernet (Wired LAN)

Ethernet is the dominant wired LAN technology at OSI Layer 2 (Data Link) with associated Layer 1 (Physical) media. It defines framing, MAC addressing, media access behavior, and multiple physical variants (copper and fiber) supporting a range of speeds and distances. In modern deployments, switched full‑duplex Ethernet provides stable, low‑latency local communication and forms the substrate for IP networks, VLAN segmentation, and data center fabrics.

## Scope and role in layering

- Layering:
  - L1: signaling over copper twisted pair or fiber optics at various rates and encoding schemes (details abstracted here).
  - L2: Ethernet framing, MAC addressing, switching behavior, VLAN tagging, FCS error detection.
- Relationship to IP:
  - IP packets are encapsulated in Ethernet frames on local segments.
  - Routers decapsulate/recapsulate at each hop; IP src/dst persist, link‑layer src/dst (MACs) change per hop.
- Contrast to Wi‑Fi:
  - Ethernet (switched) is typically full‑duplex and non‑contentious per link.
  - Wi‑Fi is shared, half‑duplex radio with contention and variable rates.

## Physical media and link properties

- Media types:
  - Copper (twisted pair): common for access links; achievable speeds depend on NICs, switch ports, cable category, and distance.
  - Fiber: used for higher speeds and/or longer distances; optics and fiber type determine reach/rate.
- Common copper link rates: 100 Mb/s, 1 Gb/s, 2.5 Gb/s, 5 Gb/s, 10 Gb/s (device, cabling, and distance dependent).
- Duplex:
  - Modern switched Ethernet is full‑duplex (simultaneous send/receive).
  - Legacy hubs were shared half‑duplex and are largely obsolete.
- Link characteristics: bandwidth, latency, error rate, duplex mode, MTU, and deterministic media access (no radio contention).

## Ethernet frame, MTU, and FCS

- Simplified frame fields:
  ```
  [Destination MAC][Source MAC][802.1Q VLAN tag (optional)][EtherType/Length][Payload][Frame Check Sequence]
  ```
- EtherType identifies payload (e.g., IPv4, IPv6, ARP).
- FCS (frame check sequence) provides link‑level corruption detection; damaged frames are typically discarded (no link‑layer retransmission).
- MTU:
  - Standard Ethernet commonly yields 1500‑byte IP payload MTU.
  - Jumbo frames permit larger MTUs in controlled environments (e.g., data centers, storage), but all devices along the path must be configured consistently or fragmentation/blackholing occurs.

## MAC addressing

- Format: 48‑bit addresses, six hexadecimal octets (e.g., `00:1A:2B:3C:4D:5E`).
- Scope and lifecycle:
  - Used for local delivery within a Layer‑2 broadcast domain; not routed end‑to‑end across the Internet.
  - Routers rewrite link‑layer addresses at each hop.
- Types:
  - Unicast (individual), multicast (group), and broadcast.
  - Broadcast MAC `ff:ff:ff:ff:ff:ff` targets all stations in a broadcast domain.
- Allocation and identity caveats:
  - Often globally unique when burned into NICs; however, VMs/containers frequently use locally administered MACs.
  - Modern OSs commonly randomize MACs for privacy on Wi‑Fi; do not treat MACs as permanent user identity without context.

## Switching behavior (bridging)

- Learning and forwarding:
  - Switches learn source MAC → ingress port mappings and forward frames to the port associated with the destination MAC.
  - Unknown‑unicast, broadcast, and some multicast frames are flooded within the VLAN until learned or constrained.
- Broadcast domains and control:
  - VLANs (802.1Q) partition broadcast domains on shared switching infrastructure.
  - IGMP snooping and storm control reduce unnecessary multicast/broadcast flooding.
- Advanced features:
  - VLANs, link aggregation, spanning tree, port security, QoS, and manageability.
- Limitations:
  - Pure Layer‑2 switches do not route between IP subnets; inter‑VLAN routing requires a router or multilayer switch.

## VLANs (802.1Q) and segmentation

- Purpose: logical Layer‑2 segmentation over shared physical switches; commonly mapped one‑to‑one with IP subnets in enterprise designs.
- Port modes:
  - Access ports carry a single VLAN to endpoints.
  - Trunk ports carry multiple VLANs with 802.1Q tags between switches, routers, hypervisors, or AP uplinks.
- Inter‑VLAN communication:
  - Requires Layer‑3 routing (router or L3 switch/firewall) and corresponding policy controls.
- Common misconfigurations:
  - Wrong access VLAN, missing/blocked VLAN on trunks, native VLAN mismatch, missing DHCP relay for a VLAN, incorrect firewall policy between VLANs.

## Address Resolution Protocol (IPv4 on Ethernet)

- Function: maps IPv4 addresses to MACs on a local subnet.
  - Host ARPs for target’s MAC if destination is on‑link.
  - For off‑subnet destinations, host ARPs for the default gateway’s MAC and frames to that gateway (IP dst remains the remote host).
- Caching and correctness:
  - ARP caches accelerate local delivery; stale/incorrect entries can impair reachability (usually auto‑refreshed).
- Security:
  - ARP spoofing/poisoning can redirect local traffic.
  - Mitigations: segmentation, switch security, Dynamic ARP Inspection (managed environments), and using encrypted higher‑layer protocols.
- IPv6 note: Ethernet does not use ARP for IPv6; Neighbor Discovery (ICMPv6) provides analogous functions.

## Operational characteristics and performance

- Reliability model:
  - Ethernet detects but does not repair link‑level corruption; higher layers (e.g., TCP) provide end‑to‑end reliability and ordering.
- Latency and throughput:
  - Switched full‑duplex Ethernet offers stable low‑latency paths relative to shared media; throughput depends on link rate and device capacity.
- MTU operations:
  - Mismatched MTU or partial jumbo support can cause PMTUD issues at higher layers (stalls/hangs for large transfers while small packets succeed).

## Interactions with IP routing and NAT

- Routing boundary:
  - Hosts in the same IP subnet communicate directly at L2 after ARP/ND resolution.
  - Hosts in different subnets require a router; routers rewrite L2 headers per next hop.
- Default gateway:
  - Must be reachable on‑link (inside the host’s subnet) in ordinary LAN designs; wrong gateway breaks off‑subnet reachability.
- NAT:
  - Common at network edges (IPv4) but not an intrinsic Ethernet function; affects reachability and troubleshooting beyond the L2 domain.

## Troubleshooting patterns (Ethernet focus)

- Fast checks:
  - Physical/link: link light, interface up, correct switch port and cable.
  - L2 adjacency: verify ARP/neighbor table entries for local peers and default gateway.
  - VLAN: confirm access/trunk configuration, allowed VLANs, native VLAN consistency.
  - MTU: test for large‑packet failures in tunneled/overlay contexts.
- Useful tools and signals:
  - ip/ifconfig/ipconfig to verify address/subnet/gateway/DNS.
  - ip neigh/arp to inspect L2 resolution.
  - ping default gateway to isolate local vs upstream faults.
  - tcpdump/Wireshark to see ARP, broadcasts, unicast forwarding, and TCP handshakes.
- Typical L2/L3 symptom mapping:
  - Can reach local hosts but not gateway: switch/VLAN/ARP issues.
  - Can reach gateway but not Internet: routing/NAT/upstream firewall.
  - Intermittent local access with duplicate ARP entries: potential IP conflict.
  - Works on one VLAN but not another: trunk allow‑list or inter‑VLAN policy.

## Security and segmentation

- Ethernet itself provides no confidentiality/integrity beyond FCS corruption detection; use TLS, SSH, or VPNs for encryption in transit.
- Limit L2 blast radius with VLANs and controlled inter‑VLAN routing/firewalling.
- Harden access ports and L2 control plane:
  - Port security, storm control, IGMP snooping, and ARP inspection (where appropriate).
- Do not conflate L2 segmentation with full security; enforce least‑privilege at L3/L7 as well.

## Reference behaviors (from the broader stack)

- Broadcast and flooding scope is limited to a VLAN/broadcast domain; routers do not forward Ethernet broadcasts.
- IPv6 operation on Ethernet relies on ICMPv6 (Neighbor Discovery, RAs); blocking ICMPv6 breaks core IPv6 behavior even if L2 is sound.
- Jumbo frames are environment‑specific optimizations; enable only with end‑to‑end validation.

## Key Points

- Ethernet provides Layer‑2 framing, MAC addressing, and switched full‑duplex links; routers change L2 headers at each hop while IP src/dst persist.
- Standard MTU is typically 1500 bytes; jumbo frames require consistent end‑to‑end configuration or higher‑layer failures can occur.
- Switches learn and forward by MAC, flood unknown/broadcast within VLANs, and commonly support VLANs, LAG, STP, QoS, and security features.
- IPv4 uses ARP for local delivery; IPv6 uses Neighbor Discovery. ARP spoofing is a local‑network risk mitigated by segmentation and switch safeguards.
- VLANs segment broadcast domains and often align with IP subnets; inter‑VLAN traffic requires routing and explicit policy. Misconfigured VLANs are frequent root causes of LAN issues.