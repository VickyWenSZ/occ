---
title: Domain Name System (DNS)
slug: dns
source: computer-networking-basics
confidence: high
tags: [dns, networking, name-resolution, protocols, security]
---

# Domain Name System (DNS)

The Domain Name System (DNS) is a distributed, hierarchical, cache-driven naming system that maps human-readable names to data needed by applications, most commonly IP addresses. DNS underpins virtually all Internet activity: an application resolves a name to one or more IPs, then proceeds to establish transport connections. DNS behavior involves authoritative data, recursive resolution, caching and TTLs, failure semantics, transport choices (UDP/TCP), and increasingly, encrypted transports (DoT/DoH).

## Role in the stack and path
- Layering: DNS is an application-layer protocol in TCP/IP terms, but it is foundational to application connectivity.
- Typical flow: application requests resolution; stub resolver queries a recursive resolver; the recursive resolver uses cached data or queries the hierarchy (root → TLD → authoritative) to obtain an answer; result is returned and cached according to TTL.
- Dependencies: IP connectivity to a resolver, transport reachability on UDP/TCP/53 or encrypted DNS ports, correct routing and firewall policy, and often DHCP/VPN-provided resolver configuration.

## Naming, zones, and authority
- Names
  - Hierarchical labels right-to-left (e.g., www.example.com).
  - FQDNs formally end with root “.” (commonly omitted in practice).
  - Domain names are not URLs; URLs include scheme, host, path, etc.
- Zones and authority
  - A zone is an administratively managed subtree (e.g., example.com).
  - Authoritative name servers host zone data and return official answers for their zones; they do not generally perform recursion for arbitrary clients.
  - Delegation: parent zones delegate to child zones via NS records maintained at registrars/registries for public domains.
- Authoritative vs recursive
  - Stub resolver: OS/app component sending queries to a recursive resolver.
  - Recursive resolver: resolves on behalf of clients, using cache and querying authoritative servers as needed; may enforce DNSSEC validation, filtering, split-horizon policy, and other enterprise behaviors.

## Resolution process (recursive lookup)
High-level algorithm to resolve www.example.com:
1. Client asks recursive resolver for A/AAAA (or other) records.
2. If cached and valid per TTL, return cache answer.
3. Else, query a root server for “com” delegation → receive referral to TLD servers.
4. Query a “com” TLD server for “example.com” delegation → receive referral to example.com authoritative servers.
5. Query an authoritative server for “www.example.com” → receive records (or CNAME, or negative response).
6. Cache result per TTL, return to client.
Notes:
- Real behavior includes CNAME following, negative caching, EDNS, DNSSEC, TCP fallback on truncation, resolver-specific policy, and split DNS.
- EDNS client subnet and CDN policies can yield client/location-specific answers.
- Multiple A/AAAA answers are common; clients may implement Happy Eyeballs to race IPv6/IPv4.

## Resource records (selected)
- A: maps name → IPv4 address.
- AAAA: maps name → IPv6 address.
- CNAME: alias to a canonical name. The target must be resolved to yield addresses. Avoid mixing a CNAME with other records at the same owner name (non-apex); providers may implement non-standard ALIAS/flattening at zone apexes.
- MX: mail exchangers for a domain; priority values (lower is preferred). MX targets must themselves resolve to addresses.
- TXT: arbitrary text; widely used for ownership verification, SPF, DKIM, DMARC, and service policies.
- NS: delegation to authoritative servers for a zone.

Operational implications:
- Multiple A/AAAA answers can distribute load and provide redundancy; DNS alone is not health-aware without external integration.
- Dual-stack deployments must ensure both A and AAAA are correct; broken IPv6 combined with client preference for AAAA can cause timeouts mitigated by Happy Eyeballs but still degrade UX.

## Transport and ports
- Standard DNS: UDP/53 for most queries; TCP/53 for zone transfers, large responses, DNSSEC cases, and fallback after truncation (TC=1).
- Encrypted DNS:
  - DoT (DNS over TLS): TCP/853.
  - DoH (DNS over HTTPS): HTTPS over TCP 443 or QUIC over UDP 443 (HTTP/3). Often indistinguishable from general HTTPS by port alone.
