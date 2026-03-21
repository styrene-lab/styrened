# Package A — Rust Service-Boundary and Ownership Matrix

## Purpose

This document maps every PORT-classified daemon behavior to its target Rust crate and module. It defines who owns what, where new code goes, and how AppContext wires services together. All later packages (B–J) reference this matrix for file-scope decisions.

## Existing Crate Inventory

| Crate | Role | LOC | Port relevance |
|---|---|---|---|
| `styrene-rns` | RNS protocol, transport, identity, crypto | 11,620 | Owns transport layer; MeshTransport trait lives here or in a new boundary crate |
| `styrene-lxmf` | LXMF message types, delivery, SDK | 4,615 | Wire-level LXMF; consumed by daemon services |
| `styrene-mesh` | StyreneEnvelope wire protocol | 799 | Wire codec; already ported |
| `styrene-ipc` | Daemon trait (6 sub-traits) + StubDaemon + types | 954 | **Target interface**; RpcDaemon must conform to this |
| `styrene-content` | Content distribution | 1,835 | Independent; not in critical path |
| `styrene-micron` | Micron parser | 1,692 | BRIDGE — page browser dependency |
| `styrene-tunnel` | PQC tunnel, WireGuard, strongSwan | 2,249 | DEFER — follows core daemon port |
| `styrened-rs` | Daemon app: RpcDaemon, bridges, storage | 17,084 | **Primary decomposition target** |
| `styrene-tui` | Ratatui stub | 624 | Future TUI host |
| `styrene-dx` | Dioxus stub | 129 | Future desktop/web host |
| `styrene-native` | PyO3 bindings | 572 | BRIDGE for FFI hybrid mode |

## RpcDaemon Current State (the god struct)

```
RpcDaemon (29 LOC struct def + 23 include! files = 7,467 LOC)
├── init.rs — constructors, initialization helpers
├── dispatch.rs — RPC method routing
├── dispatch_legacy_*.rs (5 files) — legacy message/propagation/misc/clear/router dispatch
├── sdk_*.rs (11 files) — SDK subsystem (negotiate, runtime, helpers, topics, attachments,
│                          markers, identity, paper_command, voice, auth_http, capabilities, outbound)
├── events.rs — event broadcasting and subscription
├── metrics.rs — RPC metrics collection
├── cursor_utils.rs — pagination helpers
└── tests.rs + tests/ (6 test files) — unit and integration tests
```

**Fields**: 50+ Mutex-wrapped fields mixing messaging, SDK state, event broadcasting, propagation, delivery policy, metrics, and bridge trait objects.

---

## Target Service Boundary

After decomposition, `AppContext` owns wiring; services own behavior.

### AppContext (composition root)
- **Location**: `styrened-rs/src/app_context.rs` (new)
- **Owns**: service construction, dependency wiring, lifecycle orchestration (start/shutdown ordering)
- **Does NOT own**: any business logic, any direct field access to message store or SDK state, any IPC dispatch
- **Pattern**: `Arc<AppContext>` held by services for cross-service access; services accessed via accessor methods
- **Startup order**: preserves the 22-step Python startup sequence semantics
- **Not the Daemon implementor**: see DaemonFacade below

### DaemonFacade (IPC-facing dispatch)
- **Location**: `styrened-rs/src/daemon_facade.rs` (new — Package I)
- **Implements**: `styrene-ipc::Daemon` composite trait
- **Owns**: auth enforcement (calls `AuthService::check()` before delegating), IPC-level error mapping
- **Holds**: `Arc<AppContext>` (delegates to services)
- **Pattern**: `Arc<dyn Daemon>` passed to IPC handlers; services never see it
- **Rationale**: (1) separates composition from consumption — AppContext wires, DaemonFacade dispatches; (2) prevents circular calls — services hold `Arc<AppContext>`, IPC holds `Arc<dyn Daemon>`, never service→facade→service; (3) natural auth enforcement point — RBAC checks happen here, services trust their caller

### Service Decomposition

