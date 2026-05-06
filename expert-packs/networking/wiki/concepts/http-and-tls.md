---
title: HTTP and TLS (HTTPS)
slug: http-and-tls
source: computer-networking-basics
confidence: high
tags: [replace with 3-5 relevant lowercase keywords]
---

# HTTP and TLS (HTTPS)

## Overview and layer placement
- HTTP (Hypertext Transfer Protocol) is an application-layer, request/response protocol for transferring resources (documents, APIs, media). It runs above a transport (TCP or QUIC) and depends on name resolution (DNS) and IP routing.
- TLS (Transport Layer Security) provides encryption, integrity, and endpoint authentication for application protocols. HTTPS is “HTTP over TLS.” In practical TCP/IP layering, TLS usually sits between application protocols (e.g., HTTP) and transport (e.g., TCP). With HTTP/3, security is integrated via QUIC’s TLS 1.3-based handshake over UDP.
- Typical web path sequence: DNS resolution → transport connection (TCP or QUIC) → TLS negotiation and validation → HTTP exchange → application, proxy, or CDN logic.

## Transports, ports, and versions
- Common ports:
  - HTTP: TCP 80 (often only used for redirects or ACME HTTP-01 validation).
  - HTTPS (HTTP over TLS): TCP 443 (HTTP/1.1 or HTTP/2).
  - HTTP/3: QUIC over UDP 443 (falls back to HTTP/2 or HTTP/1.1 if UDP 443 is blocked).
- Transports:
  - HTTP/1.1: text-based over TCP; supports persistent connections; no stream multiplexing.
  - HTTP/2 (RFC 9113): binary framing and multiplexed streams over a single TCP connection; header compression; commonly used with TLS.
  - HTTP/3 (RFC 9114): maps HTTP semantics (RFC 9110) over QUIC (UDP), providing multiplexed, encrypted streams with improved loss recovery; requires UDP 443.

## HTTP semantics
- Request line: method, target (path or absolute-form), version.
- Response: status code, reason phrase (opaque), headers, optional body.
- Methods: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS (and others).
- Status code classes:
  - 2xx success; 3xx redirection; 4xx client-request/authorization issues; 5xx server/upstream failures.
- Notes:
  - HTTP status codes are application-layer results. Valid DNS/transport/TLS can precede an application error (e.g., 403, 404, 500, 502).
  - Connection reuse: HTTP/1.1 persistent connections; HTTP/2 and HTTP/3 multiplexing reduce head-of-line blocking in many cases (though TCP-level HOL still affects HTTP/2).

Example (HTTP/1.1):
```
GET / HTTP/1.1
Host: www.example.com
User-Agent: curl/8.5.0
Accept: */*

HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Content-Length: 1234
...
```

## TLS fundamentals
- Goals: confidentiality, integrity, and endpoint authentication (server authentication is standard; mutual TLS to authenticate clients is possible in some architectures).
- Modern deployments should use TLS 1.3 (RFC 8446) where compatible; older versions and weak ciphers should be disabled by policy.
- Handshake (simplified):
  - ClientHello: includes TLS version, supported cipher suites, extensions such as SNI (hostname) and ALPN (application protocols).
  - ServerHello and certificate: server selects parameters, presents certificate chain, proves key possession.
  - Key establishment and traffic key derivation.
  - Application data protected once handshake completes.
- Endpoint scope: TLS protects traffic between its endpoints. If TLS terminates at a reverse proxy/load balancer, backend hops may be HTTP or separately TLS-protected depending on design.

## Certificates and validation
- A certificate binds a public key to an identity (for HTTPS, a DNS name). Modern clients validate Subject Alternative Name (SAN) entries; Common Name alone is insufficient.
- Validation checks:
  - Chain building to a trusted root (trust store), required intermediate certificates present.
  - Validity period (not expired, not before/after).
  - Name matches requested hostname (including SNI).
  - Appropriate key usage/extended key usage for server auth.
- CAs and trust:
  - Publicly trusted CAs ship in OS/browser/application trust stores; stores differ by platform and versions.
  - Internal/private CAs require distribution of a trust anchor to clients.
- Issuance/operations:
  - Domain Validation (DV) common for public names; automated issuance/renewal is typical (failures often due to DNS/HTTP validation or renewal deployment gaps).
