---
id: styrene-rs-daemon-port-execution-plan
title: styrene-rs Daemon Port Execution Plan
status: implemented
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

### Post-assessment known items from Packages B–E implementation

**Documented after full clippy + architectural review of Packages B–E (commit c0169f1).**

1. **Announce forwarding task cancellation** (adapter.rs) — The `TokioTransportAdapter` constructor spawns a detached `tokio::spawn` task that forwards announce events from the real transport's async channel to a sync broadcast sender. This task has no explicit cancellation — it exits when the transport's announce channel closes, but `shutdown()` doesn't cancel it. **Fix in Package I**: store the `JoinHandle` or `AbortHandle` and abort in `shutdown()`.

2. **TokioTransportAdapter has no unit tests** — It wraps a real `rns_core::Transport` which requires full RNS infrastructure to instantiate. MockTransport and NullTransport have thorough test coverage (31 contract tests + 18 unit tests), but the production adapter is only exercised through the existing `bootstrap.rs` integration path. **Fix in Package J**: integration tests with a real Transport instance, or extract the packet-construction logic into a testable helper.

3. **`is_connected()` always returns `true`** on TokioTransportAdapter — Currently, transport object existence is treated as connectivity. Real connectivity detection requires monitoring interface status. **Fix in later package**: track interface up/down events and reflect in `is_connected()`. The `subscribe_lifecycle` + `TransportLifecycleEvent` infrastructure is already in place for this.

4. **`send_raw` is a transport primitive, not LXMF delivery** — Documented in the trait. The caller (MessagingService, Package F) must handle LXMF wire format details like stripping the destination prefix for opportunistic delivery. The existing `TransportBridge.deliver()` does this in `bridge_helpers::opportunistic_payload()`. That logic migrates to MessagingService.

5. **InterfaceConfig made Clone** — The `config.rs` model's `InterfaceConfig` was changed from `#[derive(Debug, Deserialize)]` to `#[derive(Debug, Clone, Deserialize)]` to support `ConfigService::interfaces()` returning owned copies. This is a minor API surface change on an internal type — no external consumers affected.

### Pre-Package F architectural audit: existing modules, integration points, and library gaps

**Audit scope**: all existing styrened-rs modules relevant to Package F (messaging, discovery, node storage), plus styrene-lxmf and styrene-ipc crate surfaces.

**Existing modules to compose (not reimplement):**
- `storage/messages.rs` (575 LOC) — MessagesStore with SQLite CRUD for messages AND announces. Schema init, pagination, pruning, receipt status updates. Already the unified storage layer.
- `announce_names.rs` (153 LOC) — Pure functions for parsing peer names from announce app_data. Three strategies: msgpack array, PN metadata map, UTF-8 fallback. Used by announce_worker.
- `inbound_delivery.rs` (120 LOC) — Decode inbound LXMF wire payloads into MessageRecord. Uses styrene-lxmf decode_inbound_message. No RpcDaemon coupling.
- `lxmf_bridge.rs` (34 LOC) — Build outbound LXMF wire messages from title/content/fields. Signs with PrivateIdentity. No RpcDaemon coupling.
- `receipt_bridge.rs` (65 LOC) — Receipt correlation and handler. Pure helpers except `handle_receipt_event` which calls into RpcDaemon (this function migrates to MessagingService).
- `identity_store.rs` (77 LOC) — Load/create identity key files. Already used by bootstrap. Atomic write with tmp+rename, Unix 0600 perms.

**IPC trait contract (styrene-ipc):**
- `DaemonMessaging` — 12 async methods: send_chat, mark_read, delete_conversation, delete_message, retry_message, query_conversations, query_messages, search_messages, query_attachment, set_contact, remove_contact, query_contacts, resolve_name.
- `DaemonStatus` — includes query_devices (announce-based device list) which reads from the announce store.
- `DaemonEvents` — subscribe_messages, subscribe_devices (broadcast channels).

**Library gaps: none.** All needed crates already in deps: rusqlite (storage), tokio broadcast (pub/sub), rmpv/rmp-serde (msgpack), serde_json (JSON fields), hex (hash encoding), async-trait, thiserror.

**Key insight: MessagesStore IS the NodeStore.** The announce table (insert_announce, list_announces) lives in the same SQLite DB as messages. No separate storage struct needed — DiscoveryService writes announces, other services read them, all through the same MessagesStore instance.

