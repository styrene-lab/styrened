---
id: independent-cross-enclave
title: Independent Cross-Enclave Features (Clipboard, Discovery, Jobs)
status: decided
parent: cross-enclave-features
open_questions: []
---

# Independent Cross-Enclave Features (Clipboard, Discovery, Jobs)

## Overview

> Parent: [Cross-Enclave Features for Hub-Only Peers](CROSS-ENCLAVE-FEATURES.md)
> Spawned from: "For non-relay features (clipboard, discovery, async jobs) — should these be implemented independently of TURN, or only after TURN exists?"

*To be explored.*

## Research

### Dual-path architecture: LXMF fallback + DirectLink preferred

Every LXMF-only feature gains significant quality improvements with TURN: delivery confirmation (vs fire-and-forget), real-time freshness (vs stale-on-arrival), progress streaming (vs blind-until-complete), link-speed latency (vs store-and-forward hops). The right pattern is dual-path: LXMF message type for reliability (always works cross-enclave), DirectLink endpoint for quality (works when direct or relayed link exists), auto-detection preferring DirectLink with LXMF fallback. This means TURN doesn't just unlock existing DirectLink features — it upgrades every future LXMF feature from fire-and-forget to confirmed+real-time automatically.

## Decisions

### Decision: Dual-path design: LXMF always, DirectLink when available, RBAC per-feature

**Status:** decided
**Rationale:** Each feature gets: (1) LXMF message type — always works cross-enclave, fire-and-forget; (2) DirectLink endpoint — confirmed, real-time, works with direct or TURN-relayed link; (3) auto-detect transport preference. LXMF path can ship before TURN exists; DirectLink path lights up automatically when TURN lands. Feature-specific RBAC capabilities: clipboard.send/receive (PEER), discovery.peers (PEER), jobs.submit/cancel (OPERATOR), jobs.status (MONITOR). Each capability gates both transports — RBAC is transport-independent.

## Open Questions

*No open questions.*
