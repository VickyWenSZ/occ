---
title: IP Addressing and Subnetting (IPv4 & IPv6)
slug: ip-addressing-and-subnetting
source: computer-networking-basics
confidence: high
tags: [networking, ipv4, ipv6, subnetting, addressing]
---

# IP Addressing and Subnetting (IPv4 & IPv6)

## Purpose and scope

IP addressing identifies interfaces at Layer 3; subnetting partitions address space into routing domains (subnets) that define local vs remote delivery. Correct addressing/subnetting underpins reachability, routing, NAT behavior, DHCP/SLAAC, security policy, and diagnostics. This page covers IPv4 and IPv6 address structure, special-use ranges, assignment methods, neighbor resolution, subnet math, design patterns, and common failure modes, with dual-stack considerations.

## Addressing fundamentals

- An IP address is bound to an interface; a host can have many addresses (multiple NICs, VLANs, VPNs, VMs/containers).
- Local vs remote determination is prefix-based:
  - If destination matches a local on-link prefix, deliver via L2 (IPv4: ARP; IPv6: Neighbor Discovery).
  - Otherwise, forward to a router (default gateway or more specific route).
- Longest prefix match (LPM) selects routes; more specific prefixes win over less specific; default route (0.0.0.0/0 or ::/0) is last resort.
- Subnet boundaries change forwarding behavior. Wrong masks or overlapping subnets cause “looks local but isn’t” or routing blackholes.

## IPv4 addressing

### Structure and notation

- 32-bit address; dotted decimal, e.g., 192.0.2.10.
- CIDR notation: address/prefix-length (e.g., 192.168.1.0/24). Classful terms (A/B/C) are historical; modern routing is classless (CIDR).

### Special-use and reserved ranges

- Private-use (RFC 1918; not globally routed):
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 192.168.0.0/16
- Carrier-grade NAT (CGNAT; RFC 6598): 100.64.0.0/10 (used by providers; not for LANs).
- Loopback: 127.0.0.0/8 (commonly 127.0.0.1).
- Link-local autoconfig (APIPA): 169.254.0.0/16 (fallback when DHCP fails).
- Documentation (examples): 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24.
- Multicast: 224.0.0.0/4; limited-scope control 224.0.0.0/24 on local link.
- Broadcast: 255.255.255.255 (limited broadcast) and per-subnet directed broadcast (all-ones host part; typically filtered).

### Local delivery and resolution

- ARP maps IPv4 to MAC on-link; stale/poisoned ARP breaks local connectivity. IPv6 does not use ARP.
- A host ARPs for the destination if on-link; otherwise ARPs for the default gateway’s MAC.

### NAT interactions (IPv4)

- Source NAT/PAT enables many private hosts to share one public address; state tracks 5-tuples or mappings.
- NAT is distinct from firewalling; common home routers combine both (stateful filtering + NAT), blocking unsolicited inbound by lack of mapping.
- Double NAT and CGNAT complicate inbound reachability (port forwarding), peer-to-peer, SIP/VoIP, and some VPNs.

## IPv6 addressing

### Structure and notation

- 128-bit address; hexadecimal with colons, e.g., 2001:db8::1.
- Notation rules:
  - Suppress leading zeros in each hextet.
  - Use one “::” to compress the longest run of consecutive zero hextets.
- No broadcast; uses multicast and anycast.

### Address types and scopes

- Loopback: ::1/128.
- Link-local: fe80::/10 (required on every IPv6 interface; valid only on a link; often requires zone index when used manually, e.g., fe80::1%eth0).
- Global unicast (GUA): 2000::/3 (publicly routable).
- Unique local (ULA): fc00::/7 (commonly fd00::/8); internal-only semantics (not intended for global routing).
- Multicast: ff00::/8 (scoped group addresses).
- Documentation: 2001:db8::/32.

### Assignment and neighbor behavior

- SLAAC: host forms addresses from Router Advertisements (RAs), typically /64 LANs; may use:
  - Modified EUI-64 (MAC-derived interface ID; toggles U/L bit; privacy concerns).
  - Privacy extensions (RFC 4941): temporary randomized IIDs for outbound use; change over time.
  - Stable opaque IIDs (RFC 7217): per-prefix stable, non-MAC-derived IIDs.
