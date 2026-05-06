---
title: Proxies and Load Balancers
slug: proxies-and-load-balancers
source: computer-networking-basics
confidence: high
tags: [replace with 3-5 relevant lowercase keywords]
---

# Proxies and Load Balancers

Proxies and load balancers are intermediary systems that terminate, forward, transform, or distribute traffic between clients and services. They are deployed to enforce policy, improve scalability and availability, centralize TLS, provide observability, and control egress/ingress. They also introduce distinct failure modes that must be understood and monitored.

## Taxonomy and roles

- Forward proxy (client-side intermediary)
  - Receives client requests and fetches resources on the client’s behalf.
  - Used for egress control, web filtering, logging, malware scanning, DLP, and authentication.
  - May be explicit (client configured) or transparent/intercepting.
  - TLS interception requires enterprise-trusted CA; otherwise clients see certificate errors.
  - Application behavior varies: some honor system proxy settings; others need explicit configuration.

- Reverse proxy (server-side intermediary)
  - Exposes services to clients; forwards to one or more internal backends.
  - Capabilities: TLS termination, hostname/path routing, header/cookie-based routing, compression, caching, authentication, WAF inspection, rate limiting, logging.
  - Preserving client identity: adds X-Forwarded-For or standardized forwarding headers; trust must be constrained to known, authenticated proxies to prevent spoofing.
  - Commonly front-ends application tiers, APIs, and microservices.

- Load balancer (distributor across backends)
  - Layer 4 (transport-level) or Layer 7 (application-level) distribution.
  - Algorithms: round robin, least connections, hash-based (e.g., source-IP or header), weighted distribution, latency/health-aware selection.
  - Improves availability and capacity; does not make applications stateless. Session state, cookies, shared storage, and backend dependencies remain critical.

- Middlebox layering note
  - Many “load balancers” are also reverse proxies (full-proxy mode) and can operate at L7; others forward at L4 without parsing application protocols.
  - Firewalls, NAT, proxies, and load balancers can coexist and each introduce independent policy and state.

## TLS handling models

- TLS termination at proxy/LB
  - TLS ends at the intermediary. Enables L7 routing and policy, simplifies certificate management.
  - Backend hop can be HTTP or separately re-encrypted (TLS to backend, often with mTLS in sensitive environments).
  - Typical issues: wrong certificate, SNI not routed/recognized, unsupported TLS version/ciphers, missing intermediates, failed backend TLS validation, incorrect X-Forwarded-Proto causing redirect loops.

- TLS passthrough
  - Intermediary forwards encrypted traffic without decryption; preserves end-to-end TLS but limits L7 routing/inspection.

- SNI and ALPN
  - SNI lets clients indicate hostname for correct certificate/virtual host selection on shared IPs.
  - ALPN negotiates HTTP versions (e.g., HTTP/2). HTTP/3 uses QUIC over UDP 443; if UDP 443 is blocked, clients fall back to HTTP/2/1.1.

## Health checks and availability

- Health check types
  - TCP: validates port acceptance only.
  - HTTP/HTTPS: validates status code/path, possibly with headers (e.g., Host).
  - Deep/app-specific: validates dependencies (DB, cache); too deep can remove excessive capacity during partial outages.

- Common misconfigurations
  - Wrong path, port, protocol, or expected status code.
  - Missing Host header or SNI; TLS mismatch or cert validation failure on the check itself.
  - Authentication required for health endpoint.
  - Network blocks between balancer and backend (ACLs, firewalls, security groups).

## Client identity and scheme propagation

- Preserving original client IP to backends
  - Headers: X-Forwarded-For and standardized Forwarded headers.
  - L4 metadata: PROXY protocol supported by some LBs/backends.
  - Security: accept and trust these only from known, authenticated intermediaries; otherwise spoofing corrupts logs, geo/policy, and security decisions.

- Preserving scheme/port
  - X-Forwarded-Proto and X-Forwarded-Port commonly used.
  - Misuse leads to redirect loops (e.g., backend thinks request is HTTP and redirects to HTTPS while the reverse proxy already terminates TLS).

## Operational behaviors and constraints

