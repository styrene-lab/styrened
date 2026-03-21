---
id: styrene-rs-daemon-port-execution-plan
title: styrene-rs Daemon Port Execution Plan
status: implementing
parent: styrene-rs-architecture
tags: [rust, daemon, execution-plan, migration, cleave]
open_questions: []
branches: ["feature/styrene-rs-daemon-port-execution-plan"]
openspec_change: styrene-rs-daemon-port-execution-plan
issue_type: epic
priority: 1
---

# styrene-rs Daemon Port Execution Plan

## Overview

Detailed execution plan for the next Rust daemon port wave. Sequences S2 (MeshTransport trait), narrowed S4 (module hygiene), and S5 (AppContext decomposition) into implementation slices suitable for OpenSpec planning and cleave parallelization.

## Research

### Execution sequencing constraints for the next daemon port wave

The daemon port wave is shaped by three clarified truths: (1) S4 is no longer a full standalone refactor and should be restricted to pre-S5 low-risk module hygiene; (2) S2 must be designed from consumer-facing contract needs rather than extracted mechanically from TokioTransport; (3) S5 is the architectural pivot and should decompose RpcDaemon into bounded services without recreating a god-object. Therefore the port should be staged as: preparation and interface definition first, then bounded service migration slices, then follow-on IPC/client roles.

### Assessment of existing styrened Python daemon: responsibilities exceed the current Rust execution-plan surface

Deep review of the Python daemon shows that `StyreneDaemon` is not only a transport/RPC wrapper. It is an orchestration hub for many concerns: core lifecycle and RNS/LXMF startup, operator destination caching and reconnection handling, RPC server injection, device discovery and path snapshots, conversation and contacts persistence, read receipts, attachment extraction/storage, notification/event bridging, page browser/page server, direct-link and datalink handlers, PQC session initiation, overlay adapters (I2P/Yggdrasil), mesh VPN/relay, binary provisioning, optional HTTP API/SSE, and IPC control server startup. Much of this behavior is still coordinated directly out of `daemon.py` through cached singleton-like service references and ordered startup side effects. Therefore the Rust daemon port must treat Wave 0 inventory as a full behavior census, not merely a refactor of transport + RPC internals.

### Assessment of hidden coupling in Python daemon: startup order, singleton services, and cross-service injections are migration risks

The Python code reveals several non-obvious coupling patterns that the Rust port must not leave behind accidentally: (1) startup order is semantically significant (RBAC must be injected into LXMF before message processing; conversation service must initialize after LXMF and before RPC inbox queries; notification service and control server order matters; adapter startup precedes announce/meta surfaces); (2) many services are global singletons (`get_lxmf_service`, `get_rns_service`, `get_node_store`) with daemon-local cached references layered on top; (3) reconnection flows refresh destinations and tell page/direct-link services to invalidate state; (4) the daemon bridges legacy notification flow into a newer EventBus; (5) RPC and LXMF both perform security-sensitive checks, but authorization keys differ between destination and identity hashes and rely on NodeStore lookups. These are architecture-level seams that require explicit treatment in the Rust inventory and service-boundary map.

### Assessment of existing styrened TUI: ~35K LOC across 116 files, IPC-only architecture already established

Deep review of the Python TUI shows it is already a pure IPC client — all mesh services run inside the daemon, and the TUI communicates exclusively through IPCBridge (~60 async methods). This is architecturally favorable for the Rust port: the Ratatui TUI does not need to own any mesh/RNS/LXMF logic; it only needs to implement the same IPC client contract. The TUI has 27 screens (12,345 LOC), 34 widgets (10,505 LOC), 17 services (4,861 LOC), and extensive theming/forge/model support. The largest surface areas are the ExplorationScreen (1,418 LOC), ChatWidget (1,719 LOC), SettingsScreen (1,985 LOC), and PageBrowserWidget (975 LOC). The Forge provisioning subsystem (~1,882 LOC) is self-contained and can be deferred. The IPC bridge method set defines the complete daemon API contract that the Rust daemon's Unix socket server must implement.

### Package A complete: ownership matrix and file-scope map produced from both inventories + Rust codebase analysis