- Policy and firewalls:
  - Blocking UDP/53 and/or TCP/53 can break traditional DNS. Some environments mandate DoT/DoH or block them to enforce enterprise resolvers; browsers may use their own DoH independent of OS.

## TTLs and caching
- TTL (Time To Live) controls cache lifetime at resolvers and clients.
- Caching layers: application cache, OS stub, local router, enterprise/ISP/public recursive resolver, plus browser caches.
- Negative caching: NXDOMAIN and some NOERROR/NODATA results are cached; newly created records may appear “missing” until negative caches expire.
- Change management: lower TTLs before planned migrations only helps after older cached entries have already expired.

## Split-horizon, search domains, and VPNs
- Split-horizon DNS: answers vary by source/resolver context (e.g., corporate resolvers return private IPs for internal names, public resolvers do not). Public DNS checkers may not reflect enterprise views.
- Search domains: short names can resolve differently based on provided suffix lists (e.g., via DHCP/VPN), causing “it works on-corp but not off-corp” discrepancies.
- VPN interaction:
  - VPN clients often override resolvers and search domains; split-tunnel DNS may route queries for specific domains to corporate resolvers only.
  - Overlapping address space and DNS returning private addresses without matching routes cause reachability failures.

## Dual-stack behavior and address selection
- A and AAAA can both be present. Clients may:
  - Prefer IPv6, with fallback to IPv4 (Happy Eyeballs).
  - Use OS policies and caching to order attempts.
- Failure modes:
  - Publishing AAAA before IPv6 routing/firewalling is ready causes slow or failed connections.
  - Firewalls allowing IPv4 but not IPv6 can create asymmetric reachability.

## Common failure modes and diagnosis
- DNS resolution failure (symptoms: “name not resolved,” “could not resolve host”):
  - Causes: wrong/blocked resolver, unreachable DNS, expired/missing record, split-horizon mismatch, DNSSEC validation failure, negative cache, typos, captive portal, blocked UDP/TCP 53, VPN DNS override.
  - Tests: query using the client’s configured resolver; compare public vs enterprise vs authoritative; check A vs AAAA; inspect TTL and recent changes; account for split DNS and browser DoH.
- Wrong answers or stale data:
  - Causes: cache staleness, TTL/propagation expectations, policy-based answers, CNAME chain issues, wrong target name.
  - Tests: dig +trace to authoritative; check resolver identity and cache TTLs; flush local caches; test over and off VPN.
- IPv6-only or IPv4-only resolution mismatches:
  - Symptoms: site “works sometimes,” hangs otherwise; Happy Eyeballs masks some issues.
  - Tests: force A-only vs AAAA-only queries and connections; verify server binds/listens on both families; verify ICMPv6 not over-filtered (IPv6 requires ICMPv6 for ND/PMTU).
- Firewall/policy interference:
  - UDP/53 blocked without TCP/53 allowance (or vice versa); DoH allowed while traditional DNS blocked; captive portal hijacking.
- Split DNS/view leakage:
  - Internal names queried on public resolvers return NXDOMAIN; internal resolvers return private IPs. Ensure the client uses intended resolvers and has routes to returned private addresses.

## Security and policy considerations
- Threats and controls:
  - DNS manipulation/redirection: mitigate via resolver policy, DNSSEC validation (where deployed), registrar and zone security, monitoring, and TLS certificate validation at the application layer.
  - Enterprise controls: filtering, logging, split-horizon, and validation on recursive resolvers; careful use of DoH/DoT consistent with policy.
- Misconception correction:
  - “DNS points to a server.” More precise: DNS returns records; an address may point to a server, load balancer, CDN edge, reverse proxy, or other front-end.
- Exposure:
  - Publishing internal-only answers publicly is a common data-leak risk. Keep private zones private; enforce access policy at resolvers and registrars.

## Operations, performance, and change management
- TTL strategy:
  - Balance agility vs load. Short TTLs speed changes but increase query volume and do not override existing caches; long TTLs reduce resolver load but slow change rollouts.