- L4 vs L7 selection
  - L4 is simpler, lower overhead, and protocol-agnostic (TCP/UDP). No content-based routing.
  - L7 enables hostname/path/header/cookie routing, compression, caching, auth, WAF, logging with request metadata, and A/B or canary strategies.

- HTTP versions and transports
  - HTTP/1.1: persistent connections; head-of-line blocking at the application layer.
  - HTTP/2: multiplexing over a single connection (commonly over TLS); header compression.
  - HTTP/3: QUIC over UDP 443; middlebox/egress policies must allow UDP 443 or expect fallback.

- State, sessions, and persistence
  - Load balancing does not remove application statefulness. If sessions are stored locally on backends, request distribution can break user workflows unless application/session design or LB routing accounts for this.
  - Backends should be designed for scale-out where possible (external session stores, idempotent operations, careful retry semantics).

- Egress control via forward proxies
  - Organization-wide policy sometimes requires all outbound HTTP(S) through a forward proxy.
  - Applications may fail if proxy config is missing or authentication to proxy fails—even when raw Internet connectivity is fine.

## Common failure modes (symptoms and likely causes)

- 502 Bad Gateway / 503 Service Unavailable / 504 Gateway Timeout
  - Upstream/backends unhealthy or unreachable, wrong target port, health check failure, protocol mismatch (HTTP vs HTTPS), missing Host header, backend security group/firewall blocking LB source, no targets in AZ/subnet.

- Connection refused to LB or proxy
  - Listener on wrong port/protocol; process not running; binding only to loopback; host firewall actively rejecting.

- Connection timed out
  - Firewall or ACL silently dropping, wrong IP/route, NAT or return path issue, security group deny, server down without reject, asymmetric routing.

- TLS certificate errors
  - Expired/mismatched cert, missing intermediate, untrusted issuer (private CA without trust), wrong SNI/virtual host, client clock wrong, TLS interception without installed trust anchor.

- Wrong client IP at backend
  - Missing PROXY protocol or forwarding headers; incorrect trust chain causes backend to log/load-balance on proxy IP; security analytics broken.

- HTTP/3 impaired
  - UDP 443 blocked; client falls back to HTTP/2/1.1 with potential performance or behavior differences.

## Diagnostics and observability

- Fast checks
  - curl -v https://host/ to see DNS/TCP/TLS/HTTP phases and response codes.
  - Test HTTP vs HTTPS and verify redirects; validate certificate SANs and chain; confirm SNI by targeting hostname.
  - Force IPv4 vs IPv6 to detect dual-stack asymmetry; verify UDP 443 for HTTP/3 where relevant.

- Backend reachability and listeners
  - On servers/containers: ss/netstat to confirm listening address/port (avoid 127.0.0.1-only binds for externally served apps).
  - In cloud: verify security groups, network ACLs, and target group health; ensure backends allow LB source ranges or LB SG.

- Health checks
  - Confirm path, expected status, headers (Host), and TLS settings match backend expectations.
  - Ensure health endpoints do not require auth unless the LB supports and is configured for it.

- Packet-level proof
  - tcpdump/Wireshark on client and backend to confirm SYN/SYN-ACK, TLS ClientHello/SNI, resets/timeouts, retransmissions.
  - For MTU suspicions (tunnels, VPNs), test reduced MSS or use PMTUD-aware tools.

- DNS and routing context
  - DNS-based distribution alone does not guarantee health-aware load balancing; caches and TTLs affect change propagation.
  - Compare records (A/AAAA/CNAME) seen by the affected client/resolver vs authoritative answers; consider split-horizon or VPN resolvers.

## Cloud- and container-specific considerations

- Cloud load balancers
  - Components: listeners, target groups/pools, health checks, certificates, subnet/AZ attachments.
  - Frequent issues: wrong listener/target port, missing or wrong cert, failing health check path, backends bound to localhost only, backend SGs not permitting LB sources, subnets/AZs not attached, required headers (Host) missing, proxy protocol or forwarded headers mismatch.

- Security groups and ACLs
  - Statefulness and direction matter. Outbound/return traffic may be implicitly allowed or explicitly required depending on platform.
  - Check all enforcement points: LB listener, LB SG, subnet ACL, instance SG, OS firewall, route tables, Kubernetes NetworkPolicy.

