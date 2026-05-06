---
title: Firewalls and Security Groups
slug: firewalls-and-security-groups
source: computer-networking-basics
confidence: high
tags: [networking, security, firewalls, cloud, security-groups]
---

# Firewalls and Security Groups

## Definition and Scope

Firewalls and security groups enforce traffic policy by permitting or denying flows based on attributes such as IP prefixes, ports, protocols, interfaces/zones, and sometimes application identity and content. Filtering can exist at multiple layers and locations:
- Hosts (endpoint firewalls)
- Network devices (routers, dedicated firewalls, NGFWs)
- Cloud platforms (security groups, subnet/network ACLs, managed WAFs)
- Intermediaries (proxies, load balancers, service meshes)

Filtering may be:
- Layer 3/4: IP/port/protocol rules, connection/state tracking
- Layer 7: application and content-aware (e.g., HTTP host/path, DNS, user identity, TLS inspection)
- Stateless: each packet matched in isolation
- Stateful: connection/flow state tracked to allow return traffic without explicit reverse rules

Firewalls are distinct from NAT. NAT translates addresses/ports; many devices co-implement NAT with stateful filtering, but translation and policy enforcement are separate functions.

## Policy Models and Rule Evaluation

- Default policy: commonly “default deny” inbound; outbound may be default allow or deny depending on environment.
- Rule order: many systems are first-match. Shadowing occurs when an earlier, broader rule masks later rules.
- Implicit rules: platforms may include non-obvious implicit allows/denies; always inspect the effective policy.
- Objects: policies often use address groups, FQDN objects, security group references, or tags. DNS-based objects depend on resolver behavior and cache TTLs.

## Types of Firewalls

### Host Firewalls
- Examples: Windows Defender Firewall, Linux nftables/iptables-based (often via firewalld/ufw), macOS application firewall features, endpoint security suites.
- Capabilities: inbound and outbound control; profile-aware behavior (public/private/domain).
- Common pitfalls:
  - Service listening but bound to loopback only (127.0.0.1/::1)
  - Inbound rules missing or direction reversed
  - Outbound restrictions silently blocking egress to DNS, NTP, APIs

### Network Firewalls (Physical/Virtual/NGFW)
- Placement: Internet edges, data center boundaries, inter-VLAN segmentation points, cloud edges.
- Capabilities (product-dependent): L3/4 ACLs, L7 app-ID, user-ID, URL categories, TLS inspection, IPS, geo/policy controls, threat intel.
- Operational nuances:
  - Zone/interface scoping matters
  - Rule order and default policies are critical
  - Asymmetric routing can break state tracking
  - State sync required for HA pairs to avoid session drops on failover

### Cloud Security Groups
- Virtual, stateful firewalls attached to instances, ENIs, load balancers, managed databases, etc. Behavior differs by provider.
- Properties:
  - Often stateful: replies to allowed outbound are auto-allowed inbound (and vice versa)
  - Attach to resources, not subnets (contrast with subnet/network ACLs, which are often stateless)
- Common failure modes:
  - Confusing security groups with route tables, network ACLs, OS firewalls, or service access policies
  - Forgetting to allow traffic from load balancer subnets or LB-attached security group
  - Egress overlooked, breaking API calls, DNS, NTP, package updates
  - IPv6 rules missing (dual-stack asymmetry)
- Related controls:
  - Subnet/network ACLs: often stateless, order-sensitive, and evaluated in addition to security groups
  - Internet/NAT gateways: route prerequisite for public/egress connectivity; not security controls by themselves

## Stateful Filtering and Connection Tracking

- TCP: track SYN/SYN-ACK/ACK, established state; return traffic allowed for established flows.
- UDP: pseudo-state tracked by recent traffic with timeouts; firewall may expire idle flows quickly.
- ICMP/ICMPv6: essential control traffic (notably ICMPv6 for Neighbor Discovery, PMTU); blanket blocking breaks IPv6.
- Failure/scale considerations:
  - State table exhaustion drops new flows
  - Idle timeout breaks long-lived but idle sessions
  - Asymmetric routing prevents matching return traffic to existing state
  - HA failover without state sync causes session resets