- Common certificate errors: expiration, hostname mismatch, untrusted issuer, incomplete chain, wrong certificate served by SNI, client clock skew, TLS interception/captive portal.

## SNI and ALPN
- SNI (Server Name Indication): client indicates the target hostname during TLS handshake, enabling multi-tenant TLS on a shared IP. Missing/mis-sent SNI commonly yields the “default” certificate and mismatch errors. Older/legacy clients might lack SNI support.
- ALPN (Application-Layer Protocol Negotiation): advertises/negotiates HTTP/2 vs HTTP/1.1 (for TCP-based HTTPS) or HTTP/3 (over QUIC). Mismatched ALPN support can force fallback or failure.

## DNS interactions
- HTTP depends on DNS A/AAAA records for reachability. CNAMEs may alias names; the final target must resolve to addresses.
- Dual-stack nuances:
  - Clients may implement Happy Eyeballs to avoid delays when one family (IPv4/IPv6) is impaired.
  - A site may fail on IPv6 (AAAA present) while IPv4 works; tests must isolate A vs AAAA behavior.
- DNS caching and TTLs can delay changes; split-horizon or VPN DNS may return internal addresses unreachable without proper routes.

## Operational topologies and intermediaries
- Direct origin: client ↔ origin server (TLS at origin).
- Reverse proxy/load balancer:
  - TLS termination at the edge; optional re-encryption to backends.
  - L7 routing by hostname/path/header, compression, caching, auth, and WAF policy.
  - Preserve client identity via standardized forwarding headers (e.g., Forwarded, X-Forwarded-For, X-Forwarded-Proto); trust chain must be explicit to avoid spoofing.
- CDN: edge caches content; origin fetches proceed over HTTPS; failures at CDN, origin, or policy layers can surface as 4xx/5xx.
- Health checks:
  - TCP-level only proves port openness; HTTP-level checks can verify a path/status. Deep checks risk cascading failures if they depend on flaky upstreams.

## Common HTTPS failures and causes
- TCP connect fails:
  - Refused: service not listening, wrong port, host firewall REJECT, container bound to loopback only.
  - Timeout: network/drop by firewall, wrong IP, routing/NAT/egress rule issues, asymmetric path.
- TLS handshake fails:
  - Expired or not-yet-valid certificate; hostname mismatch (SNI/virtual host config); untrusted CA; incomplete chain (missing intermediate); protocol/cipher mismatch; SNI not provided; captive portal or TLS interception; client clock error.
- Application returns error after TLS success:
  - 403 (policy/WAF/auth), 404 (route/object not found), 500 (server/app failure), 502/503/504 (proxy/load balancer/upstream issues, unhealthy backends).
- HTTP/3-specific:
  - UDP 443 blocked: client/server fall back to HTTP/2 or HTTP/1.1; if fallback disabled or incompatible, requests fail.
- Dual-stack asymmetry:
  - AAAA exists but IPv6 path/firewall/ICMPv6 blocked; service listens only on IPv4; security groups allow IPv4 but not IPv6.

## Diagnostics and tooling
- curl:
  - Phase visibility with verbose: `curl -v https://www.example.com/`
  - Follow redirects: `-L`
  - Override DNS for testing: `--resolve www.example.com:443:203.0.113.10`
  - Force IPv4/IPv6: `-4` or `-6`
  - Check TLS details: `--cert-status` (OCSP stapling), `--tlsv1.3` to constrain versions (compatibility permitting)
- DNS:
  - `dig A/AAAA/CNAME www.example.com`
  - Compare recursive resolver vs authoritative; check TTLs and CNAME chains.
- Transport reachability:
  - TCP connect tests (e.g., `curl --connect-timeout 5 https://host/`, `Test-NetConnection -ComputerName host -Port 443` on Windows).
- Server-side checks:
  - Listening/bind: `ss -lntp`/`netstat -an` to confirm 0.0.0.0 vs 127.0.0.1 (and ::/::1) bindings.
  - Logs: web server, reverse proxy, load balancer health check, WAF.
- Packet capture:
  - `tcpdump`/Wireshark show SYN/SYN-ACK, TLS ClientHello/SNI/ALPN, resets, retransmissions; payload opaque under TLS by design.

