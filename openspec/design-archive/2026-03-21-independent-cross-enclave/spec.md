# Independent Cross-Enclave Features (Clipboard, Discovery, Jobs) — Design Spec (extracted)

> Auto-extracted from docs/independent-cross-enclave.md at decide-time.

## Decisions

### Dual-path design: LXMF always, DirectLink when available, RBAC per-feature (decided)

Each feature gets: (1) LXMF message type — always works cross-enclave, fire-and-forget; (2) DirectLink endpoint — confirmed, real-time, works with direct or TURN-relayed link; (3) auto-detect transport preference. LXMF path can ship before TURN exists; DirectLink path lights up automatically when TURN lands. Feature-specific RBAC capabilities: clipboard.send/receive (PEER), discovery.peers (PEER), jobs.submit/cancel (OPERATOR), jobs.status (MONITOR). Each capability gates both transports — RBAC is transport-independent.

## Research Summary

### Dual-path architecture: LXMF fallback + DirectLink preferred

Every LXMF-only feature gains significant quality improvements with TURN: delivery confirmation (vs fire-and-forget), real-time freshness (vs stale-on-arrival), progress streaming (vs blind-until-complete), link-speed latency (vs store-and-forward hops). The right pattern is dual-path: LXMF message type for reliability (always works cross-enclave), DirectLink endpoint for quality (works when direct or relayed link exists), auto-detection preferring DirectLink with LXMF fallback. This means TURN …
