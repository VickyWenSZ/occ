---
title: Wi‑Fi (IEEE 802.11)
slug: wi-fi
source: computer-networking-basics
confidence: high
tags: [wireless, ieee-802.11, wlan, security, troubleshooting]
---

# Wi‑Fi (IEEE 802.11)

## Definition and model placement
- Wi‑Fi is a family of wireless LAN technologies defined by IEEE 802.11. It operates at the data link layer (OSI Layer 2) and the TCP/IP link layer, providing local wireless connectivity over radio instead of cables.
- Typical frequency bands: 2.4 GHz, 5 GHz, and 6 GHz (availability depends on device support and regulatory domain).
- Architectural role: provides local delivery of frames on a shared radio medium; upper layers (IP, TCP/UDP, applications) are independent of whether the link is Wi‑Fi or Ethernet.

## Medium characteristics and performance
- Shared, half‑duplex medium: only one transmitter effectively uses a channel at a time within a contention domain.
- Real throughput is usually much lower than advertised PHY/link rates due to contention, retransmissions, protocol overhead, and environmental factors.
- Performance determinants:
  - Signal strength (RSSI) and signal‑to‑noise ratio (SNR); e.g., −50 dBm is stronger than −75 dBm.
  - Interference and noise (neighboring Wi‑Fi, Bluetooth, microwave ovens, cordless phones, wireless cameras, DFS radar events, unintentional emitters).
  - Channel width and channel selection.
  - Distance, walls/materials, client/AP capabilities, number of clients, neighboring networks.
  - Client transmit power asymmetry (AP may be heard by client but client may not reliably reach AP).
- Compared with Ethernet:
  - Wi‑Fi is shared and half‑duplex; switched Ethernet is typically full‑duplex with stable low latency.
  - Wi‑Fi links are more sensitive to environmental conditions; Ethernet links have predictable MTU/duplex once negotiated.

## Bands, channels, and channel planning
- 2.4 GHz:
  - Limited non‑overlapping channels; in many regions, plan with channels 1/6/11 to reduce overlap.
  - Crowded band; higher interference likelihood.
- 5 GHz and 6 GHz:
  - More channels; better aggregate performance potential.
  - DFS channels (5 GHz) may require radar detection and channel vacate events; availability varies by region/AP/client.
- Channel width trade‑off:
  - Wider channels increase peak throughput but reduce the number of non-overlapping channels and increase susceptibility to interference.
  - In dense environments, narrower channels can improve aggregate performance.

## Association, authentication, and encryption
- Association uses SSID (network name), with selected authentication/encryption:
  - WPA2 or WPA3 are recommended.
  - WPA‑Personal (PSK): shared passphrase.
  - WPA‑Enterprise: per‑user/device authentication using 802.1X with a RADIUS backend.
  - Legacy WEP and WPA/TKIP are insecure/obsolete and should not be used; mixed modes can weaken security and cause compatibility issues.
- Security scope:
  - Wi‑Fi encryption protects the wireless link only; it does not replace HTTPS/TLS, VPNs, application auth, or network segmentation.

## SSIDs and network identity
- Multiple APs may present the same SSID to extend coverage; an SSID can be broadcast on multiple bands and even map to different VLANs/policies.
- Hidden SSIDs are not a strong security control; clients can reveal/probe for them and attackers can often discover them.
- Enterprise SSIDs can dynamically assign users/devices to different VLANs based on policy.

## Roaming behavior
- Roaming decisions are typically client‑driven; enterprise systems can assist with standards/controller features, but behavior varies by device.
- Sticky clients may cling to weak APs despite better alternatives, degrading performance.
- Fast roaming features can reduce handoff disruption for voice/video but must be supported and correctly configured on both client and infrastructure.

## MAC addressing and privacy
- Wi‑Fi uses 48‑bit MAC addresses for link‑local delivery; addresses are not routed across IP hops.
- Modern OSs frequently use MAC address randomization on Wi‑Fi for privacy; do not assume MAC is a persistent identity without context.

## Frames and local delivery
- Wi‑Fi frames encapsulate higher‑layer payloads (e.g., IP packets) for local delivery across the wireless link.
- Routers decapsulate incoming link‑layer frames (Ethernet/Wi‑Fi) and re‑encapsulate for the next hop; IP addresses remain end‑to‑end while link‑layer addresses change per hop.