**SDK subsystem excluded from Package F.** RpcDaemon's sdk_*.rs files (negotiate, runtime, helpers, topics, attachments, markers, identity, paper_command, voice, auth_http, capabilities, outbound = ~3,000+ LOC) manage the SDK contract lifecycle. This is deeply coupled to RpcDaemon fields and should NOT be mixed into domain services. It stays in RpcDaemon until Package I or becomes a dedicated SdkService.

### Pre-Package I gap analysis: 39 Daemon trait methods vs service readiness

**Assessment of which Daemon trait methods can delegate to real service behavior vs which must remain stubbed.**

**Ready for real delegation (~15 methods):**
- DaemonIdentity: query_identity (IdentityService.identity_hash + metadata), announce (IdentityService.announce)
- DaemonStatus: query_status (StatusService.uptime+interfaces+propagation + transport.is_connected), query_config (ConfigService), query_auto_reply (AutoReplyService.config), set_auto_reply (AutoReplyService.set_config), query_devices (DiscoveryService.list_announces → DeviceInfo mapping)
- DaemonMessaging: query_messages (MessagingService.list_messages), get partial via MessagingService
- DaemonEvents: subscribe can wrap EventService.subscribe with DaemonEvent conversion

**Must remain NotImplemented (~24 methods):**
- DaemonIdentity: set_identity (needs identity metadata storage — display_name, icon, short_name)
- DaemonStatus: query_path_info (needs transport path table access not yet exposed)
- DaemonMessaging: send_chat (needs full delivery pipeline), mark_read/delete_conversation/delete_message (need store extensions), retry_message (needs delivery pipeline), query_conversations (needs grouped query), search_messages (needs FTS), query_attachment (needs attachment storage), set_contact/remove_contact/query_contacts (needs contact table), resolve_name (needs node store name lookup)
- DaemonFleet: all 10 methods (FleetService is stub — RPC dispatch deeply coupled to RpcDaemon)
- DaemonTunnel: all 5 methods (TunnelService is DEFER'd)

**Key decision**: Package I creates the facade with auth enforcement and wires what's ready. Remaining methods return IpcError::NotImplemented. This matches StubDaemon's pattern — the facade replaces it as the IPC-facing type, starting mostly-stubbed but with real service delegation for ready methods. Store extensions (delete, search, contacts, conversations) are follow-on work that incrementally fills methods.

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

### Decision: NodeStore is a service-level abstraction over MessagesStore's announce table, not a separate storage struct

**Status:** decided
**Rationale:** MessagesStore already owns both messages and announces in a single SQLite database with unified schema init. Creating a separate NodeStore struct would mean either (A) two DB connections to the same file, or (C) breaking apart the schema init. Option B is correct: DiscoveryService owns announce writes via store.insert_announce(), other services read via store.list_announces(). The 'NodeStore' from the ownership matrix becomes a conceptual view — the DiscoveryService write interface to the announce side of MessagesStore. The original ownership-matrix.md §NodeStore decision ('shared storage module, DiscoveryService writes, others read') is preserved in spirit: DiscoveryService writes, MessagingService/IdentityService/FleetService read, but through the existing MessagesStore rather than a new struct.

### Decision: Package F services compose existing modules, not reimplement them

**Status:** decided
**Rationale:** The existing modules (MessagesStore, announce_names, inbound_delivery, lxmf_bridge, receipt_bridge) are already pure functions or data-focused structs with no RpcDaemon coupling. Package F services wrap and compose these: MessagingService holds Arc<Mutex<MessagesStore>>, uses inbound_delivery for decode, lxmf_bridge for wire encode, receipt_bridge helpers for correlation. DiscoveryService uses announce_names for parsing. No logic reimplementation needed — services are thin orchestrators over well-factored existing code. The SDK subsystem (~11 files, 3,000+ LOC) is explicitly excluded from Package F — it stays in RpcDaemon until Package I or becomes its own service.

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
- `crates/apps/styrened-rs/src/transport/mesh_transport.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/transport/adapter.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/transport/null_transport.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/transport/mock_transport.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/transport/mod.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/mod.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/identity.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/config.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/status.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/auth.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/auto_reply.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/messaging.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/discovery.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/protocol.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/events.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/tunnel.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/services/fleet.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/app_context.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/daemon_facade.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/lib.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/src/bin/reticulumd/bootstrap.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/Cargo.toml` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/tests/transport_null.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/tests/transport_contract.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/tests/app_context_construction.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `crates/apps/styrened-rs/tests/daemon_facade_contract.rs` (modified) — Post-assess reconciliation delta — touched during follow-up fixes

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