Analyzed the full styrene-rs crate structure (11 crates, 42K LOC) and the RpcDaemon god struct (50+ Mutex fields across 23 include! files, 7,467 LOC). Produced ownership-matrix.md defining: 11 target services (IdentityService, ConfigService, StatusService, FleetService, MessagingService, DiscoveryService, ProtocolService, EventService, TunnelService, TransportAdapter, AuthService), AppContext as composition root, DaemonFacade as the thin Daemon trait implementor replacing RpcDaemon. File-scope map covers ~20 new files, ~15 modified, ~8 test files. MeshTransport trait defined from consumer contracts (messaging needs send+subscribe_inbound, discovery needs subscribe_announces, fleet needs send+request). Startup order and reconnection invalidation maps validated and assigned to Rust service owners. All BRIDGE items documented with IPC contract requirements. All DEFER items mapped to existing or needed design-tree nodes.

## Decisions

### Decision: Organize the daemon port into four waves: prepare, abstract transport, decompose daemon, then unlock dependents

**Status:** decided
**Rationale:** Wave 0 (prepare) performs narrowed S4 low-risk cleanup, inventories RpcDaemon responsibilities, and identifies target service boundaries and file scope. Wave 1 (abstract transport) lands S2 MeshTransport with deterministic mocks and explicit lifecycle semantics. Wave 2 (decompose daemon) executes S5 in bounded slices: identity/config/status-fleet, messaging/conversations/node-store, protocol/inbound handling, events/tunnel, then RpcDaemon field collapse. Wave 3 (unlock dependents) starts Unix socket IPC and PropagationClient on top of the new daemon/service interfaces. This sequencing minimizes churn, preserves testability, and creates natural cleave boundaries.

### Decision: Cleave boundaries follow change coupling, not node boundaries

**Status:** decided
**Rationale:** The existing design nodes are architectural units, but the most efficient implementation split is by coupling and test surface. A good cleave plan should keep each child either interface-first or service-slice-first, with narrow file overlap and explicit dependency order. For example, transport trait extraction and MockTransport tests can be isolated from later AppContext delegation slices, while pre-S5 daemon module hygiene remains separate from post-S5 daemon breakup. This reduces merge conflicts and shortens feedback loops.

### Decision: Initial implementation work packages: inventory, transport contract, transport mocks/tests, AppContext foundation, service slices, facade collapse, dependent unlocks

**Status:** decided
**Rationale:** To maximize execution clarity and parallelism, the daemon port should be broken into small work packages with narrow ownership: (A) RpcDaemon inventory + service boundary/file-scope map, (B) MeshTransport contract and TokioTransport adaptation, (C) MockTransport and transport contract tests, (D) AppContext foundation and service registration skeleton, (E) service slice 1 — identity/config/status-fleet delegation, (F) service slice 2 — messaging/conversations/node-store delegation, (G) service slice 3 — protocol/inbound handling delegation, (H) service slice 4 — events/tunnel delegation, (I) RpcDaemon field collapse + Daemon trait conformance cleanup, (J) dependent unlock prep for Unix socket IPC and PropagationClient. These packages create a natural serial/parallel graph for cleave.

### Decision: Recommended dependency graph for implementation packages

**Status:** decided
**Rationale:** Package A precedes everything because it defines file scope and ownership. Package B depends on A. Package C depends on B's contract shape but may proceed in parallel with B's concrete TokioTransport adaptation once semantics are fixed. Package D depends on A and may begin once the service map is stable. Packages E-H each depend on D; E should start first to establish the delegation pattern, F/G/H can then proceed in cautious sequence or limited parallelism depending on file overlap. Package I depends on E-H being green. Package J depends on I. This graph supports fast iteration while respecting the architectural risks identified in assessment.

### Decision: Use one OpenSpec change for the daemon port wave, but multiple cleave children under a single reviewed file-scope map

**Status:** decided
**Rationale:** These packages are part of one coherent architectural migration and should live under one reviewed OpenSpec change so specs, design, and verification remain unified. However implementation should be split into multiple cleave children after the file-scope map is established. This avoids premature fragmentation at the spec layer while still enabling parallel execution where safe. The first child should produce or validate the file-scope/ownership matrix; later children should cite that matrix to minimize cross-branch conflict.

### Decision: Wave 0 inventory must explicitly classify Python daemon responsibilities into port-now, preserve-via-IPC, and defer categories

**Status:** decided
**Rationale:** A naive daemon port risks silently dropping behavior that is currently embedded in Python orchestration. Before implementation, Package A must classify every observed Python daemon responsibility into one of three buckets: (1) port in the initial Rust daemon wave because it is core to the daemon/runtime contract (transport, RPC facade, service registry, eventing, status/fleet, messaging/conversation orchestration); (2) preserve via existing Python-side IPC/integration temporarily because the Rust wave is not yet taking ownership (for example some web/API/TUI-facing adapters); or (3) explicitly defer as follow-on work with documented compatibility expectations (overlay management, page services, VPN/relay, provisioning, etc., if not included in the first slice). The port is incomplete unless every current Python-owned daemon behavior has a stated migration disposition.