## Interaction with IP, DHCP, and IPv6
- IP assignment over Wi‑Fi is the same as wired:
  - IPv4: typically via DHCP; failures yield symptoms like 169.254.0.0/16 link‑local fallback.
  - IPv6: SLAAC (RA‑based), DHCPv6, or both; ICMPv6 must not be broadly blocked.
- Subnet and default gateway correctness remain essential; wrong gateway/mask causes remote reachability failures.

## Interference and environmental considerations
- Common interference sources: neighboring APs, Bluetooth, microwaves, cordless phones, wireless cameras; DFS radar (5 GHz) can force channel changes; poorly shielded devices can emit noise.
- Effects: retransmissions, down‑shifted modulation rates, higher latency/jitter, “slow Internet” despite healthy WAN.

## Mesh Wi‑Fi and backhaul
- Mesh systems extend coverage via multiple nodes:
  - Wired backhaul preferred for capacity/stability.
  - Wireless backhaul consumes airtime; poor node placement yields strong‑looking but slow links.
  - Place nodes where they still have good connectivity to main node/backhaul.

## Troubleshooting patterns and diagnostics
- Distinguish “Wi‑Fi” vs “Internet”: associated Wi‑Fi doesn’t guarantee upstream Internet reachability.
- Rapid triage:
  - Interface/association OK? Correct SSID/security?
  - Got IP? If not, check DHCP scope/VLAN/rogue DHCP/relay.
  - Ping default gateway to isolate local link vs upstream issue.
  - Test external IP reachability (routing/NAT) vs DNS name resolution (DNS).
  - Compare performance wired vs Wi‑Fi to isolate RF issues.
  - Compare 2.4 GHz vs 5/6 GHz; check channel utilization/interference.
  - Observe roaming/sticky-client behavior; test near AP.
- Symptom→layer hints:
  - Strong RSSI but poor throughput: interference/contention, AP overload, bad backhaul, sticky roam.
  - Has Wi‑Fi but no IP: DHCP/VLAN/relay/scope exhaustion.
  - Can ping gateway but not Internet IP: routing/NAT/firewall upstream.
  - DNS resolves but TCP 443 times out: firewall/security group/routing/server down.
- Useful checks/tools:
  - OS network status, IP/DHCP lease info, default route, DNS servers.
  - Latency to gateway over Wi‑Fi (jitter spikes suggest RF contention).
  - Channel plan and channel width; neighboring networks scan (where available).

## Security and operational guidance
- Prefer WPA2/WPA3, retire WEP/TKIP; avoid insecure mixed modes.
- WPA‑Enterprise (802.1X + RADIUS) for per‑user/device authentication in enterprise.
- Segment Wi‑Fi (e.g., guest vs internal) using VLANs/firewalls; Wi‑Fi link encryption does not enforce application‑level trust.
- Monitor for rogue APs and misconfigurations; use 802.1X, wireless monitoring, and switch/AP protections.
- Be aware of MAC randomization impacts on per‑MAC policies and DHCP reservations.

## Relationship to broader LAN design
- APs bridge wireless clients to the wired LAN; misusing routers as APs without proper modes can create double‑NAT, duplicate DHCP, and roaming issues.
- Enterprise deployments require channel planning, site surveys, controller tuning, and validation; automatic channel selection is not always optimal.

## Common failure modes (selected)
- Wrong/legacy security settings (WEP/TKIP) or PSK mismatch.
- DHCP misconfiguration or exhausted pools; wrong VLAN tagging to AP SSIDs.
- Interference/congestion due to poor channel plan or channel width choice.
- Sticky roaming or misconfigured fast‑roam features.
- Mesh nodes with weak backhaul links; poor AP placement.
- Client privacy/MAC randomization breaking MAC‑based reservations/policies.

## Key Points
- Wi‑Fi (802.11) is a shared, half‑duplex Layer‑2 wireless LAN; real throughput depends heavily on RF conditions, contention, and configuration.
- Use WPA2/WPA3; WEP/TKIP are obsolete. WPA‑Enterprise with 802.1X/RADIUS enables per‑user/device auth; Wi‑Fi link security does not replace TLS/VPN/app auth.
- Channel planning matters: 2.4 GHz uses 1/6/11 non‑overlapping channels; 5/6 GHz offer more channels but involve DFS/regulatory constraints; wider channels trade capacity for interference susceptibility.
- Roaming is client‑driven; sticky clients and misconfigured fast‑roam features commonly degrade performance.
- Troubleshoot methodically: verify association and IP/DHCP, test gateway reachability, separate RF issues from upstream routing/DNS, and compare Wi‑Fi vs wired performance.