| Service | Rust module | IPC trait | Owns (from inventory) | Package |
|---|---|---|---|---|
| **IdentityService** | `styrened-rs/src/services/identity.rs` | `DaemonIdentity` | 1.4 operator identity, 2.4 destination resolution, announce trigger | E |
| **ConfigService** | `styrened-rs/src/services/config.rs` | (partial `DaemonStatus`) | 13.1 config load/save, 13.3 hardware/system info | E |
| **StatusService** | `styrened-rs/src/services/status.rs` | `DaemonStatus` | query_status, query_devices proxy, path info query | E |
| **FleetService** | `styrened-rs/src/services/fleet.rs` | `DaemonFleet` | 4.1 RPC server dispatch, 4.2 RPC client, exec/reboot/update, terminal sessions | E |
| **AuthService** | `styrened-rs/src/services/auth.rs` | (internal) | 4.3 RBAC policy + roster, 4.4 blocklist (peer_blocks table); exposes `check(identity, capability)` and `is_blocked(identity)` — enforcement is DaemonFacade's job | E |
| **MessagingService** | `styrened-rs/src/services/messaging.rs` | `DaemonMessaging` | 3.1 conversations, 3.2 contacts, 3.3 chat handling, 3.4 sending, 3.5 read receipts, 3.6 attachments; queries `AuthService::is_blocked()` for inbound filtering | F |
| **DiscoveryService** | `styrened-rs/src/services/discovery.rs` | (internal) | 2.1 announce handling, 2.3 path snapshots, device type detection; writes to NodeStore | F |
| **NodeStore** | `styrened-rs/src/storage/node_store.rs` | (internal) | 2.2 node persistence, identity/destination hash lookups, prefix matching; shared read layer consumed by MessagingService (display names), IdentityService (dest resolution), FleetService (capabilities), DiscoveryService (writes) | F |
| **ProtocolService** | `styrened-rs/src/services/protocol.rs` | (internal) | 6.1 registry, 6.2 StyreneProtocol, 6.3 ChatProtocol, 6.4 wire models | G |
| **EventService** | `styrened-rs/src/services/events.rs` | `DaemonEvents` | 5.1 EventBus, 5.2 notifications, 5.3 activity ring, event fan-out | H |
| **TunnelService** | `styrened-rs/src/services/tunnel.rs` | `DaemonTunnel` | tunnel lifecycle — wraps `styrene-tunnel` crate | H |
| **AutoReplyService** | `styrened-rs/src/services/auto_reply.rs` | (internal) | 13.4 auto-reply: per-peer cooldown tracking, reply composition, sends through MessagingService; reads config from ConfigService | E |
| **TransportAdapter** | `styrened-rs/src/transport/adapter.rs` | MeshTransport trait | 1.5 reconnection, transport lifecycle, send/receive routing | B |

### Module Layout After Decomposition

```
styrened-rs/src/
├── app_context.rs          (new — Package D: composition root)
├── daemon_facade.rs        (new — Package I: Daemon trait impl, auth enforcement)
├── services/
│   ├── mod.rs              (new — Package D)
│   ├── identity.rs         (new — Package E)
│   ├── config.rs           (existing, extend — Package E)
│   ├── status.rs           (new — Package E)
│   ├── fleet.rs            (new — Package E)
│   ├── auth.rs             (new — Package E)
│   ├── auto_reply.rs       (new — Package E)
│   ├── messaging.rs        (new — Package F)
│   ├── discovery.rs        (new — Package F)
│   ├── protocol.rs         (new — Package G)
│   ├── events.rs           (new — Package H)
│   └── tunnel.rs           (new — Package H)
├── transport/
│   ├── mod.rs              (existing)
│   ├── adapter.rs          (new — Package B)
│   ├── mesh_transport.rs   (new — Package B, trait definition — daemon-internal only)
│   ├── mock_transport.rs   (new — Package C)
│   └── test_bridge.rs      (existing)
├── rpc/
│   ├── mod.rs              (existing — modified by Package I)
│   ├── daemon.rs           (existing — shrinks through E–H, collapses in I)
│   ├── daemon/             (existing include files — progressively emptied)
│   ├── codec.rs            (existing)
│   ├── types.rs            (existing — some types migrate to service modules)
│   ├── params.rs           (existing)
│   ├── helpers.rs          (existing)
│   ├── http.rs             (existing — BRIDGE)
│   ├── event_sink.rs       (existing — migrates to EventService)
│   ├── replay.rs           (existing)
│   └── send_request.rs     (existing)
├── storage/
│   ├── mod.rs              (existing)
│   ├── messages.rs         (existing — remains shared; accessed via service layer)
│   └── node_store.rs       (new — Package F: shared read layer, DiscoveryService writes)
├── lib.rs                  (existing — add services module)
├── lxmf_bridge.rs          (existing)
├── receipt_bridge.rs       (existing)
├── identity_store.rs       (existing)
├── inbound_delivery.rs     (existing)
├── announce_names.rs       (existing)
├── rns_crypto.rs           (existing)
└── e2e_harness.rs          (existing)
```

