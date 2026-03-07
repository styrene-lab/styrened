---
id: turn-relay
title: TURN-Style Link Relay via Hub
status: decided
parent: cross-enclave-features
open_questions:
  - What is the relay coordination protocol? How does Node A tell Hub to relay to Node B, and how does Hub authenticate/authorize the relay?
---

# TURN-Style Link Relay via Hub

## Overview

> Parent: [Cross-Enclave Features for Hub-Only Peers](CROSS-ENCLAVE-FEATURES.md)
> Spawned from: "What is the relay coordination protocol? How does Node A tell Hub to relay to Node B, and how does Hub authenticate/authorize the relay?"

*To be explored.*

## Research

### RNS.Channel is single-packet — not suitable for bulk relay

RNS.Channel provides reliable bidirectional message delivery but is size-constrained to a single packet (~383 bytes on a standard Link). It's designed for control/signaling, not bulk data forwarding. DirectLink already uses link.request() for endpoints and RNS.Resource for file transfer. Relay data path should use: Channel for signaling/control (relay setup, teardown, keepalive), link.request() forwarding for DirectLink endpoints, and RNS.Resource proxying for bulk transfers.

## Decisions

### Decision: Link lifecycle: disconnect propagation with permanent-link exception

**Status:** decided
**Rationale:** Default: when either side disconnects, hub tears down both halves and emits RelayIdleTimeout or RelayPeerDisconnected. Permanent links: hub keeps the surviving half alive and attempts reconnect to the dropped peer for a configurable grace period before teardown. Same-enclave permanent links are admin self-service; cross-enclave permanent links require mutual consent (relay.request_permanent + relay.accept_permanent).

### Decision: Relay data path: channel-based multiplexed forwarding

**Status:** exploring
**Rationale:** Channels allow multiplexing multiple logical streams over a single RNS.Link, which aligns with DirectLink's existing endpoint model (/status, /ping, /speedtest, /relay). Raw request/response would require a new link per operation. Channels also enable future features like port forwarding. Needs verification that RNS.Channel supports the bidirectional byte forwarding pattern needed for relay.

### Decision: Hybrid data path: Channel for control, request forwarding for data

**Status:** decided
**Rationale:** RNS.Channel is single-packet (~383B) — unsuitable for bulk relay. Hybrid approach: Channel for relay signaling (setup, teardown, keepalive, error notification), link.request() forwarding for DirectLink endpoint proxying (/status, /ping, /meta, /info, /speedtest), RNS.Resource proxying for bulk transfer (file transfer). This matches existing DirectLink patterns — no new transport abstractions needed.

## Open Questions

- What is the relay coordination protocol? How does Node A tell Hub to relay to Node B, and how does Hub authenticate/authorize the relay?

## Implementation Notes

### File Scope

- `src/styrened/services/relay.py` (new) — RelayService — hub-side relay session manager. Tracks active sessions, enforces limits, bridges links.
- `src/styrened/models/relay.py` (new) — RelaySession, RelayConfig, RelayError hierarchy (12 error types), RelayRequest/Response messages
- `src/styrened/models/rbac.py` (modified) — Add relay.* capabilities: request, request_permanent, list, teardown, accept, accept_permanent, reject, admin, prioritize, bridge
- `src/styrened/services/direct_link.py` (modified) — Add /relay endpoint handler, RELAYED link type, relay-aware link tracking
- `src/styrened/daemon.py` (modified) — Wire RelayService into daemon lifecycle, relay config parsing
- `src/styrened/models/config.py` (modified) — Add RelayConfig to CoreConfig (enabled, max_sessions, max_per_identity, etc.)
- `src/styrened/services/config.py` (modified) — Parse relay: section from YAML config
- `tests/unit/test_relay.py` (new) — RelayService unit tests — session lifecycle, limit enforcement
- `tests/unit/test_relay_errors.py` (new) — 12 error path tests — one per RelayError subclass
- `tests/unit/test_relay_rbac.py` (new) — RBAC gating tests for all relay.* capabilities

### Constraints

- RNS.Channel is single-packet (~383B) — use for signaling only, not bulk forwarding
- Relay must not bypass target peer RBAC — relayed links carry source identity hash
- Permanent links require triple consent: requester cap + hub config + target cap
- 12 distinct error types, each with dedicated test
- Hub relay is opt-in (relay.enabled defaults to false)