## Inbound vs Outbound (Egress) Controls

- Inbound: controls traffic entering an interface/zone/resource. Public service reachability also requires listening services, correct binding, return routes, NAT/public IP correctness, and upstream port availability.
- Outbound/egress: often overlooked. Egress deny can break DNS, OCSP/CRL, NTP, API calls, package updates, and web access (even if inbound is fine). Proxies may be required by policy.

## Relationship to NAT and Port Forwarding

- NAT is not a firewall. Common NAT/PAT behavior impedes unsolicited inbound only because no translation state exists.
- Port forwarding exposes internal services via a public address/port mapping and requires:
  - Public reachability (no CGNAT or double NAT blocking)
  - Correct protocol/port mapping
  - Stable internal address and return path
  - Host firewall allowance, service listening, and ISP not blocking the port
- Double NAT and CGNAT complicate inbound access and some peer-to-peer/VPN protocols.

## Layer 7 Inspection, TLS, and WAF

- NGFWs can inspect L7 traffic (HTTP, DNS, etc.) to enforce application policies.
- TLS interception requires enterprise-trusted CA; otherwise clients see certificate errors. Inspection increases complexity and CPU cost.
- Web Application Firewalls (WAFs) typically sit as reverse proxies, applying HTTP/S-specific rules (e.g., request normalization, signature/behavior checks). They complement but do not replace L3/4 firewalls.

## Rule Elements and Objects

Typical match/action dimensions:
- Source/destination IP/CIDR (IPv4 and IPv6), address groups, security group references
- Protocol: TCP, UDP, ICMP/ICMPv6, others
- Ports: exact, ranges, service objects
- Direction and interface/zone
- Application/user identity (where supported)
- Time windows, QoS/markings (product-dependent)
- Logging action (allow/deny with log)

## Logging, Monitoring, and Operations

- Log both denies and key allows (with 5-tuple, action, rule ID). Ensure NTP is correct for correlation across systems.
- Validate effective policy after changes; document rule owner, justification, review/expiration.
- Monitor:
  - Throughput and conntrack/state table usage
  - Drop counters and top denies
  - Health of HA pairs and state replication
  - TLS inspection certificate validity and distribution

## Performance and Capacity

- Capacity bounds include throughput (L3/L7), concurrent sessions, new connections per second, NAT table size, and inspection CPU.
- TLS inspection and L7 features materially reduce effective capacity; plan headroom and test under realistic traffic mixes.

## Common Failure Modes (and Diagnoses)

- Missing allow rule or wrong direction (symptom: timeouts)
- Wrong protocol/port (TCP vs UDP mismatch; health checks using unexpected method)
- Rule shadowing by earlier broader rule
- State table exhaustion or idle timeout
- Asymmetric routing (stateful deny on return path)
- App-ID misclassification; FQDN object not resolving as expected
- Host bound to loopback; firewall allows but service unreachable externally
- Security group allows LB→instance, but subnet ACL blocks, or vice versa
- IPv6 blocked while IPv4 allowed; missing ICMPv6 (breaks ND/PMTU)
- Egress deny: DNS/NTP/API failures; HTTP works only via proxy if policy requires it
- Port forwarding defined but upstream CGNAT/double NAT prevents inbound
- Cloud LB health checks blocked by backend firewall or incorrect path/host header

Required data to troubleshoot effectively:
- 5-tuple: src IP, dst IP, protocol, src port, dst port
- Direction and enforcement points along path (host firewall, security group, subnet ACL, edge firewall, mesh policy)
- Transport-level evidence (RST=refused vs silent drop=timeout)
- Packet captures/logs at ingress/egress of enforcement points

## Examples

