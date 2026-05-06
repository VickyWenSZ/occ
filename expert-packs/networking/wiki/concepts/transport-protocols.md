---
title: Transport Protocols (TCP, UDP, QUIC)
slug: transport-protocols
source: computer-networking-basics
confidence: high
tags: [networking, transport, tcp, udp, quic]
---

# Transport Protocols (TCP, UDP, QUIC)

## Overview and layer placement
- Role: Layer 4 (transport) in the TCP/IP model; provides end-to-end communication between processes using ports. QUIC implements transport-like behavior over UDP.
- Relationship to other layers:
  - Below: IP (IPv4/IPv6) provides addressing and routing.
  - Above: Application protocols (e.g., DNS, HTTP, SSH, SMTP).
  - Security: TLS typically runs above TCP (e.g., HTTPS), while QUIC integrates TLS 1.3-style security into its transport design over UDP.
- Common transports in practice: TCP and UDP dominate; QUIC rides on UDP. SCTP appears in some environments but is out of scope here.

## Ports, sockets, addressing, five-tuple
- Ports identify local endpoints/services on a host. TCP and UDP each have independent port spaces (TCP/53 vs UDP/53 are distinct).
- Server role: listens on a known port; client role: initiates from an ephemeral source port (ephemeral ranges vary by OS/config).
- Socket identity and flow:
  - A TCP or UDP flow is identified by the five-tuple: protocol, source IP, source port, destination IP, destination port.
  - A server socket may bind to specific local addresses or all interfaces (e.g., 127.0.0.1 vs 0.0.0.0 for IPv4).
- Well-known examples (defaults; not guarantees):
  - HTTP: TCP 80
  - HTTPS: TCP 443; HTTP/3 uses QUIC over UDP 443
  - DNS: UDP 53 (and TCP 53 for large/truncated answers, zone transfers, DNSSEC-related cases)
  - NTP: UDP 123
  - SSH: TCP 22
  - DHCPv4: UDP 67/68; DHCPv6: UDP 546/547

## TCP (Transmission Control Protocol)
- Properties:
  - Connection-oriented, reliable, ordered byte-stream.
  - Provides retransmission, duplicate detection, in-order delivery, checksums.
  - Does not preserve message boundaries; applications must implement framing if needed.
- Connection establishment and errors:
  - Three-way handshake:
    ```
    Client → Server: SYN
    Server → Client: SYN-ACK
    Client → Server: ACK
    ```
  - Closed port: server may send RST → “connection refused” (fast failure).
  - Silent drop (e.g., firewall): client retries → “connection timed out.”
  - TCP establishment is separate from TLS negotiation and application success.
- Reliability and control:
  - Reliability: sequence numbers, ACKs, retransmissions, ordering.
  - Flow control: receiver-advertised window prevents overrunning receiver buffers.
  - Congestion control: sender adapts rate to network conditions (e.g., Reno, CUBIC, BBR depending on OS/config).
- Usage:
  - Common for HTTP/1.1, HTTP/2 (often over TLS), SSH, SMTP, IMAP, databases, and many application protocols.
- Operational notes:
  - Throughput degrades with loss and high RTT due to congestion-control behavior.
  - High bandwidth-delay product paths need sufficient window sizes.
  - MTU/PMTUD issues can cause stalls on larger transfers while small packets succeed.

## UDP (User Datagram Protocol)
- Properties:
  - Connectionless, datagram-oriented. No built-in reliability, ordering, retransmission, or congestion control.
  - Has a checksum, but loss/reordering must be handled by the application if required.
- Usage:
  - Low-overhead or latency-sensitive apps, DNS queries, NTP, many real-time media/gaming/tunneling protocols.
  - QUIC uses UDP as its substrate.
- NAT/firewall behavior:
  - Despite being connectionless, stateful devices often track UDP “flows” with timeouts based on outbound packets.
  - Timeout behavior varies; long idle periods may break flows more readily than TCP.
- Diagnostics:
  - Failures often present as application timeouts (no standard handshake to fail fast).
  - Many networks allow TCP 443 but block UDP 443, which affects QUIC/HTTP/3.

## QUIC (over UDP)
- Properties:
  - Modern, encrypted transport running over UDP; provides reliable streams, ordering, congestion control, and TLS 1.3–style security integrated into the transport.
  - Used by HTTP/3 (typically UDP 443).
- Behavior and deployment:
  - When UDP 443 is blocked, clients commonly fall back to HTTPS over TCP (HTTP/2 or HTTP/1.1), depending on client/server support.
  - QUIC reliability is implemented above UDP; firewalls/NATs still apply UDP state/timeout constraints.
- TLS and application negotiation:
  - QUIC integrates TLS; HTTP/3 is selected via ALPN, and SNI still matters for correct virtual host selection.
- Operational notes:
  - Middleboxes that block or rate-limit UDP affect QUIC.
  - Observe path asymmetry between QUIC and TCP-based alternatives during fallback testing.

## TLS interactions (TCP vs QUIC)
- TCP path:
  - TCP establishes first; then TLS handshake starts (e.g., HTTPS).
  - SNI indicates hostname; ALPN selects application protocol (e.g., h2 vs http/1.1).
  - Certificate validation is separate from TCP success; expired/mismatched/untrusted chains cause HTTPS failures despite an open TCP port.
