# Security

> OCC is in alpha. The current broker prioritises clarity and federation feasibility over hardening. Do not run a production broker without the work tracked in this document.

## Threat model

OCC is built on three properties:

- **Pack content is public.** Expert packs are community-approved knowledge meant to be world-readable. The broker serves them unauthenticated by design via `/tree`, `/packs/*`, `/search`.
- **User queries are private to the Node.** The broker sees keyword sub-queries during retrieval, never the user's original question. Peer Critic exchanges are end-to-end encrypted — the broker routes ciphertext only.
- **Peers are not yet authenticated.** Today's broker accepts any WebSocket registration with self-declared tier and VRAM. PKI-based registration signing is tracked in the Sprint 4 hardening roadmap.

## Known limitations (alpha)

These gaps are visible from `node/server/broker.py` and trivially discoverable by probing a live broker. Documenting them is part of the project's commitment to transparency.

| Gap | Impact | Fix tracked in |
|-----|--------|----------------|
| Unsigned WebSocket registration | A malicious node can register with inflated VRAM and receive Critic queries from real nodes | Sprint 4 — PKI signing |
| No rate limit on `/search` | DoS vector against the broker | Sprint 4 — hardening |
| Unbounded in-memory `nodes` and `pending_queries` dicts | Memory exhaustion vector | Sprint 4 — hardening |
| `/admin/reindex` token is a single static value | No rotation; a compromise persists indefinitely | Sprint 4 — token rotation |

## What is intentionally public

- The broker source code (`node/server/broker.py`) — required for the federation roadmap (anyone can run their own broker).
- Pack content and the search index — these are the commons.
- Tier and VRAM information of registered nodes (`/nodes`) — required for the peer selection model. The next iteration ties this to a PKI identity.

## What is NOT in this repository

- Production server credentials (SSH keys, deployment tokens)
- Production server IP and hostname
- Real expert pack content (the repo ships the directory shell only — packs are deployed separately)
- Per-user configuration, chat history, and local working drafts

These are kept out of source control via `.gitignore`.

## Reporting a vulnerability

Please email **vickywensz@gmail.com** with the subject line `[OCC SECURITY]`. Do not open a public issue for an unpatched vulnerability. Acknowledgement within 7 days.