- Kubernetes and ingress
  - Service types: ClusterIP (internal), NodePort, LoadBalancer (provisions cloud LB), ExternalName.
  - Ingress exposes HTTP/HTTPS via rules (host/path) but requires an ingress controller.
  - Common failures: no controller or class mismatch, wrong DNS to LB, missing/invalid TLS secret, host/path rule mismatch, Service selector mismatch (no endpoints), readiness probe failing (pods removed), NetworkPolicy blocking traffic, CoreDNS issues.
  - Containers and binding: process listening on 127.0.0.1 inside container is not reachable externally unless proxied; EXPOSE in images is metadata—explicit port publishing is required.

## Policy and security

- Egress and zero trust
  - Forward proxies enforce egress policies; identity-aware proxies and WAFs enforce app-level access and inspection.
  - Zero trust emphasizes identity and context over network location; proxies/LBs are key enforcement points but must be paired with strong auth and least-privilege policies.

- Header trust model
  - Never trust X-Forwarded-For/Forwarded from arbitrary clients. Terminate or sanitize at known edges; accept only from trusted intermediaries (by IP, mTLS, or auth).

- TLS interception
  - Requires corporate root CA on clients; otherwise certificate warnings/errors. Clearly document scope and impacts (e.g., on certificate pinning and protocol support).

## Structured troubleshooting playbooks

- LB returning 502/503
  - Verify listener/target ports and protocols; check target group health and health check path/status/headers/TLS; confirm backend SG/firewall; inspect backend logs; align HTTP vs HTTPS expectations; ensure all AZs/subnets attached and targets registered.

- Works via ping but fails over HTTPS
  - ICMP != TCP 443. Use curl -v to identify TCP/TLS/HTTP failure point; validate cert/SAN/SNI/clock; check proxy requirement; test firewall egress/ingress on 443.

- Connection refused vs timed out
  - Refused: no listening service or active reject; check bind address/port and host firewall.
  - Timed out: silent drop/routing/NAT; traceroute/TCP traceroute; inspect SG/ACL/firewall; packet capture to locate drop.

- Container service unreachable externally
  - Ensure service listens on container interface (0.0.0.0 inside container if appropriate); publish/map host ports; open host/SG firewalls; in Kubernetes, check Service selector/targetPort, endpoints, readiness, Ingress rules.

- Dual-stack inconsistency
  - Validate A vs AAAA; confirm LB/listeners/firewalls on IPv6; ensure ICMPv6 allowed; confirm backends bind on IPv6 and cert/SNI routing matches.

## Interactions with HTTP status codes

- 4xx often indicates client/auth/WAF/policy issues (e.g., 401/403); 404 can be missing route or wrong virtual host on reverse proxy.
- 5xx often indicates upstream/backend failure or proxy/LB timeout behavior (500 app failure; 502 bad gateway to upstream; 503 no capacity/unhealthy targets; 504 upstream timeout).

## Practical test snippets

- Inspect end-to-end HTTPS phases with explicit Host and SNI routing
  ```
  curl -v https://www.example.com/
  ```
- Test specific backend via LB VIP using Host header (diagnostics only; ensure routing/policy allows)
  ```
  curl -v -H "Host: www.example.com" https://<lb-address>/
  ```
- Force address family to detect dual-stack issues
  ```
  curl -4 -v https://www.example.com/
  curl -6 -v https://www.example.com/
  ```

## Key Points

- Proxies (forward/reverse) and load balancers add scalability, policy, and observability but introduce distinct routing, TLS, and header-trust failure modes.
- L7 load balancers enable hostname/path/header routing and policy; L4 devices distribute flows without parsing application protocols.
- TLS termination at the edge changes trust boundaries; SNI, certificates, and X-Forwarded-Proto/X-Forwarded-For must be correct and trusted only from known intermediaries.
- Accurate, appropriately scoped health checks are essential; misconfigured paths, headers, or TLS quickly cause widespread 502/503/504 errors.
- Cloud/Kubernetes add layers: security groups/ACLs, target groups, Ingress/Service objects, readiness/endpoints, and NetworkPolicy all affect reachability and must be verified end-to-end.