### Decision: TUI inventory produced alongside daemon inventory to enable working inward from both ends

**Status:** decided
**Rationale:** The daemon inventory captures what the backend must provide; the TUI inventory captures what the frontend consumes. Together they define the IPC contract surface from both sides. The TUI is already a pure IPC client, which means the Rust port boundary is clean: the daemon owns all mesh/RNS/LXMF services, and the TUI owns all rendering/input/navigation. The IPCBridge method set (~60 methods) is the shared contract. Ratatui TUI implementation should follow daemon port so it can target stable Rust daemon IPC interfaces rather than co-evolving against a moving internal structure.

### Decision: MeshTransport trait stays in styrened-rs (daemon-internal, not promoted to styrene-ipc)

**Status:** decided
**Rationale:** All MeshTransport consumers are services inside styrened-rs. Frontend crates (styrene-tui, styrene-dx) depend on styrene-rns for data types only — comment: 'no transport'. styrene-ipc defines the frontend↔daemon boundary (Daemon trait), not daemon-internal abstractions. Promoting MeshTransport would pollute the IPC crate with implementation concerns no frontend needs. The trait is not cross-crate; it belongs in the app crate.

### Decision: NodeStore is a shared storage module (storage/node_store.rs), not folded into DiscoveryService

**Status:** decided
**Rationale:** NodeStore is consumed by multiple services: DiscoveryService writes, MessagingService reads display names, IdentityService reads destination hashes, FleetService reads capabilities. Folding it into DiscoveryService would create a dependency from all readers to the discovery domain. As a storage module (parallel to storage/messages.rs), it serves as the shared identity resolution authority with clear write/read ownership.

### Decision: DaemonFacade kept as separate struct (not implementing Daemon on AppContext directly)

**Status:** decided
**Rationale:** Chesterton's fence analysis reveals three reasons: (1) separates composition concern (AppContext wires services) from consumption concern (DaemonFacade dispatches IPC); (2) prevents circular calls — services hold Arc<AppContext>, IPC holds Arc<dyn Daemon>, preventing service→facade→service recursion; (3) natural auth enforcement point — DaemonFacade calls AuthService.check() before delegating to services, keeping services clean. StubDaemon in styrene-ipc remains available for frontend testing without daemon infrastructure.

### Decision: AuthService owns policy data and check methods; DaemonFacade owns enforcement

**Status:** decided
**Rationale:** Mirrors the Python daemon pattern where RPCServer checks capabilities before dispatching. AuthService owns RBAC policy config, roster, and blocklist data, exposing check(identity, capability) and is_blocked(identity). DaemonFacade calls auth.check() before delegating to services. Services trust their caller. Special case: MessagingService queries is_blocked() for inbound message filtering — this is a data query, not an enforcement gate.

### Decision: AutoReplyService is a standalone service, not part of ConfigService

**Status:** decided
**Rationale:** Auto-reply has behavior beyond config: per-peer cooldown tracking, reply composition, and sends through MessagingService. It reads config from ConfigService but acts through the messaging pipeline. Folding it into config would force config to depend on messaging. As a standalone service it has clean dependencies: reads ConfigService, sends via MessagingService.

### Decision: MeshTransport is a thin trait over rns_core::Transport, not a delivery pipeline

**Status:** decided
**Rationale:** Option C (split levels): MeshTransport wraps raw transport operations (send_raw, send_via_link, request_path, resolve_identity, announce, subscribe_inbound, subscribe_announces, lifecycle). The delivery pipeline (path request → identity poll → link attempt → opportunistic fallback → receipt tracking) lives in MessagingService as service-level orchestration. Rust's type system makes the wiring provable at compile time — if MessagingService needs Arc<dyn MeshTransport> + Arc<IdentityService>, AppContext won't compile without them. No need for a thick abstraction to protect against misassembly. All referenced rns_core types (AddressHash, DestinationDesc, Identity, ReceivedData, AnnounceEvent, SendPacketOutcome, LinkSendResult, PacketDataBuffer) have public fields and/or public constructors — fully constructable in MockTransport tests.

### Decision: NullTransport for standalone/test mode — null object pattern instead of Option wrapping

**Status:** decided
**Rationale:** The daemon can run without transport (test mode, standalone). Rather than Option<Arc<dyn MeshTransport>> scattered through services, a NullTransport implements MeshTransport and returns TransportError::Unavailable on every send, empty receivers on subscribe, false on is_connected. Services always hold Arc<dyn MeshTransport> — no Option-checking in business logic. AppContext construction picks TokioTransportAdapter or NullTransport at startup. NullTransport is trivial to implement and eliminates a class of None-handling bugs.