## Load balancers, proxies, and TLS termination pitfalls
- Wrong or missing certificate (including SNI mapping).
- Backend protocol mismatch (LB sends HTTP to a backend expecting HTTPS or vice versa).
- Health check misconfig (wrong path/host header/status/port; missing intermediate cert for HTTPS checks).
- Backend listening only on loopback; security group/firewall not allowing LB source.
- Redirect loops (improper X-Forwarded-Proto handling, mixed HTTP/HTTPS policies).
- Host-based routing requires correct Host header; ensure LB/proxy preserves or sets it.

## Security considerations
- HTTPS authenticity hinges on correct certificate validation. Do not bypass certificate errors outside controlled diagnostics.
- HSTS can enforce HTTPS-only access for domains that publish it, reducing downgrade risk.
- TLS interception (enterprise forward proxies) requires trusted enterprise CA distribution to avoid client warnings.
- “HTTPS” applies to the segment where TLS terminates; internal hops may require re-encryption or mTLS in sensitive environments.
- Time synchronization (e.g., NTP) is critical for certificate validity checks and many auth systems.

## End-to-end flow: opening an HTTPS website (condensed)
1. Browser parses URL; checks caches/HSTS/proxy configuration.
2. Resolve hostname via DNS; follow CNAMEs; choose A vs AAAA (Happy Eyeballs may race both).
3. Establish transport:
   - TCP 443 (HTTP/1.1 or HTTP/2) or QUIC UDP 443 (HTTP/3).
4. TLS handshake:
   - ClientHello with SNI/ALPN → server certificate chain → validation → keys established.
5. HTTP request/response:
   - Send method/headers/body; receive status/headers/body; possibly multiple requests over same connection or multiplexed streams.
6. Intermediaries (optional):
   - CDN/WAF/reverse proxy/LB route to backends; health checks govern target selection.
7. Browser fetches additional assets (often different hostnames), repeating DNS/TLS/HTTP as needed; connections may be reused.

## HTTP status codes: infrastructure-relevant cues
- 301/302/307/308: redirect; validate scheme/host/path to avoid loops.
- 401/403: missing/failed auth or WAF/policy block.
- 404: wrong route/path/virtual host or missing resource.
- 500: server/application error.
- 502: bad gateway; upstream connect/TLS/app error from proxy/LB.
- 503: unavailable; no healthy capacity or maintenance.
- 504: gateway timeout; upstream too slow or unreachable.

## Common remediation patterns
- Certificate issues: renew and deploy to all endpoints; include intermediates; ensure hostname in SAN; fix SNI routing; correct client clock.
- Transport issues: open required ports (TCP 443, optionally UDP 443), correct security groups/firewalls/ACLs; ensure return paths/NAT; avoid asymmetric routing.
- Dual-stack: verify IPv6 listeners, routes, firewall rules, and ICMPv6; remove premature AAAA until path is ready.
- Proxy/LB routing: fix listener protocol/port, host/path rules, health checks, backend bind address, and forwarded headers.
- DNS: correct records/TTL; ensure split-horizon/VPN DNS returns reachable addresses; align CDN CNAMEs.

## Example curl-based triage
```
# Show DNS/TCP/TLS/HTTP phases
curl -v https://www.example.com/

# Force IPv4 vs IPv6
curl -4v https://www.example.com/
curl -6v https://www.example.com/

# Test specific IP + SNI/Host mapping
curl -v --resolve www.example.com:443:203.0.113.10 https://www.example.com/

# Follow redirects and show headers
curl -v -L -I https://www.example.com/

# Constrain TLS version (diagnostic only)
curl -v --tlsv1.3 https://www.example.com/
```

## Key Points
- HTTPS = HTTP over TLS. Modern stacks use HTTP/2 over TCP 443 or HTTP/3 over QUIC (UDP 443), with ALPN negotiating the protocol and SNI selecting the certificate/virtual host.
- Certificate validation (chain trust, SAN hostname, validity, intermediates) is foundational; most HTTPS failures stem from misissued/expired/misdeployed certs or SNI/chain errors.
- DNS, dual-stack behavior, and caching directly impact HTTP reachability and performance; test A vs AAAA explicitly and account for Happy Eyeballs.
- Proxies/CDNs/load balancers add power and failure modes: termination points, forwarded headers, health checks, and backend protocol mismatches must be correct.
- Diagnostic rigor (curl -v, dig, socket/listen checks, and packet capture) separates transport/TLS failures from application-layer errors (4xx/5xx).