- DHCPv6: can provide addresses (stateful) and/or other config (stateless), often alongside SLAAC.
- Neighbor Discovery (ICMPv6): router discovery (default gateways), on-link prefix discovery, address resolution, duplicate address detection (DAD), neighbor unreachability detection (NUD). Blocking ICMPv6 breaks IPv6.
- Common LAN prefix size is /64. P2P may use /127; loopbacks /128.

### NAT in IPv6

- Native IPv6 favors end-to-end global addressing with firewall policy; NAT66 is generally discouraged.
- NPTv6 (prefix translation) can be used for limited renumbering scenarios.
- NAT64/DNS64 bridge IPv6-only clients to IPv4 servers via a NAT64 prefix (e.g., 64:ff9b::/96) with DNS synthesis; application/protocol constraints apply.

### Dual-stack and address selection

- Dual-stack runs IPv4 and IPv6 concurrently; clients may try IPv6 first with quick fallback (Happy Eyeballs).
- Asymmetric failures are common: AAAA present but IPv6 routing/firewall wrong; monitoring covers IPv4 only; ICMPv6 blocked; server not bound to IPv6.

## Subnetting concepts

### What a subnet is

- A subnet is an IP prefix defining which addresses are directly reachable at L2; different subnets communicate via routing.
- Subnetting and summarization (supernetting) shape routing tables and fault domains.

### Gateway requirements

- Default gateway must be reachable on-link; i.e., the gateway IP must be inside the host’s local subnet (normal LAN design). Misplaced gateways cause off-link ARP attempts and failures.

### Overlapping subnets

- Overlap creates routing ambiguity (e.g., home 192.168.1.0/24 vs corporate VPN 192.168.1.0/24). Local connected route usually wins; corporate hosts become unreachable. Mitigate by renumbering, using uncommon ranges, or NAT inside VPN designs.

## IPv4 subnetting math

### Prefix length, masks, capacity

- Host capacity (common case): 2^(32 − prefix) − 2 (network + broadcast excluded).
- Teaching exceptions:
  - /31 on point-to-point links uses both addresses (no broadcast); capacity 2.
  - /32 is a host route (one address).
- Common masks:
  - /24 = 255.255.255.0 (256 total; 254 usable hosts)
  - /25 = 255.255.255.128 (128 total; 126 usable)
  - /26 = 255.255.255.192 (64 total; 62 usable)
  - /27 = 255.255.255.224 (32 total; 30 usable)
  - /28 = 255.255.255.240 (16 total; 14 usable)
  - /30 = 255.255.255.252 (4 total; 2 usable; classic P2P)
  - /31 = 255.255.255.254 (2 total; 2 usable; P2P)

### Find network and broadcast

Algorithm:
1. Convert address and mask to binary (or use bitwise arithmetic).
2. Network = address AND mask.
3. Broadcast = network OR (NOT mask).
4. Usable range = (network + 1) .. (broadcast − 1) for typical LANs.

Example:
- 192.168.10.130/25
  - Mask 255.255.255.128 → block size 128 → networks at .0 and .128
  - Network = 192.168.10.128
  - Broadcast = 192.168.10.255
  - Usable = .129–.254

### Splitting a /24

- Two /25:
  - 192.168.10.0/25 (hosts .1–.126), 192.168.10.128/25 (hosts .129–.254)
- Four /26:
  - 192.168.10.0/26, .64/26, .128/26, .192/26 (each 62 usable hosts)
- Eight /27:
  - Increments of 32: .0, .32, .64, .96, .128, .160, .192, .224

### Worked allocation example

Goal: 6 subnets, ≥30 hosts each from 192.168.50.0/24.
- Need ≥30 usable → /27 (30 usable) fits.
- Allocate eight /27s; use first six:
  - 192.168.50.0/27, .32/27, .64/27, .96/27, .128/27, .160/27.

## IPv6 subnetting practice

- Ordinary LANs use /64. Mechanisms (SLAAC, ND) assume /64 for interface identifiers.
- Site planning uses large aggregates for hierarchy and summarization:
  - Typical delegations: /48 (enterprise site), /56 (home/small site), /60 (smaller home).
  - From a /56, 256 distinct /64 LANs are available.
- P2P links: /127 recommended to avoid ping-pong ND issues; loopbacks /128.

Example: ISP delegates 2001:db8:1234:5600::/56
- LAN prefixes (examples):
  - 2001:db8:1234:5601::/64 (users)
  - 2001:db8:1234:5602::/64 (servers)
  - 2001:db8:1234:5603::/64 (guest)
  - … up to 2001:db8:1234:56ff::/64.

