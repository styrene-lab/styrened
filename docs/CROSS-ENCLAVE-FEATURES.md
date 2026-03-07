---
id: cross-enclave-features
title: Cross-Enclave Features for Hub-Only Peers
status: decided
tags: [networking, directlink, hub, relay]
open_questions: []
---

# Cross-Enclave Features for Hub-Only Peers

## Overview

Enable DirectLink-dependent features (speedtest, real-time status, file transfer) between styrene nodes that share no direct RNS path — only a common hub. Six candidate features assessed; TURN-style link relay recommended first as it unlocks all others.

## Research

### Current Cross-Enclave Capabilities

Chat (LXMF store-and-forward) ✅, RPC (LXMF envelope) ✅, WireGuard VPN (LXMF key exchange + internet data) ✅. DirectLink ❌ (requires RNS path), File Transfer ❌ (requires RNS.Link), Speedtest ❌ (DirectLink-only), Real-time status ❌ (DirectLink-only).

## Decisions

### Decision: TURN relay first, then independent quick-wins

**Status:** exploring
**Rationale:** Building TURN first converts hub-only peers into effectively direct-linked peers, meaning all existing DirectLink features work without LXMF fallback paths. Clipboard sharing and mutual discovery are independent quick wins (single LXMF messages) that can proceed in parallel.

### Decision: Relay is explicit — peers know they are relayed

**Status:** decided
**Rationale:** Explicit is truthier. Peers adapt behavior (speedtest interpretation, chunk sizing, TUI display). Link type enum DIRECT/RELAYED. No additional complexity — relay negotiation inherently reveals the relay.

### Decision: Resource limits with permanent-link opt-in

**Status:** decided
**Rationale:** Default: per-identity concurrent relay cap (2), global relay cap (16), per-session byte ceiling (50 MiB), idle timeout (15 min). Permanent links bypass idle timeout and byte cap, requiring either: (a) same-enclave admin self-service, or (b) cross-enclave mutual consent — both peers explicitly agree to permanent status. Hub config section relay: with operator-tunable limits. No amplification risk — relay is 1:1 bidirectional forwarding. Full test suite for all limit-exceeded error paths (max sessions, max bytes, idle teardown, unauthorized permanent request).

### Decision: Full relay capability surface — 3-tier gating with 12 error paths

**Status:** decided
**Rationale:** Three independent gates: requesting peer RBAC, hub config, target peer RBAC. Client caps: relay.request (PEER), relay.request_permanent (OPERATOR), relay.list (PEER), relay.teardown (PEER). Target caps: relay.accept (PEER), relay.accept_permanent (OPERATOR), relay.reject (PEER — granular block without BLOCKED role). Admin caps: relay.admin (ADMIN — force-teardown, view all), relay.prioritize (OPERATOR — survive LRU eviction), relay.bridge (OPERATOR — multi-hop relay placeholder). Hub config: relay.enabled, max_sessions, max_per_identity, max_bytes_per_session, idle_timeout, allow_permanent, allowed_identities. Permanent links require triple consent: requester cap + hub config + target cap. 12 distinct error types each with dedicated test: RelayDisabled, RelayMaxSessions, RelayMaxPerIdentity, RelayByteLimitExceeded, RelayIdleTimeout, RelayUnauthorized, RelayPermanentDenied, RelayTargetRejected, RelayTargetOffline, RelayPermanentConsentDenied, RelayEvicted, RelayBridgeDenied.

### Decision: Sequencing: TURN is priority, LXMF paths ship in parallel, DirectLink paths light up post-TURN

**Status:** decided
**Rationale:** TURN is the force multiplier — it upgrades every current and future feature from fire-and-forget to confirmed+real-time. But LXMF paths for clipboard/discovery/jobs have zero TURN dependency and can ship in parallel. Each feature is dual-path: LXMF message type (ships now, works everywhere) + DirectLink endpoint (ships with or after TURN, activates automatically when link exists). This means parallel workstreams with no blocking dependency, and TURN retroactively improves features that shipped before it.

## Open Questions

*No open questions.*