### Decision: Transport lifecycle events via subscribe_lifecycle on the trait

**Status:** decided
**Rationale:** MeshTransport exposes fn subscribe_lifecycle() -> broadcast::Receiver<TransportLifecycleEvent> where the enum covers Connected, Disconnected, Reconnected variants. This is genuinely a transport concern — the trait should expose it rather than relying on AppContext polling is_connected() for state transitions. Services that care about reconnection (IdentityService, DiscoveryService) subscribe directly. The reconnection invalidation map (clear cached destinations, re-announce, re-enter discovery) is triggered by services reacting to Reconnected events they subscribed to.

### Decision: Receipt tracking owned by MessagingService, fanout by EventService

**Status:** decided
**Rationale:** MessagingService owns the receipt correlation map (packet_hash/resource_hash → message_id) because it initiated the send and needs to update delivery status. When receipt callbacks arrive from transport, MessagingService resolves the message_id and pushes delivery status events through EventService for IPC fanout. This splits the concern cleanly: MessagingService tracks causality (which send produced which receipt), EventService handles distribution (notify TUI, SSE, activity ring). The current TransportBridge receipt_map + receipt_tx pattern decomposes naturally into this two-service model.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `styrene-rs/crates/**/transport*.rs` (modified) — Transport abstraction, adapters, and mocks for S2
- `styrene-rs/crates/**/rpc/daemon*.rs` (modified) — RpcDaemon facade reduction, delegated service calls, and eventual field collapse
- `styrene-rs/crates/**/rpc/mod.rs` (modified) — Pre-S5 low-risk module hygiene and non-daemon structural cleanup
- `styrene-rs/crates/**/services/*.rs` (modified) — New or expanded daemon domain services introduced by S5 slices
- `styrene-rs/crates/**/ipc*.rs` (modified) — Daemon trait integration and follow-on Unix socket IPC consumers
- `styrene-rs/crates/**/tests/**/*.rs` (modified) — Unit/integration coverage for transport abstraction and daemon slice migration
- `openspec/changes/styrene-rs-daemon-port-execution-plan/inventory.md` (new) — Authoritative Python daemon behavior census with PORT/BRIDGE/DEFER classification, startup order map, and reconnection invalidation map
- `openspec/changes/styrene-rs-daemon-port-execution-plan/tui-inventory.md` (new) — Authoritative TUI behavior census with PORT/BRIDGE/DEFER/DROP classification and IPC contract surface enumeration
- `openspec/changes/styrene-rs-daemon-port-execution-plan/ownership-matrix.md` (new) — Authoritative Rust service-boundary ownership matrix, file-scope map, and MeshTransport trait specification

### Constraints

- Implementation planning should treat S4 daemon include breakup as post-S5 work, not part of the initial wave.
- Every wave must preserve compilation and add tests before collapsing old paths.
- Parallel work should avoid overlapping ownership of RpcDaemon internals unless explicitly serialized.
- Unix socket IPC and PropagationClient should not begin until the new daemon/service interfaces are stable enough to consume.
- Package A should produce the authoritative file-scope map and service ownership matrix used by all later tasks.
- Packages B and C may run in parallel once the transport contract is fixed, but C must not invent semantics independently of B.
- Package D should land before service-slice packages E-H begin.
- Packages E-H should be serialized or narrowly parallelized only when file overlap is acceptably low.
- Package I should be last within the daemon wave; it depends on prior service delegation slices being green.
- Package J should remain blocked until Package I proves stable daemon interfaces.
- Package A must inventory all current Python daemon startup/shutdown responsibilities, not only the Rust-oriented architecture nodes.
- The ownership matrix must record ordered startup dependencies and reconnection invalidation behaviors currently encoded in `styrened/daemon.py`.
- Security-sensitive identity/destination-hash translations and blocklist/RBAC interactions must be explicitly mapped before moving RPC/LXMF behavior.
- Features not ported in the initial daemon wave must be called out as preserve-via-IPC or deferred, with no silent behavioral drop.
- Package A is not complete until every entry in inventory.md has a finalized disposition and the startup/reconnect maps are validated against source.
- TUI port should follow daemon port so it targets stable Rust IPC interfaces.
- The IPCBridge ~60-method surface is the shared contract between daemon and TUI inventories.
- Ratatui TUI must not reintroduce direct mesh/RNS/LXMF dependencies; it must remain a pure IPC client.