## Address assignment methods

### IPv4

- Static: manual address/mask/gateway/DNS (error-prone at scale).
- DHCPv4: leases address, mask, gateway, DNS, and options (PXE, NTP, etc.).
  - Reservations give stable mapping by MAC or client ID.
  - Leases should align with operational churn; short leases increase control-plane load.

### IPv6

- SLAAC: RAs advertise prefix and default gateway; hosts self-assign IIDs.
- DHCPv6: provides addresses/config (stateful) or only other config (stateless).
- Prefix delegation (PD): downstream router receives a prefix (e.g., /56) and sub-assigns /64s on LANs.
- Privacy: use RFC 4941 temporary or RFC 7217 stable opaque IIDs to avoid MAC-derived identifiers.

## Default gateway, ARP/ND, and local delivery

- Default gateway choice is per-subnet. Hosts must be able to resolve the gateway’s L2 address:
  - IPv4: ARP “Who has X?”
  - IPv6: ND Neighbor Solicitation to the gateway’s address; routers discovered via RAs.
- Wrong mask/gateway leads to:
  - ARP/ND for remote addresses (because host thinks remote is local) → no reply → timeout.
  - Or sending to an unreachable off-link gateway → blackhole.

## Private vs public addressing and reachability

- Private IPv4 (RFC 1918) requires NAT for Internet egress; inbound needs port forwarding or overlay (VPN/reverse proxy).
- Public addresses are “globally routable” but may still be unreachable due to routing policy, firewalls, or provider constraints (e.g., outbound TCP/25 blocks).
- Home/CGNAT: carrier-grade NAT prevents simple inbound port-forwarding; alternatives include VPN, reverse tunnels, or provider-assigned public IP.
- IPv6 GUA restores end-to-end addressability; inbound access still governed by firewall default-deny.

## Multicast, anycast, loopback

- IPv4 multicast: 224.0.0.0/4; scoped control messages (224.0.0.0/24) stay on-link.
- IPv6 multicast: ff00::/8; ND and RA use multicast; do not block required groups.
- Anycast (v4/v6): same address advertised from multiple locations; LPM/routing picks nearest (e.g., DNS resolvers).
- Loopback: 127.0.0.0/8 (v4), ::1 (v6). Services bound only to loopback are host-local.

## Design patterns and planning

- Enterprise:
  - Hierarchical IPv4 CIDR and IPv6 aggregates for summarization.
  - Subnet per VLAN/security zone (users, servers, DMZ, management, voice, guest).
  - Avoid overlap across sites and VPN domains.
  - Reserve address blocks for infrastructure; document gateway/DHCP/DNS conventions.
- Home:
  - Use uncommon RFC1918 ranges to reduce VPN overlap (e.g., 10.64.0.0/24 rather than 192.168.1.0/24).
  - Prefer DHCP reservations for devices needing port-forwarding stability.
  - If IPv6 PD available, segment LANs with /64s; keep firewall default-deny inbound.
- Cloud:
  - Plan VPC/VNet CIDRs for growth and peering; avoid overlap with on-prem and partner spaces.
  - Public subnets route to Internet gateway; private subnets egress via NAT gateway.
  - Security groups enforce L3/L4 stateful policy; route tables steer between IGW, NAT, VPN, TGW.
- Kubernetes/containers:
  - Pod IPs are routable within cluster; Services provide stable virtual IPs; Ingress exposes HTTP/S.
  - Binding to 127.0.0.1 inside a container isolates the service; bind to 0.0.0.0/:: for external reachability; publish ports or use Services/Ingress.

## Common failure modes

- Wrong subnet mask: host treats remote as local (or vice versa) → ARP/ND fails; fix mask.
- Wrong default gateway: local comms fine; off-subnet fails; fix DHCP option or static config.
- Gateway off-subnet: host cannot ARP/ND for gateway; invalid ordinary LAN design.
- Overlapping subnets (especially VPN): local route wins; renumber or NAT in VPN design.
- ARP/ND issues: stale entries, spoofing, or blocked ICMPv6 → local delivery fails; clear cache, enable DAI/RA Guard, allow ICMPv6.
- IPv6 AAAA published but IPv6 path blocked: users hit IPv6 first and stall; remove AAAA until ready or fix IPv6 routing/firewall.
- ICMPv6 blocked: ND, PMTU discovery break; allow essential ICMPv6.
- NAT state/translation errors (IPv4): timeouts, asymmetric routing, double NAT; fix NAT rules, ensure symmetric paths, avoid unnecessary NAT layers.

