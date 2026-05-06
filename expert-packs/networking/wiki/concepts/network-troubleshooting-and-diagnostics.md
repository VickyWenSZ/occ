---
title: Network Troubleshooting and Diagnostic Tools
slug: network-troubleshooting-and-diagnostics
source: computer-networking-basics
confidence: high
tags: [networking, troubleshooting, diagnostics, tools, tcp/ip]
---

# Network Troubleshooting and Diagnostic Tools

This page compiles a practical, layer-aware methodology and the core diagnostic tools used to isolate and resolve network problems across Ethernet/Wi‑Fi links, IP routing, transport (TCP/UDP/QUIC), DNS, HTTP/TLS, firewalls/NAT, VPNs, cloud/container overlays, and performance issues. It emphasizes disciplined scoping, correct tool selection, and careful interpretation to avoid false conclusions.

## Layered troubleshooting flow (disciplined checklist)

Progress methodically from local state to application, changing one variable at a time.

1) Define symptom and scope
- Precisely state the failure: target name/IP/port, client(s) affected, network context (LAN, Wi‑Fi SSID, VPN, cloud, container), time window.
- Determine blast radius: one device, one subnet/VLAN, one site/region, one application/host, one address family (IPv4 vs IPv6), or everyone.

2) Verify local link and IP configuration
- Interface/SSID/cable up? Proper VLAN/port? Valid IP, subnet/prefix, default gateway, DNS servers?
- Commands:
  - Windows: `ipconfig /all`
  - Linux: `ip addr; ip route; ip -6 route; ip link; ip neigh`
  - macOS: `ifconfig; netstat -rn; scutil --dns`

3) Test local L2/L3 reachability
- Ping self and loopback to validate stack: `ping 127.0.0.1`, `ping ::1`
- Ping own IP, then default gateway (prefer both IPv4 and IPv6).
- If gateway unreachable: suspect Wi‑Fi auth/VLAN/port, ARP/ND failure, cable/AP/switch issues.

4) Test routed IP reachability
- Ping a known external IP (bypasses DNS): e.g., `ping 1.1.1.1` and `ping -6 2606:4700:4700::1111`
- If gateway works but external IP fails: suspect WAN/NAT/firewall/ISP/routing.

5) Test DNS resolution
- Resolve the exact failing hostname using the client’s configured resolver.
- Compare with a public resolver and with authoritative answers if needed.
- Commands:
  - `nslookup name resolver_ip`
  - `dig name A +ttl +nocomments @resolver`
  - Check A vs AAAA; beware split-horizon and browser DoH.

6) Test transport/port reachability
- Distinguish refused vs timed out.
- Commands:
  - Windows: `Test-NetConnection host -Port 443`
  - Linux: `curl -v telnet://host:443` or `curl -v --connect-timeout 5 https://host/`
  - TCP traceroute as available: `traceroute -T -p 443 host`

7) Test TLS and HTTP semantics
- Use verbose HTTP client to see where it fails (DNS/TCP/TLS/HTTP).
- `curl -v https://host/` (check SNI, certificate chain/hostname/expiry, ALPN, redirects, HTTP status).

8) Compare working vs failing paths
- Same client over different networks (Wi‑Fi vs Ethernet, VPN vs direct)?
- Same destination over IPv4 vs IPv6?
- Same request via proxy vs direct?
- Same service through load balancer vs backend IP?

9) Inspect policy devices and captures
- Verify firewall/security group rules (src/dst IPs, ports, protocol, direction, zone/interface).
- Check NAT, routes, health checks, proxy rules.
- Packet capture at client/server edges confirms whether SYNs/ACKs, DNS responses, ICMP errors, TLS handshakes appear.

## Core diagnostic tools and what they prove

Reachability and path
- ping: ICMP echo RTT/reachability. Success proves only ICMP reachability; failures can be due to ICMP filtering.
- traceroute/tracert: apparent forward path via TTL/hop-limit expiry; probe type matters (UDP/ICMP/TCP). Asymmetry and non-responding hops are common.

Local state and routing
- Windows: `ipconfig /all`, `route print`, PowerShell `Get-NetIPConfiguration`
- Linux: `ip addr`, `ip route`/`ip -6 route`, `ip neigh`, `nmcli`, `resolvectl`
- macOS: `ifconfig`, `netstat -rn`, `scutil --dns`
- Interpretation: wrong/missing default gateway, wrong subnet mask/prefix, stale/failed ARP/ND, unexpected VPN or policy route.