---

## Ownership Cross-Reference: Inventory → Rust Target

### PORT Items

| # | Behavior | Target Module | Depends On | Notes |
|---|---|---|---|---|
| 1.1 | Lifecycle orchestration | `app_context.rs` | all services | startup/shutdown ordering |
| 1.2 | RNS initialization | `app_context.rs` + `styrene-rns` | — | config resolution, port pre-flight |
| 1.3 | LXMF initialization | `app_context.rs` + `styrene-lxmf` | RNS | router, delivery dest |
| 1.4 | Operator identity | `services/identity.rs` | `identity_store.rs` | multi-path resolution cascade |
| 1.5 | Destination caching + reconnect | `transport/adapter.rs` | identity, discovery | reconnection invalidation map |
| 2.1 | Device discovery | `services/discovery.rs` | transport, `announce_names.rs` | announce handler + type detection |
| 2.2 | NodeStore | `storage/node_store.rs` | storage | SQLite node persistence; shared read by messaging/identity/fleet |
| 2.3 | Path snapshot | `services/discovery.rs` | transport, NodeStore | periodic path table capture |
| 2.4 | Identity/dest resolution | `services/identity.rs` | NodeStore, RNS | 5-strategy cascade |
| 3.1 | Conversation service | `services/messaging.rs` | storage, contacts | SQLAlchemy → rusqlite |
| 3.2 | Contact service | `services/messaging.rs` | storage | address book |
| 3.3 | Chat message handling | `services/messaging.rs` | protocol, storage | field extraction, IPC broadcast |
| 3.4 | Message sending | `services/messaging.rs` | identity, LXMF | delivery method selection |
| 3.5 | Read receipts | `services/messaging.rs` | LXMF | ecosystem interop |
| 3.6 | Attachment storage | `services/messaging.rs` + `storage/` | filesystem | UUID-based temp naming |
| 4.1 | RPC server | `services/fleet.rs` | protocol, auth | RBAC-gated dispatch |
| 4.2 | RPC client | `services/fleet.rs` | protocol | remote command sending |
| 4.3 | RBAC | `services/auth.rs` | config | role/capability mapping |
| 4.4 | Blocklist | `services/auth.rs` | storage, RBAC | peer_blocks table |
| 4.5 | IPC control server | `bin/reticulumd/rpc_loop.rs` | app_context | Unix socket server |
| 5.1 | EventBus | `services/events.rs` | — | async pub/sub |
| 5.2 | Notification service | `services/events.rs` | IPC | fan-out to IPC/SSE |
| 5.3 | Activity ring | `services/events.rs` | — | deque backfill |
| 5.4 | Legacy notification bridge | `services/events.rs` | — | transitional; remove post-port |
| 6.1 | Protocol registry | `services/protocol.rs` | — | handler registration |
| 6.2 | StyreneProtocol | `services/protocol.rs` | `styrene-mesh` | wire format dispatch |
| 6.3 | ChatProtocol | `services/protocol.rs` | LXMF | ecosystem compat |
| 6.4 | Wire protocol models | `styrene-mesh` crate | — | already ported |
| 13.1 | Config service | `services/config.rs` | filesystem | YAML load/save |
| 13.3 | Hardware/system info | `services/status.rs` | — | sysinfo crate |
| 13.4 | Auto-reply | `services/auto_reply.rs` | messaging, config | per-peer cooldown tracking, reply composition, sends through MessagingService |