### Minimal Linux nftables (stateful allow outbound, limited inbound)
```bash
# nftables example (simplified)
table inet filter {
  chains {
    input { type filter hook input priority 0; policy drop;
      ct state established,related accept
      iif lo accept
      tcp dport { 22, 443, 80 } accept
      icmp type echo-request accept
      ip6 nexthdr icmpv6 accept # allow essential ICMPv6
      log prefix "FW-DROP " counter drop
    }
    output { type filter hook output priority 0; policy accept; } # review for egress policy
    forward { type filter hook forward priority 0; policy drop; }
  }
}
```

### Conceptual cloud security group (stateful)
```json
{
  "inbound": [
    { "proto": "tcp", "port": 443, "source": "0.0.0.0/0" },
    { "proto": "tcp", "port": 22,  "source": "198.51.100.0/24" },  // admin subnet
    { "proto": "tcp", "port": 443, "sourceSecurityGroup": "alb-sg" } // allow from LB
  ],
  "outbound": [
    { "proto": "udp", "port": 53,  "dest": "10.0.0.53/32" },       // DNS
    { "proto": "udp", "port": 123, "dest": "0.0.0.0/0" },          // NTP
    { "proto": "tcp", "port": 443, "dest": "0.0.0.0/0" }           // HTTPS egress
  ]
}
```

## Best Practices

- Enforce least privilege: scope by source/destination, protocol, and port; segment networks (VLANs/subnets/zones) and control inter-segment flows.
- Treat IPv6 as first-class: mirror IPv4 policy, allow essential ICMPv6, validate dual-stack reachability.
- Avoid relying on NAT for security; use explicit stateful policies and logging.
- For HA pairs, synchronize state and config; test failover.
- Permit health checks explicitly (correct path/host/proto) and allow LB→backend traffic sources.
- Document rule intent, owner, and review/expiry; remove stale exceptions.
- For TLS inspection, manage enterprise CA distribution and capacity; provide bypasses for protocols that break with interception.
- Validate across all enforcement layers: host firewall, security groups, subnet ACLs, route tables, proxies, service mesh/network policies.

## Interactions with Related Components

- Proxies/load balancers: may terminate TLS, apply L7 policy; backend firewalls must allow traffic from proxy/LB addresses or groups; health checks require specific allowances.
- DNS: FQDN-based rules depend on resolver behavior and TTL; egress blocks on UDP/TCP 53 or DoH/DoT can alter application behavior.
- VPNs: full vs split tunneling changes routes and DNS; overlapping subnets complicate policy application and reachability.
- Containers/Kubernetes: host firewalls, CNI plugins, and Kubernetes NetworkPolicy interact; a pod listening on 127.0.0.1 is not externally reachable even if firewalls allow; ensure policies permit DNS to CoreDNS and ingress/egress paths.
- Home networking: consumer routers combine NAT+stateful firewall; CGNAT and ISP port blocks limit inbound; IPv6 commonly defaults to blocking unsolicited inbound.

## Diagnostic Playbook Snippets

- Connection refused vs timed out:
  - Refused: port closed/actively rejected (service not listening, host firewall reject)
  - Timed out: silent drop/routing blackhole/security group/ACL deny
- “Works on IPv4, fails on IPv6”:
  - Check AAAA, IPv6 listener, IPv6 SG/firewall rules, ICMPv6, routes
- “LB returns 502/503”:
  - Verify backend health check path/host/proto, backend listening/bind address, backend firewall/SG allowing LB sources, protocol mismatch (HTTP vs HTTPS)

## Key Points

- Firewalls enforce traffic policy; security groups are cloud-native, stateful firewalls attached to resources. NAT is not a firewall.
- Stateful filtering simplifies return-traffic handling but requires correct routing symmetry, adequate state capacity, and ICMP/ICMPv6 allowances.
- Effective reachability depends on all layers: host firewall, security groups, subnet ACLs, routes/NAT, proxies/LBs, and application binding.
- Egress controls are often the root cause of “can’t reach API/DNS/NTP” failures; log and monitor both denies and key allows.
- Dual-stack parity matters: mirror IPv4 and IPv6 policies and allow essential ICMPv6 to avoid breaking Neighbor Discovery and PMTU.