Sockets and listeners
- Linux: `ss -lntup` (preferred), `netstat -anp`
- Windows: `netstat -ano`, `Get-NetTCPConnection`
- Use to confirm a service is listening on the expected IP/port/interface (not only on loopback), process-ID correlation, abnormal TCP states (SYN-SENT, TIME-WAIT).

DNS resolvers and records
- nslookup: quick answers from selected resolver.
- dig: detailed RRsets, TTLs, CNAME chains, response codes (NOERROR, NXDOMAIN, SERVFAIL), and which server answered.
- Always test the client’s actual resolver (VPN, split DNS, DoH can differ from OS settings).

HTTP/TLS client
- curl: end-to-end URL diagnostics (DNS → TCP/QUIC → TLS → HTTP). Useful flags:
  - `-v` verbose; `--resolve host:port:ip` test name-to-IP mapping; `-4`/`-6` force family; `--http2`/`--http3-only`; `--proxy`; `--connect-timeout N`
- Interpretation: differentiate “Could not resolve host,” “Connection refused,” “Operation timed out,” TLS verify failures, and HTTP 3xx/4xx/5xx.

Packet capture and analysis
- tcpdump: capture/filters at edges.
  - Examples:
    - `tcpdump -ni any tcp port 443`
    - `tcpdump -ni eth0 host 8.8.8.8`
    - `tcpdump -ni any 'icmp or icmp6'`
- Wireshark: decode DNS, TCP handshakes, TLS ClientHello/SNI/ALPN, retransmissions, ICMP errors; payloads are opaque when encrypted.
- Caveats: capture requires privileges; encryption limits visibility; offloads can alter local view; protect sensitive data.

Performance probes
- ping/jitter to default gateway and to Internet targets.
- Throughput tests (note single-flow vs multi-flow differences).
- Look for bufferbloat symptoms (massive RTT spikes under upload/download).

## Interpreting common results and error classes

- Connection refused (TCP RST quickly): no process listening at the destination IP:port; or host firewall actively rejects; or listening only on loopback; or wrong port.
- Connection timed out (no response): silent drop by firewall/ACL, blackhole route, NAT or return-path problem, ISP filtering, or server down without sending RST.
- TLS errors: expired certificate, hostname mismatch, untrusted CA, missing intermediate, wrong SNI, protocol/cipher mismatch, client clock skew, interception/captive portal.
- DNS outcomes:
  - NXDOMAIN: name does not exist in this DNS view (split DNS? typo? negative cache?)
  - NOERROR with answer: OK; mind TTL and record type(s).
  - NOERROR empty for type: name exists for other types (e.g., MX exists, but no A).
  - SERVFAIL: resolver/authoritative/DNSSEC failure, upstream issue.
  - REFUSED: recursion disabled/policy.
  - Timeout: resolver unreachable, packet loss, firewall.
- Traceroute asterisks: often control-plane rate limiting; not proof of forwarding loss if later hops respond normally.
- Ping success does not prove TCP/UDP application connectivity; ping failure does not prove the host is down (ICMP may be blocked).

## NAT, firewalls, and security groups: what to verify

Collect the exact 5‑tuple and context
- Source IP/port, destination IP/port, protocol (TCP/UDP/ICMP), direction/ingress-egress interface or zone, state tracking behavior, expected return path.

Outbound flow on private IPv4 (PAT)
- Confirm default route and NAT rule exist; ensure NAT state table not exhausted.
- For failures: check if SYN leaves client but never reaches server (egress block/upstream filter). If SYN-ACK leaves server but never returns, fix return path/firewall.

Inbound via port forwarding
- Preconditions: actual public IP (not CGNAT/double NAT), correct external port, stable internal target IP, listening service, host firewall allows, ISP not blocking.
- Common breaks: CGNAT upstream, internal host IP changed, wrong target port, service binds to 127.0.0.1, asymmetric routing.

Cloud security controls
- Security groups (stateful) vs network ACLs (often stateless): check both.
- Load balancers: listener port/protocol, certificate attachment, target group port/protocol, health check path/host/header, backend SG allows LB sources.
- Route tables: Internet/Egress/NAT gateway association, subnet/AZ alignment, blackhole routes.

