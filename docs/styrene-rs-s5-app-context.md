---
id: styrene-rs-s5-app-context
title: "S5: AppContext — decompose RpcDaemon god-struct into service registry"
status: exploring
parent: styrene-rs-architecture
dependencies: [styrene-rs-s1-arc-runtime, styrene-rs-s2-mesh-transport-trait, styrene-rs-s4-module-structure]
open_questions: []
---

# S5: AppContext — decompose RpcDaemon god-struct into service registry

## Overview

RpcDaemon is a god-struct with 40+ Mutex fields. styrene-ipc already defines the Daemon composite trait (DaemonMessaging, DaemonIdentity, DaemonStatus, DaemonFleet, DaemonEvents, DaemonTunnel) but RpcDaemon does not implement it yet. AppContext owns all services (transport, messages, conversations, node_store, auto_reply, protocols, config, identity). RpcDaemon becomes a thin RPC dispatch layer that delegates to AppContext services. Services receive Arc&lt;AppContext&gt; and subscribe to transport events via broadcast channels. Depends on S1 (Arc), S2 (MeshTransport trait), S4 (modules).

## Research

### Assessment: S5 is the real architectural pivot and must avoid becoming a second god-object

Deep assessment shows S5 is not a routine refactor; it is the architectural hinge for the Rust daemon. Its benefits are clear — RpcDaemon becomes a thin IPC/RPC facade and service logic moves into coherent components — but the main risk is simply renaming the current god-struct into an AppContext with the same uncontrolled reachability. AppContext should own wiring, shared capabilities, and service registration, while individual service modules own behavior. The decomposition should be planned around bounded service domains (messaging, fleet/node store, identity/config, protocols, transport integration, tunnel/events) and staged adoption of the styrene-ipc Daemon trait, rather than a single giant move.

## Decisions

### Decision: Treat AppContext as composition root and service registry, not as a renamed god-struct

**Status:** decided
**Rationale:** S5 only succeeds if AppContext centralizes wiring without re-centralizing all mutable behavior. The correct target is a composition root that owns shared dependencies and service registration, while behavior lives behind focused service interfaces. RpcDaemon then becomes a thin dispatch facade implementing the styrene-ipc Daemon composite trait by delegating to services. This decomposition should proceed in slices by service domain, so compilation and tests remain green through the migration instead of requiring a flag day rewrite.

### Decision: AppContext owns composition and shared handles; daemon behavior is split into bounded domain services

**Status:** decided
**Rationale:** The Rust daemon should be decomposed into bounded services rather than a single central mutable object. AppContext should own only composition-root concerns: shared dependency construction, lifecycle wiring, service registration, global config/identity handles, and cross-service capability discovery. Business behavior moves into domain services. The initial service map should be: MessagingService (message send/receive, conversations), IdentityService (identity access and signing coordination), FleetService (status, node store, fleet queries), ProtocolService (protocol dispatch/routing), TransportService adapter (bridge from MeshTransport events into service-facing streams), EventService (subscriptions and fan-out for daemon consumers), TunnelService, and ConfigService/runtime settings. RpcDaemon becomes a thin facade that delegates trait methods into these services.

### Decision: Migrate RpcDaemon to AppContext in bounded slices aligned to daemon trait groupings

**Status:** decided
**Rationale:** The daemon refactor should avoid a flag day rewrite. Migration proceeds in bounded slices that preserve compilation and testability throughout. Recommended order: (1) Identity + Config + Status/Fleet read paths, because they are lower-risk and establish delegation patterns; (2) Messaging + Conversations + NodeStore integration; (3) Protocol dispatch and inbound handling through transport-facing adapters; (4) Events and Tunnel services; (5) final RpcDaemon field collapse and Daemon composite trait conformance cleanup. At each stage, RpcDaemon remains the facade while implementation responsibility moves behind service interfaces. Old fields may temporarily coexist, but each slice should shrink direct field access and add tests for the delegated behavior before proceeding.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- AppContext must not directly absorb business logic that belongs in domain services.
- Migration should proceed in bounded slices so RpcDaemon delegation and tests can be validated incrementally.
- Service boundaries should align with styrene-ipc trait groupings where practical (messaging, identity, status/fleet, events, tunnel).
- S5 implementation planning should identify which shared dependencies remain in AppContext versus which are owned privately by each service.
- AppContext should only own composition-root concerns: wiring, shared handles, lifecycle orchestration, and service lookup.
- Messaging, fleet/status, identity, protocol routing, events, tunnel, and config/runtime behavior should live in separate services.
- Transport integration should be represented as an adapter/service boundary, not as direct ad hoc field access from every consumer.
- RpcDaemon methods should delegate into services rather than reaching across AppContext internals.
- S5 migration must proceed slice-by-slice, not as a one-shot rewrite.
- Each migration slice should leave RpcDaemon compiling and preserve existing behavior behind delegation.
- Lower-risk read-oriented domains (identity, config, status/fleet) should move before high-churn inbound/protocol logic.
- Each slice should add or adapt tests that prove delegation behavior before collapsing old fields.