### BRIDGE Items (remain Python-side initially)

| # | Behavior | IPC Contract Needed | Notes |
|---|---|---|---|
| 8.1 | Direct link service | `page_*` IPC methods | Used by page browser + Ygg bootstrap |
| 8.2 | Datalink handlers | `datalink_*` IPC methods | RBAC-gated /ping, /meta, etc. |
| 9.1–9.3 | Page services | `page_*` IPC methods on bridge | NomadNet pages stay Python-side |
| 10.3 | Hub connection | `hub_status` IPC method | Simple state tracking |
| 12.1 | HTTP API | None (Python web server) | Optional `[web]` extra |
| 13.2 | Doctor/diagnostics | CLI-only | Python CLI tool |

### DEFER Items (design-tree nodes needed)

| # | Behavior | Existing Design Node | Needs New Node |
|---|---|---|---|
| 7.1 | I2P adapter | `i2p-adapter-adoption-model` | No |
| 7.2 | Yggdrasil adapter | `yggdrasil-service` | No |
| 7.3 | Adapter probe loop | follows adapters | No |
| 10.1 | Mesh VPN | `mesh-vpn-integration` | No |
| 10.2 | Relay service | `nat-traversal-relay` | No |
| 11.1 | PQC sessions | `pqc-tunnel-*` nodes | No |
| 11.2 | YubiKey | `yubikey-identity-derivation` | No |
| 12.2 | Binary provisioner | `rpc-binary-provisioner` | No |
| 12.3 | Terminal service | — | Yes: `remote-terminal-service` |
| 3.7 | Group threads | `lxmf-group-discussion-model` | No |

---

## MeshTransport Trait (Package B contract)

The trait lives in `styrened-rs/src/transport/mesh_transport.rs` (daemon-internal, NOT promoted to `styrene-ipc`).

**Design decision**: Option C — split levels. MeshTransport is a **thin trait** wrapping raw transport operations. The delivery pipeline (path request → identity poll → link attempt → opportunistic fallback → receipt tracking) lives in **MessagingService** as service-level orchestration. Rust's type system makes the wiring provable — `Arc<dyn MeshTransport>` in service constructors is enforced at compile time.

```rust
use rns_core::destination::DestinationDesc;
use rns_core::hash::AddressHash;
use rns_core::identity::Identity;
use rns_core::transport::core_transport::{AnnounceEvent, ReceivedData, SendPacketOutcome};
use rns_core::transport::delivery::LinkSendResult;
use std::time::Duration;
use tokio::sync::broadcast;

/// Transport lifecycle events — services subscribe to react to connectivity changes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportLifecycleEvent {
    Connected,
    Disconnected,
    Reconnected,
}

/// Errors from transport operations.
#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("transport unavailable")]
    Unavailable,
    #[error("send failed: {0}")]
    SendFailed(String),
    #[error("link failed: {0}")]
    LinkFailed(#[from] std::io::Error),
    #[error("shutdown failed: {0}")]
    ShutdownFailed(String),
}

#[async_trait::async_trait]
pub trait MeshTransport: Send + Sync {
    // --- Sending ---

    /// Opportunistic single-packet send (broadcast, no link setup).
    async fn send_raw(
        &self,
        dest: AddressHash,
        data: &[u8],
    ) -> Result<SendPacketOutcome, TransportError>;

    /// Link-based reliable send (with resource fallback for large payloads).
    /// Caller must provide a fully-resolved DestinationDesc (includes peer Identity).
    async fn send_via_link(
        &self,
        dest: DestinationDesc,
        data: &[u8],
        timeout: Duration,
    ) -> Result<LinkSendResult, TransportError>;

    // --- Discovery ---

    /// Trigger path request for a destination.
    async fn request_path(&self, dest: &AddressHash);

    /// Look up peer identity from transport's announce table.
    /// Returns None if identity not yet known (peer hasn't announced).
    async fn resolve_identity(&self, dest: &AddressHash) -> Option<Identity>;

    // --- Announcing ---

    /// Send announce with optional app_data.
    async fn announce(&self, app_data: Option<&[u8]>);

    // --- Subscriptions (broadcast channels) ---

    /// Subscribe to inbound data events (decoded payloads delivered to our destination).
    fn subscribe_inbound(&self) -> broadcast::Receiver<ReceivedData>;

    /// Subscribe to announce events from other nodes.
    fn subscribe_announces(&self) -> broadcast::Receiver<AnnounceEvent>;

    /// Subscribe to transport lifecycle transitions (connected/disconnected/reconnected).
    fn subscribe_lifecycle(&self) -> broadcast::Receiver<TransportLifecycleEvent>;

    // --- State queries ---

    /// Our identity address hash.
    fn identity_hash(&self) -> AddressHash;

    /// Our delivery destination hash.
    fn destination_hash(&self) -> AddressHash;

    /// Whether transport is currently connected/operational.
    fn is_connected(&self) -> bool;

    // --- Lifecycle ---

    /// Shut down the transport gracefully.
    async fn shutdown(&self) -> Result<(), TransportError>;
}
```