## VPNs and proxies: split-tunnel, DNS, and MTU traps

- Remote-access VPN
  - Split vs full tunnel: verify pushed routes and DNS suffixes; confirm no overlapping home/corp subnets (e.g., both using 192.168.1.0/24).
  - MTU/MSS clamping: tunnel overhead may blackhole large packets when ICMP PTB is filtered; symptoms include small pings OK, large HTTPS stalls.
- Forward proxy
  - Client must honor proxy settings (system vs app-specific). TLS interception requires enterprise CA trust; otherwise cert errors arise.
- Reverse proxy/load balancer/CDN
  - 502/503/504 usually indicate upstream health or route issues; validate health checks, SNI/Host headers, protocol (HTTP vs HTTPS) at each hop, and backend bindings.

## IPv6-specific diagnostics

- ICMPv6 is essential (Neighbor Discovery, Router Advertisements, Packet Too Big). Blanket ICMPv6 filtering breaks IPv6.
- Dual-stack asymmetry:
  - AAAA present but IPv6 route/firewall missing → IPv6 attempts stall; many clients use Happy Eyeballs to fall back to IPv4 with added delay.
  - Verify server listens on IPv6 and that IPv6 SG/firewall permits inbound/outbound.
- Tools:
  - `ping -6 host`, `traceroute -6 host`, `ip -6 route`, `ip -6 neigh`
  - Check RA/SLAAC/DHCPv6 behavior and on-link prefixes; watch for rogue RAs.

## MTU and fragmentation checks

Symptoms
- Small pings/DNS/handshakes succeed; large HTTP/TLS/file transfers stall or reset.

Tests
- Linux IPv4 DF test: `ping -M do -s 1472 host` (1472+28=1500). Reduce size until success.
- Windows IPv4 DF test: `ping -f -l 1472 host`
- IPv6 uses PMTUD only; ensure ICMPv6 Packet Too Big is not filtered.

Mitigations
- Set tunnel/interface MTU appropriately; enable MSS clamping on VPN/PPPoE; ensure ICMP(6) error delivery end-to-end.

## Wi‑Fi/link-layer diagnostics

- Validate signal (dBm) and SNR; test latency to default gateway over Wi‑Fi vs wired.
- Check band/channel utilization; try 5/6 GHz; adjust channel width; mitigate interference (Bluetooth, microwaves, neighboring APs).
- Mesh backhaul quality and AP placement matter; sticky roaming can degrade experience.

## Containers and Kubernetes: common diagnostic pivots

Containers
- Network namespaces isolate loopback. If an app binds to 127.0.0.1 inside the container, it is not reachable from host/network without additional plumbing.
- Publish ports explicitly (Docker `-p hostPort:containerPort`); `EXPOSE` is metadata in many runtimes.

Kubernetes
- Service/Ingress:
  - Confirm Service selector matches pod labels; `Endpoints`/`EndpointSlice` populated; correct `targetPort`; readiness passing.
  - Ingress requires a controller; ensure class matches; DNS points to the correct LB; TLS secret valid; host/path rules match requests.
- CNI/NetworkPolicy:
  - Verify pod IP allocation; inter-node pod networking; node routes/encapsulation/MTU correctness.
  - Enforced NetworkPolicy may block DNS or egress implicitly; remember namespace scoping.

## Performance and bufferbloat triage

- Separate bandwidth (capacity) from throughput (achieved rate) and latency/jitter.
- Under sustained upload/download, watch RTT to first hop; large increases suggest bufferbloat.
- Mitigate with smart queue management (SQM/fq_codel/pie), shaping just below link rate so the local router, not the ISP edge, queues packets.

## Scenario playbooks (fast guided diagnostics)

DNS works at home but fails on VPN
- Likely: split DNS/resolver override, missing DNS suffix, resolver ACL, overlapping subnets.
- Actions: inspect VPN-pushed DNS/route list; query internal names via corporate resolver; ensure route to internal IP; fix split DNS or add routes.

Ping works but HTTPS fails
- Likely: port 443 filtered, TLS validation, proxy policy.
- Actions: `curl -v https://host/`; verify certificate/hostname/SNI/clock; check egress filters; confirm no proxy requirement.