- QUIC path:
  - QUIC integrates TLS 1.3–style security; HTTP/3 runs over QUIC on UDP 443.
  - SNI and ALPN operate within the QUIC/TLS handshake.
- Common TLS failures:
  - Expired cert, hostname mismatch, missing intermediate, untrusted issuer, wrong SNI, client clock skew, TLS interception/captive portal.

## NAT, stateful filtering, and port forwarding
- Stateful filtering:
  - Tracks TCP state; for UDP, uses pseudo-state with timeouts.
  - Asymmetric routing or state loss can break sessions; long-idle UDP is more vulnerable to timeout.
- NAT:
  - Source NAT/PAT maps internal private IP:port pairs to public IP:port.
  - Complicates inbound connections without port forwarding; double NAT or CGNAT can prevent straightforward inbound access.
- Port forwarding:
  - Maps public address:port to internal host:port.
  - Requires: real public reachability, correct protocol/port mapping, stable internal address, listener up, and permissive host/network firewalls.

## Performance considerations
- Latency and loss:
  - TCP throughput is strongly affected by RTT and loss (loss often interpreted as congestion).
  - QUIC implements congestion control similar in spirit to TCP; lossy paths degrade throughput and increase latency for both.
- Jitter:
  - Variation in latency affects real-time apps (often UDP-based), even if average RTT is acceptable.
- Bufferbloat:
  - Excessive queueing under load increases latency; visible during large uploads/downloads.
- Wi-Fi impact:
  - Shared medium, retransmissions, interference, and roaming worsen packet loss and latency before IP/transport processing.

## Diagnostics and observability
- Connection reachability:
  - TCP: test with curl or TCP-specific tools to distinguish “refused” vs “timed out.”
  - UDP/QUIC: verify UDP 443 reachability (HTTP/3) and observe if client falls back to TCP.
- Socket/listener checks:
  - `ss` or `netstat` to confirm services listening on expected address/port (e.g., 0.0.0.0 vs 127.0.0.1).
- Packet capture:
  - `tcpdump`/Wireshark reveal handshake completion, retransmissions, resets, DNS responses, and whether traffic reaches/leaves the host.
  - Encrypted payloads remain opaque; metadata (handshakes, SNI/ALPN visibility in traditional TLS) is still useful.
- Error interpretation:
  - Connection refused: active reject, likely no listener or host firewall rejecting.
  - Connection timed out: path/filtering/routing/NAT problem, or silent drop at destination.
  - TLS errors: certificate/trust/SNI/clock issues; not transport reachability.
- Trace path:
  - Traceroute variants (ICMP/UDP/TCP probes) provide path hints; non-responses at intermediate hops do not prove forwarding loss.

## Common failure modes and fixes
- TCP port closed or wrong bind address:
  - Symptom: fast “connection refused.”
  - Fix: start service, bind to correct interface, adjust host firewall, fix container/Service port publishing.
- Silent filtering/NAT/routing issue:
  - Symptom: “connection timed out.”
  - Fix: open firewall/security group, correct routes/NAT, ensure return path, verify ISP/edge policies.
- UDP/QUIC blocked:
  - Symptom: HTTP/3 fails; client falls back to HTTP/2/1.1; degraded performance.
  - Fix: allow UDP 443, adjust egress policies, confirm stateful device timeouts.
- TLS negotiation/validation failure:
  - Symptom: browser or curl certificate errors.
  - Fix: deploy correct certificate/chain, ensure SNI/ALPN routing, fix clocks/trust stores.
- Dual-stack asymmetry:
  - Symptom: Works over IPv4 but fails over IPv6 (or vice versa).
  - Fix: align listener, firewall, routing, and DNS (A/AAAA) behavior; allow essential ICMPv6.

## Security considerations
- Confidentiality/integrity:
  - Use TLS over TCP (HTTPS) or QUIC-integrated TLS for encrypted/authenticated sessions.
- Exposure control:
  - Avoid unnecessary open ports; least-privilege inbound/outbound rules.
- NAT ≠ firewall:
  - NAT by itself is not a security policy; rely on explicit stateful filtering and application-layer controls.

## Minimal message/flow summaries
- TCP connect:
  ```
  SYN →  SYN-ACK → ACK
  ```
  Then optional TLS handshake, then application data over a reliable byte stream.
- UDP send:
  ```
  Single datagram; no handshake.
  ```
  Application handles any reliability/ordering if desired.
- QUIC (HTTP/3):
  ```
  UDP 443
  QUIC with integrated TLS 1.3–style security
  Reliable, ordered streams; HTTP semantics carried as HTTP/3
  ```

## Key Points
- TCP provides a reliable, ordered byte stream with connection establishment, flow control, and congestion control; UDP provides minimal datagram delivery without built-in reliability; QUIC implements reliable, encrypted streams over UDP and underpins HTTP/3.
- A transport flow is identified by protocol + source/destination IPs + source/destination ports; TCP and UDP have separate port spaces and distinct firewall/NAT handling.
- “Connection refused” implies an active reject (no listener or filtered with RST); “connection timed out” implies silent drop/routing/NAT issues; TLS success/failure is independent of TCP success.
- Blocking UDP 443 disables HTTP/3/QUIC paths and triggers fallback to TCP-based HTTPS, often with performance implications.
- Throughput and latency are shaped by RTT, loss, congestion control, and queueing; Wi‑Fi quality, MTU issues, and bufferbloat frequently dominate user-visible performance.