### Design rationale

**Why thin, not thick**: The existing `TransportBridge::deliver()` does significantly more than raw send — it's a full delivery pipeline (path request → identity wait → link → fallback → receipts). That logic belongs in MessagingService, not hidden inside a monolithic trait. This keeps the trait mockable with deterministic behavior and lets service-level tests verify delivery strategy independently.

**Why `send_via_link` is on the trait**: Link establishment (encrypted bidirectional RNS channel) is genuinely a transport concern — the protocol-level handshake, proof exchange, and resource fallback. The service layer decides *when* to use link vs opportunistic; the transport layer owns *how*. The `send_via_link` free function in `rns_core::transport::delivery` maps directly to this method.

**Why `resolve_identity` instead of a separate IdentityService lookup**: Transport already maintains the announce table mapping `AddressHash → Identity`. This is a read-only query into transport state, not an identity management operation. IdentityService uses this as one strategy in its 5-strategy resolution cascade.

**NullTransport**: Implements MeshTransport for standalone/test mode. Returns `TransportError::Unavailable` on sends, empty receivers on subscribes, `false` from `is_connected()`. Eliminates `Option<Arc<dyn MeshTransport>>` throughout services.

**Type constructability verified**: All referenced rns_core types have public fields and/or public constructors:
- `AddressHash::new([u8; 16])`, `::new_from_hex_string()`
- `Identity::new(PublicKey, VerifyingKey)`, `::new_from_slices()`
- `DestinationDesc { identity, address_hash, name }` — all pub fields
- `ReceivedData { destination, data, payload_mode, ... }` — all pub fields
- `AnnounceEvent { destination, app_data, ... }` — all pub fields
- `PacketDataBuffer` = `StaticBuffer<PACKET_MDU>`, `::new()`, `::new_from_slice()`
- `SendPacketOutcome` — public enum variants
- `LinkSendResult` — public enum variants

### Consumer contracts

- **MessagingService** → `send_raw` + `send_via_link` + `request_path` + `resolve_identity` + `subscribe_inbound` (delivery pipeline orchestration + receipt tracking)
- **DiscoveryService** → `subscribe_announces` + `subscribe_lifecycle` (device discovery, reconnect re-entry)
- **IdentityService** → `announce` + `identity_hash` + `destination_hash` + `resolve_identity` + `subscribe_lifecycle` (identity management, re-announce on reconnect)
- **FleetService** → `send_raw` or `send_via_link` + `subscribe_inbound` (RPC request/response; fleet builds its own correlation layer)
- **EventService** → `subscribe_lifecycle` (lifecycle event fanout to IPC)
- **Tests** → `MockTransport` with canned responses, deterministic send results, injectable inbound/announce events

---

## Daemon Trait Conformance Plan

`RpcDaemon` currently does NOT implement `styrene-ipc::Daemon`. After decomposition:

```
    IPC handlers                          Services (hold Arc<AppContext>)
         │                                         │
         ▼                                         ▼
  ┌──────────────┐                     ┌───────────────────────┐
  │ DaemonFacade │──── delegates ────▶ │      AppContext       │
  │ impl Daemon  │                     │  (composition root)   │
  │              │                     └───────────┬───────────┘
  │ auth.check() │                                 │ owns
  │ before each  │         ┌───────────┬───────────┼───────────┬───────────┐
  │ delegation   │         ▼           ▼           ▼           ▼           ▼
  └──────────────┘   Identity    Messaging    Status/Fleet   Events    Auth
                     Service     Service      Service        Service   Service
                        │           │             │             │         │
                        └───────────┴─────────────┴─────────────┘         │
                                        │                                 │
                              ┌─────────┴─────────┐              ┌───────┘
                              ▼                   ▼              ▼
                         NodeStore           MessagesStore    RBAC policy
                       (shared read)        (shared storage)  (check/block)
```

**Call direction**: IPC → DaemonFacade → AuthService.check() → Service → storage/transport.
Services never call DaemonFacade. Services access each other through AppContext accessors.

`DaemonFacade` (Package I) is a thin struct holding `Arc<AppContext>` that:
1. Checks RBAC via `auth.check(caller, capability)` before every delegation
2. Delegates to the appropriate service through AppContext
3. Maps service errors to IPC errors

This replaces `RpcDaemon` as the IPC-facing type. `StubDaemon` (in `styrene-ipc`) remains available for frontend testing without any daemon infrastructure.

---

## File-Scope Map for Implementation

### Package B — MeshTransport (2 new files, 1 modified)
- `[new]  styrened-rs/src/transport/mesh_transport.rs` — trait + error types
- `[new]  styrened-rs/src/transport/adapter.rs` — TokioTransport adapter
- `[mod]  styrened-rs/src/transport/mod.rs` — re-exports

### Package C — MockTransport (1 new file, 1 new test file)
- `[new]  styrened-rs/src/transport/mock_transport.rs` — deterministic mock
- `[new]  styrened-rs/tests/transport_contract.rs` — contract tests

### Package D — AppContext (2 new files, 1 modified)
- `[new]  styrened-rs/src/app_context.rs` — composition root
- `[new]  styrened-rs/src/services/mod.rs` — service module
- `[mod]  styrened-rs/src/lib.rs` — add services + app_context modules

### Package E — Service slice 1 (6 new files, modified daemon includes)
- `[new]  styrened-rs/src/services/identity.rs`
- `[new]  styrened-rs/src/services/config.rs` (or extend existing `config.rs`)
- `[new]  styrened-rs/src/services/status.rs`
- `[new]  styrened-rs/src/services/fleet.rs`
- `[new]  styrened-rs/src/services/auth.rs` — RBAC policy + roster + blocklist data; check/is_blocked methods
- `[new]  styrened-rs/src/services/auto_reply.rs` — cooldown tracking, reply composition, sends via MessagingService
- `[mod]  styrened-rs/src/rpc/daemon/init.rs` — delegate to services
- `[mod]  styrened-rs/src/rpc/daemon/dispatch_legacy_misc.rs` — delegate
- `[mod]  styrened-rs/src/rpc/daemon/sdk_identity.rs` — delegate

### Package F — Service slice 2 (3 new files, modified daemon includes)
- `[new]  styrened-rs/src/services/messaging.rs`
- `[new]  styrened-rs/src/services/discovery.rs`
- `[new]  styrened-rs/src/storage/node_store.rs` — shared read layer; DiscoveryService writes, others read
- `[mod]  styrened-rs/src/rpc/daemon/dispatch_legacy_messages.rs` — delegate
- `[mod]  styrened-rs/src/rpc/daemon/dispatch.rs` — delegate
- `[mod]  styrened-rs/src/storage/messages.rs` — service-facing API refinement
- `[mod]  styrened-rs/src/storage/mod.rs` — add node_store module

### Package G — Service slice 3 (1 new file, modified daemon includes)
- `[new]  styrened-rs/src/services/protocol.rs`
- `[mod]  styrened-rs/src/rpc/daemon/dispatch_legacy_router.rs` — delegate
- `[mod]  styrened-rs/src/rpc/daemon/dispatch_legacy_propagation.rs` — delegate
- `[mod]  styrened-rs/src/inbound_delivery.rs` — service-facing adapter