“Connection refused” to service
- Likely: not listening, wrong bind address/port, host firewall reject, container port not published.
- Actions: `ss -lntup` on server; bind to 0.0.0.0/::; open host firewall; verify LB targetPort.

“Connection timed out” to service
- Likely: path/filtering blackhole, NAT/return-path issue, wrong IP.
- Actions: TCP traceroute; verify SG/NACL/firewall on both sides; confirm server’s route back; capture SYN at server.

Website works over IPv4 not IPv6
- Likely: premature AAAA, IPv6 firewall/route missing, server not bound v6.
- Actions: `curl -4/-6`; check v6 listener, SG, ICMPv6, upstream v6 connectivity; remove AAAA until ready.

Wi‑Fi strong signal, poor performance
- Likely: interference/contention, bad backhaul, sticky roam.
- Actions: compare wired vs Wi‑Fi; test RTT/jitter to gateway; change channel/band/width; optimize AP placement/backhaul; update firmware.

Load balancer 502/503
- Likely: failing health checks, wrong backend port/protocol, SG block, missing Host header/SNI.
- Actions: verify listener, health check path/host/status, backend SG, HTTP vs HTTPS consistency, required headers.

VPN connects but internal app fails
- Likely: missing split route, DNS to internal FQDN missing, subnet overlap, MTU.
- Actions: confirm route to app IP; resolve via VPN DNS; adjust MTU/MSS; avoid overlapping CIDRs.

DHCP client gets wrong config or 169.254.x.x
- Likely: rogue DHCP, wrong VLAN/relay, exhausted scope.
- Actions: check DHCP server ID in lease, switch port VLAN, relay helpers, scope utilization; account for MAC randomization.

## OS/tooling notes and caveats

- Windows vs Linux vs macOS tooling differs; do not assume the same commands exist. Prefer `ip`/`ss` on modern Linux. Windows PowerShell `Test-NetConnection` is useful for port tests.
- Browsers may use DNS-over-HTTPS independent of OS. VPN clients often override DNS/routes.
- ICMPv6 must not be broadly blocked; IPv6 Neighbor Discovery and PMTUD depend on it.
- Encrypted traffic hides payloads; rely on metadata (handshakes, timing, error codes) and capture at the right edge.

## Minimal command cribsheet

Local config
- Windows: `ipconfig /all`
- Linux: `ip addr; ip route; ip -6 route; ip neigh`
- macOS: `ifconfig; netstat -rn; scutil --dns`

Reachability and path
- `ping host` / `ping -6 host`
- `traceroute host` / `traceroute -6 host` / `traceroute -T -p 443 host`
- Windows: `tracert host`

DNS
- `nslookup name`
- `dig name A+AAAA +ttl @resolver`

Ports and HTTP/TLS
- `ss -lntup` (Linux), `netstat -ano` (Windows)
- `curl -v https://host/` (use `-4`/`-6`, `--resolve`, `--proxy`, `--http3-only` as needed)

Capture
- `tcpdump -ni any tcp port 443`
- `tcpdump -ni any 'icmp or icmp6'`

MTU probes
- Linux: `ping -M do -s 1472 host`
- Windows: `ping -f -l 1472 host`

## Safety and privacy

- Packet captures and verbose logs may contain credentials, cookies, tokens, or PII. Limit scope/duration, sanitize outputs, and store securely.
- Coordinate with change control when altering firewall/NAT/route policies; document source/destination, ports, purpose, and rollback.

## Key Points

- Isolate by layer: confirm link, IP, DNS, transport, TLS, then application; compare known‑good vs failing paths while changing one variable at a time.
- Interpret tools cautiously: ping/traceroute do not guarantee application connectivity; refused vs timeout differentiate host/listener issues vs path/filtering.
- DNS and IPv6 are frequent culprits: test A vs AAAA, verify client resolver path, and keep ICMPv6 unblocked for ND/PMTUD.
- Policy devices dominate failures: verify firewall/security groups, NAT, routes, proxies, load balancer health checks, and return paths with precise 5‑tuple context.
- Performance issues often start at the edge: diagnose MTU blackholes and bufferbloat; use SQM/shaping and correct MTU/MSS for tunnels and overlays.