## Diagnostics and calculations

- Show IPs and masks/prefixes:
  - Windows: ipconfig /all
  - Linux: ip addr, ip -6 addr
  - macOS/BSD: ifconfig
- Show routes:
  - Windows: route print; PowerShell Get-NetRoute
  - Linux: ip route, ip -6 route
- Neighbor caches:
  - IPv4: arp -a, ip neigh
  - IPv6: ip -6 neigh
- Reachability:
  - ping 192.0.2.1; ping6/ping -6 2001:db8::1
  - For link-local: ping -6 fe80::1%eth0 (zone index required)
- Subnet sanity checks:
  - Verify gateway is inside on-link prefix and responds to ARP/ND.
  - Verify mask/prefix matches network plan.
- Dual-stack tests:
  - dig A and AAAA; curl -4/-6 to force family; ensure service binds on both.
- NAT/port-forwarding:
  - Confirm internal service listens on correct address/port and host firewall allows it.
  - Verify public IP truly assigned (not behind CGNAT); confirm rule matches protocol/port and return route.

## Security considerations

- NAT is not security; stateful firewalls and explicit policy enforce access. Least-privilege network access is preferred.
- Local L2 threats: ARP spoofing, rogue DHCP, rogue RAs. Mitigate with segmentation, switch security features (DAI, RA Guard), 802.1X, and encrypted apps.
- IPv6 global addresses require the same (or stricter) inbound policy as IPv4; default deny unsolicited inbound.
- DNS and TLS protect higher-layer identity and confidentiality; address correctness alone does not guarantee safe communications.

## Worked examples

### IPv4: find network and broadcast

```
IP:     10.23.45.67
Mask:   255.255.255.192 (/26)

Block size: 64 in last octet → subnets at .0, .64, .128, .192
Network:    10.23.45.64
Broadcast:  10.23.45.127
Usable:     10.23.45.65 – 10.23.45.126
```

### IPv4: choose smallest subnet for a requirement

Requirement: 20 hosts on one segment.
- Need ≥20 usable → /27 (30 usable) is minimal typical LAN prefix.

### IPv6: use link-local with zone index

```
# Linux/macOS example
ping -6 fe80::a00:27ff:fe12:3456%eth0
ssh -6 user@fe80::a00:27ff:fe12:3456%eth0
```

### IPv6: home PD layout from /56

```
Delegated: 2001:db8:abcd:1200::/56

LAN1 users: 2001:db8:abcd:1201::/64
LAN2 IoT:   2001:db8:abcd:1202::/64
Guest:      2001:db8:abcd:1203::/64
Mgmt:       2001:db8:abcd:1204::/64
```

## Operational tips

- Adopt consistent gateway conventions (e.g., .1 in IPv4 subnets; ::1 or ::1:1 style in IPv6) and document them.
- In dual-stack, deploy and monitor IPv6 and IPv4 equivalently (health checks, firewalls, logs, metrics).
- Allow essential ICMP/ICMPv6 for ND and PMTU; blackholing “Packet Too Big” causes PMTU stalls (small pings work; HTTPS/TLS stalls).
- For VPNs, design non-overlapping address pools; when unavoidable, implement NAT within the VPN or use identity-aware application gateways instead of raw L3 access.
- Use DHCP reservations (IPv4) or stable DHCPv6/DUID-based assignments for services needing predictable addresses; avoid static misalignment with DHCP scopes.

## Key Points

- Subnetting defines local vs remote delivery; wrong masks or off-subnet gateways break reachability even when IPs “look correct.”
- IPv4 local delivery uses ARP and typically relies on NAT for Internet egress; IPv6 uses Neighbor Discovery, SLAAC/DHCPv6, and should not broadly block ICMPv6.
- Ordinary IPv6 LANs are /64; plan sites with /48–/56 aggregates and avoid NAT66; enforce inbound policy with firewalls instead.
- Overlapping subnets (especially with VPNs) cause ambiguous routing; prevent by careful planning and uncommon private ranges.
- Dual-stack deployments must validate both families: publish AAAA only when IPv6 routing, firewall, and bindings are correct; test with -4/-6 tooling.