### Package H — Service slice 4 (2 new files, modified daemon includes)
- `[new]  styrened-rs/src/services/events.rs`
- `[new]  styrened-rs/src/services/tunnel.rs`
- `[mod]  styrened-rs/src/rpc/daemon/events.rs` — delegate to EventService
- `[mod]  styrened-rs/src/rpc/event_sink.rs` — delegate

### Package I — Facade collapse (1 new file, major daemon modification)
- `[new]  styrened-rs/src/daemon_facade.rs` — thin Daemon trait impl
- `[mod]  styrened-rs/src/rpc/mod.rs` — RpcDaemon field removal
- `[mod]  styrened-rs/src/rpc/daemon.rs` — collapse remaining includes
- `[mod]  styrened-rs/src/bin/reticulumd/bootstrap.rs` — use AppContext
- `[mod]  styrened-rs/src/bin/reticulumd/rpc_loop.rs` — use DaemonFacade

### Package J — Dependent unlock (documentation + interface validation)
- `[mod]  styrened-rs/src/bin/reticulumd/rpc_loop.rs` — Unix socket readiness check
- `[new]  styrened-rs/tests/daemon_facade_contract.rs` — facade-level integration tests

### Cross-cutting test files
- `[new]  styrened-rs/tests/service_identity.rs`
- `[new]  styrened-rs/tests/service_messaging.rs`
- `[new]  styrened-rs/tests/service_discovery.rs`
- `[new]  styrened-rs/tests/service_events.rs`
- `[new]  styrened-rs/tests/service_fleet.rs`
- `[new]  styrened-rs/tests/service_auth.rs`

---

## Startup Order Preservation

The Python daemon's 22-step startup must map to Rust AppContext construction:

| Python step | Rust equivalent | Service owner |
|---|---|---|
| 1a. RNS init | `Transport::new()` via config | TransportAdapter |
| 1b. LXMF init | LXMF bridge construction | AppContext |
| 2. Operator destination | `IdentityService::init()` | IdentityService |
| 3. RPC server start | `FleetService::init()` | FleetService |
| 7. RBAC injection | `AuthService::init()` | AuthService |
| 8. Conversation + contacts | `MessagingService::init()` | MessagingService |
| 9. RPC ← conversation wiring | AppContext wiring | AppContext |
| 11. Auto-reply | `ConfigService::init_auto_reply()` | ConfigService |
| 13. Discovery | `DiscoveryService::start()` | DiscoveryService |
| 14. Path snapshot | `DiscoveryService::start_path_snapshots()` | DiscoveryService |
| 16. IPC server | `rpc_loop::run()` | binary main |
| 17. Notifications | `EventService::init()` | EventService |
| 22. Main loop | tokio select! in main | binary main |

Steps 4–6 (overlay adapters), 10 (PQC), 15 (HTTP), 18 (terminal), 19–21 (pages/direct link) are BRIDGE/DEFER and not wired in the initial Rust startup.

---

## Reconnection Invalidation

Preserved in TransportAdapter + AppContext:

| Python invalidation step | Rust owner |
|---|---|
| Clear cached destinations | IdentityService (notified by TransportAdapter) |
| Reinitialize operator dest | IdentityService |
| Invalidate page/direct-link | BRIDGE — not in initial Rust scope |
| Re-enter eager discovery | DiscoveryService (notified by TransportAdapter) |
| Re-announce | IdentityService (triggered by TransportAdapter) |

TransportAdapter emits a `Reconnected` event; services subscribe and handle their own invalidation.

---

## Summary

| Metric | Count |
|---|---|
| New Rust files | ~22 |
| Modified Rust files | ~15 |
| New test files | ~8 |
| Services | 12 (Identity, Config, Status, Fleet, Auth, AutoReply, Messaging, Discovery, Protocol, Event, Tunnel, TransportAdapter) |
| Shared storage | 2 (NodeStore, MessagesStore) |
| Composition root | 1 (AppContext) |
| IPC facade | 1 (DaemonFacade) |
| Existing crates modified | 1 (styrened-rs) |
| New crates | 0 |
| Packages | 10 (A–J) |
