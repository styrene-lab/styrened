---
id: styrene-rs-s2-mesh-transport-trait
title: "S2: MeshTransport trait — testable, swappable transport backend"
status: decided
parent: styrene-rs-architecture
open_questions: []
---

# S2: MeshTransport trait — testable, swappable transport backend

## Overview

Transport is a 500+ LOC concrete struct with direct tokio::spawn and hardcoded TCP/UDP. Extract MeshTransport trait: send_packet, send_announce, request_path, link, subscribe_announces, subscribe_inbound, destination_identity. TokioTransport implements the trait. MockTransport enables unit tests without real network. WasmTransport (future) implements over WebSocket for browser targets. Required for AppContext service registry (S5) and testability of all service layer code.

## Research

### Assessment: the trait is valuable but risks becoming a leaky mirror of the current transport implementation

Deep assessment of S2 suggests the core hazard is overfitting the trait to today's TokioTransport internals. The proposed API mixes command operations, event subscription, path/link management, and identity exposure. If extracted mechanically from the concrete struct, MeshTransport may become too broad, async-runtime-coupled, or difficult to mock. The trait should be shaped by service-consumer needs (daemon services, tests, future Wasm/WebSocket transport), not by preserving every concrete method. Spawn ownership, channel lifetimes, announce/inbound fan-out semantics, and shutdown behavior need to be explicit contract points, or the abstraction will only move complexity around.

## Decisions

### Decision: Define MeshTransport from consumer contracts, not by mechanically mirroring TokioTransport

**Status:** decided
**Rationale:** The transport abstraction is only worthwhile if it reduces coupling for service code and tests. Therefore the trait should be derived from the minimum stable contract required by consumers: packet send, announce send, path request, link access/establishment as needed, inbound event subscription, announce subscription, destination identity exposure, and explicit lifecycle/shutdown semantics if services depend on them. Methods that exist only because TokioTransport currently owns spawning or internal coordination should stay out of the public trait until a consumer requires them.

### Decision: MeshTransport exposes command operations plus broadcast-style inbound and announce subscriptions with explicit lifecycle semantics

**Status:** decided
**Rationale:** Service consumers need a small stable contract, not TokioTransport internals. MeshTransport should provide command-style operations for send/request/link behavior, plus subscription accessors for inbound packets and announce events using broadcast/fan-out semantics suitable for multiple independent consumers. The transport layer owns its background tasks; services do not spawn or manage transport internals directly. The contract must also define lifecycle semantics: initialization/start responsibility, shutdown behavior, and what subscribers observe when the transport stops or faults. This keeps service code runtime-agnostic and makes MockTransport capable of deterministic event injection and failure simulation.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- Trait shape must be justified by service/test consumers, not by one-for-one extraction from TokioTransport.
- MockTransport must support deterministic testing of inbound packets, announce streams, and failure/shutdown conditions.
- Ownership of background tasks, event channels, and shutdown semantics must be explicit in the contract before implementation begins.
- Future Wasm/WebSocket transport should remain plausible without forcing Tokio-specific APIs into the trait surface.
- MeshTransport should expose only consumer-needed command operations plus inbound/announce subscription APIs.
- Inbound packets and announces should support multi-consumer fan-out semantics rather than single-consumer ownership.
- Transport implementation owns background task spawning and internal coordination.
- The contract must define startup, shutdown, and fault semantics visible to subscribers and tests.
- MockTransport must support deterministic injection of inbound traffic, announce events, and shutdown/failure conditions.