- Health-aware routing:
  - DNS-based distribution alone does not confirm backend health; integrate with health checks only through systems designed for it (e.g., provider DNS with failover).
- CDN and geo policies:
  - Answers can vary by resolver location and EDNS client subnet signaling; testing must include the client’s actual resolver path.
- Planning and hygiene:
  - Maintain accurate NS delegation; validate that authoritative servers are reachable and consistent.
  - Avoid CNAME at apex unless your provider supports ALIAS/flattening semantics.
  - For mail: ensure MX targets resolve correctly and are reachable.

## Tooling and practical diagnostics
- Query tools:
  - nslookup: simple queries against a chosen resolver.
  - dig: detailed DNS interrogation (types, TTLs, flags, authority, +trace).
- What to check:
  - Resolver being used (OS vs browser DoH vs VPN).
  - Record types returned (A, AAAA, CNAME chains, MX/TXT).
  - Response code: NOERROR, NXDOMAIN, SERVFAIL, REFUSED, timeout.
- Response interpretation:
  - NOERROR with answers: success.
  - NOERROR no answers (NODATA): name exists but not for requested type.
  - NXDOMAIN: name does not exist in that view (typo, not delegated, split DNS).
  - SERVFAIL: resolver/authoritative failure, DNSSEC validation error, upstream problem.
  - REFUSED: server policy prohibits answering (e.g., recursion disabled).
  - Timeout: no response (path/firewall/down server).
- Example commands:
  ```bash
  # Query using the system’s default resolver
  dig www.example.com A +ttlunits

  # Query AAAA via a specific resolver
  dig @9.9.9.9 www.example.com AAAA

  # Follow delegation to authoritative servers
  dig +trace www.example.com

  # Inspect MX and TXT for a domain
  dig example.com MX +short
  dig example.com TXT +short
  ```

## Ports and encrypted DNS quick reference
- DNS (classic): UDP 53; TCP 53 (zone transfers, large/truncated responses, DNSSEC/fallback).
- DoT: TCP 853 (resolver-specific support and policy).
- DoH: HTTPS over TCP 443 or QUIC over UDP 443 (policy-dependent; can bypass port-based controls).

## Interactions with DHCP, VPNs, and applications
- DHCP typically provisions resolver IPs and search domains; errors propagate broadly (e.g., clients can reach IPs but cannot resolve names).
- VPNs often override resolvers and establish split-DNS; ensure routes exist to private IPs returned by internal resolvers.
- Browsers may use DoH independently of OS settings; application-specific resolver behavior can diverge from system configuration.

## Troubleshooting playbook (focused)
- Confirm scope: one client vs many; on VPN vs off; IPv4 vs IPv6 specific.
- Identify resolver path: system resolver, enterprise recursive, ISP, public, browser DoH.
- Compare answers:
  - A vs AAAA; public vs enterprise vs authoritative.
  - Check CNAME chains; ensure final addresses resolve.
- Validate transport:
  - UDP/TCP 53 reachability; policy impacts; captive portals.
  - For DoH/DoT environments, validate HTTPS 443 or TLS 853 reachability to resolver endpoints.
- Account for caching:
  - Flush local caches; consider negative caching; re-test after TTL expiry where needed.

## Key Points
- DNS is hierarchical, distributed, and heavily cached; authoritative servers answer for zones, while recursive resolvers fetch and cache answers on behalf of clients.
- Standard DNS uses UDP/53 with TCP/53 fallback; encrypted DNS variants (DoT/DoH) run over TCP 853 and HTTPS 443/UDP 443 respectively and can alter policy/observability.
- TTLs govern caching at many layers; negative caches and split-horizon DNS commonly explain “works here but not there” behaviors.
- Dual-stack answers (A/AAAA) and client address-selection (e.g., Happy Eyeballs) mean partial IPv6 failures can degrade or intermittently break name-based access.
- Effective DNS troubleshooting tests the client’s actual resolver path and interprets DNS response codes (NOERROR, NXDOMAIN, SERVFAIL, REFUSED, timeout) in context of caching, policy, and transport reachability.