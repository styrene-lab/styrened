# Package A — Python Daemon Behavior Census and Migration Inventory

## Purpose

This document is the authoritative inventory of all behavior currently owned by the Python `styrened` daemon. Every entry must be classified into one of three migration dispositions before Rust daemon implementation begins.

## Migration Dispositions

- **PORT**: include in the initial Rust daemon wave
- **BRIDGE**: preserve temporarily via Python-side IPC/integration until the Rust daemon takes ownership in a later wave
- **DEFER**: explicitly deferred; document compatibility expectations and follow-on plan

No entry may be left unclassified. Unclassified entries block implementation.

---

## 1. Lifecycle and Initialization

### 1.1 Core lifecycle orchestration
- **Source**: `daemon.py:StyreneDaemon.start()`, `services/lifecycle.py:CoreLifecycle`
- **Behavior**: ordered startup of RNS, LXMF, operator identity, and all daemon-owned services; ordered shutdown and cleanup of temp config dirs
- **Startup dependencies**: RNS must init before LXMF; LXMF must init before RPC/conversation/chat
- **Disposition**: `PORT`
- **Notes**: startup order is semantically significant; Rust must preserve or redesign ordering guarantees

### 1.2 Reticulum initialization
- **Source**: `services/lifecycle.py:CoreLifecycle._initialize_reticulum()`
- **Behavior**: config path resolution, temp config generation, port conflict pre-flight, RNS service init, operator destination creation
- **Startup dependencies**: none (first in chain)
- **Disposition**: `PORT`
- **Notes**: port conflict detection via socket bind is a safety feature worth preserving

### 1.3 LXMF initialization
- **Source**: `services/lifecycle.py:CoreLifecycle._initialize_lxmf()`, `services/lxmf_service.py`
- **Behavior**: LXMF router creation, delivery destination registration, announce, propagation node enablement, monkey-patch for upstream LXMF bug
- **Startup dependencies**: RNS must be initialized; operator identity must exist
- **Disposition**: `PORT`
- **Notes**: monkey-patch for `get_outbound_propagation_cost()` is a real bug workaround; Rust LXMF impl may not need it

### 1.4 Operator identity management
- **Source**: `services/reticulum.py:ensure_operator_identity()`, `get_operator_identity_object()`
- **Behavior**: multi-path identity resolution (config override → system → user → LXMF app detection → YubiKey derivation → generate new), identity sharing/symlinking with other LXMF apps
- **Startup dependencies**: none (called during lifecycle init)
- **Disposition**: `PORT`
- **Notes**: YubiKey identity derivation is a distinct code path; identity sharing/symlinking is operator tooling

### 1.5 Operator destination caching and reconnection
- **Source**: `daemon.py:_init_operator_destination()`, `_handle_rns_reconnection()`
- **Behavior**: create and cache operator RNS destination; on RNS reconnect: clear stale destinations, reinitialize, invalidate page/direct-link state, re-enter eager discovery, re-announce
- **Startup dependencies**: RNS + identity init
- **Disposition**: `PORT`
- **Notes**: reconnection is a first-class runtime correctness concern, not optional polish

---

## 2. Transport, Discovery, and Mesh State

### 2.1 Device discovery via announces
- **Source**: `services/reticulum.py:StyreneAnnounceHandler`, `start_discovery()`
- **Behavior**: listen to all RNS announces, parse app_data, detect device types by aspect matching, extract LXMF destination hashes, identity cross-referencing, overlay capability detection, eager Ygg bootstrap
- **Startup dependencies**: RNS init, NodeStore
- **Disposition**: `PORT`
- **Notes**: identity/destination hash architecture is critical for message delivery; cross-reference logic between LXMF and operator announces prevents duplicate entries

### 2.2 Node persistence (NodeStore)
- **Source**: `services/node_store.py:NodeStore`
- **Behavior**: SQLite storage of discovered nodes with identity_hash, destination_hash, lxmf_destination_hash, short_name, capabilities, overlay addresses; thread-safe per-operation connections; prefix matching for partial hashes; path table persistence
- **Startup dependencies**: filesystem paths
- **Disposition**: `PORT`
- **Notes**: NodeStore is the identity resolution authority for LXMF message sending; must preserve hash lookup semantics exactly

### 2.3 Path snapshot service
- **Source**: `services/path_snapshot.py:PathSnapshotService`
- **Behavior**: periodic snapshotting of RNS path table into NodeStore paths table for topology edge data
- **Startup dependencies**: NodeStore, RNS
- **Disposition**: `PORT`
- **Notes**: relatively self-contained

### 2.4 Identity/destination resolution for sending
- **Source**: `services/lxmf_service.py:LXMFService._resolve_identity()`
- **Behavior**: 5-strategy identity resolution cascade: direct recall → NodeStore operator dest → NodeStore LXMF dest → identity hash recall → path request with blocking wait
- **Startup dependencies**: RNS, NodeStore, LXMF
- **Disposition**: `PORT`
- **Notes**: this is security-sensitive and delivery-critical; the multi-strategy cascade exists because RNS hashes are context-dependent (operator vs LXMF vs identity)

---

## 3. Messaging and Conversations

### 3.1 Conversation service
- **Source**: `services/conversation_service.py:ConversationService`
- **Behavior**: SQLAlchemy-backed message persistence, conversation listing, message retrieval, delivery tracking, display name resolution via NodeStore
- **Startup dependencies**: LXMF, NodeStore, ContactService, DB engine
- **Disposition**: `PORT`
- **Notes**: DB schema includes contacts identity_hash backfill migration

### 3.2 Contact service
- **Source**: `services/contacts.py:ContactService`
- **Behavior**: contact address book management, alias resolution, shared DB engine with conversation service
- **Startup dependencies**: DB engine, NodeStore
- **Disposition**: `PORT`
- **Notes**: contacts are a core daemon data surface

### 3.3 Incoming chat message handling
- **Source**: `daemon.py:_handle_chat_message_for_conversation()`
- **Behavior**: protocol discrimination (chat vs styrene vs read_receipt), LXMF field extraction (thread, attachments, security metadata), attachment persistence, conversation save, IPC broadcast
- **Startup dependencies**: conversation service, LXMF, attachment store
- **Disposition**: `PORT`
- **Notes**: ~300 lines of field extraction logic; ecosystem compatibility with Sideband/NomadNet/MeshChat requires preserving all LXMF field handling

### 3.4 Message sending
- **Source**: `services/lxmf_service.py:LXMFService.send_message()`, `send_with_retry()`
- **Behavior**: identity resolution, LXMF destination construction, delivery method selection (direct/propagated/auto), LXMF field injection, delivery/failure callbacks
- **Startup dependencies**: LXMF, identity resolution
- **Disposition**: `PORT`
- **Notes**: delivery method selection includes smart path-availability checking

### 3.5 Read receipt protocol
- **Source**: `protocols/read_receipt.py:ReadReceiptProtocol`
- **Behavior**: handle incoming read receipts, send batched outgoing receipts
- **Startup dependencies**: conversation service, LXMF
- **Disposition**: `PORT`
- **Notes**: ecosystem interop feature

### 3.6 Attachment storage
- **Source**: `services/attachment_store.py`
- **Behavior**: save/rename/retrieve binary attachments keyed by message ID
- **Startup dependencies**: filesystem paths
- **Disposition**: `PORT`
- **Notes**: UUID-based temp naming for concurrent safety

### 3.7 Group threads
- **Source**: `services/group_threads.py`
- **Behavior**: group thread footprint and management
- **Startup dependencies**: conversation service
- **Disposition**: `DEFER`
- **Notes**: group threading model is still a decided-but-unimplemented design node

---

## 4. RPC and Control Plane

### 4.1 RPC server
- **Source**: `rpc/server.py:RPCServer`
- **Behavior**: Styrene wire protocol RPC dispatch, RBAC capability checks, rate limiting, replay protection, handler registration for STATUS_REQUEST/EXEC/REBOOT/CONFIG_UPDATE/SELF_UPDATE/PROVISION/PING/INBOX_QUERY/MESSAGES_QUERY
- **Startup dependencies**: StyreneProtocol, RBAC policy
- **Disposition**: `PORT`
- **Notes**: every message type is capability-gated; unmapped types are rejected (fail-closed); replay protection uses request_id tracking

### 4.2 RPC client
- **Source**: `rpc/client.py`
- **Behavior**: send RPC commands to remote nodes
- **Startup dependencies**: StyreneProtocol
- **Disposition**: `PORT`
- **Notes**: complementary to server

### 4.3 RBAC policy
- **Source**: `models/rbac.py:RBACPolicy`
- **Behavior**: role-based access control with capability mapping, roster management, blocklist
- **Startup dependencies**: config
- **Disposition**: `PORT`
- **Notes**: RBAC is injected into both RPC server and LXMF service

### 4.4 Blocklist management
- **Source**: `services/lxmf_service.py:block_peer()`, `unblock_peer()`, `_seed_blocks_to_rbac()`
- **Behavior**: peer_blocks table in SQLite, seeded into RBAC at startup, contacts best-effort sync
- **Startup dependencies**: LXMF, RBAC, DB
- **Disposition**: `PORT`
- **Notes**: write order is important (peer_blocks first, then RBAC, then contacts)

### 4.5 IPC control server
- **Source**: `daemon.py:_start_control_server()`, TUI IPC integration
- **Behavior**: Unix socket IPC for TUI ↔ daemon communication
- **Startup dependencies**: daemon services, notification service
- **Disposition**: `PORT` (this IS the Unix socket IPC the Rust daemon is building toward)
- **Notes**: critical for TUI integration; contract must be preserved or evolved

---

## 5. Eventing and Notifications

### 5.1 EventBus
- **Source**: `services/event_bus.py:EventBus`
- **Behavior**: async pub/sub event bus with typed events and action discrimination
- **Startup dependencies**: none
- **Disposition**: `PORT`
- **Notes**: canonical internal event system; TUI subscribes to this

### 5.2 Notification service
- **Source**: `services/notifications.py`
- **Behavior**: fan-out to IPC, SSE, callback backends; NotificationEvent typing
- **Startup dependencies**: control server (optional)
- **Disposition**: `PORT`
- **Notes**: bridges between old notification paths and EventBus

### 5.3 Activity ring buffer
- **Source**: `daemon.py:_activity_ring`
- **Behavior**: deque of last 200 events for TUI backfill on connect
- **Startup dependencies**: none
- **Disposition**: `PORT`
- **Notes**: simple but important for TUI catch-up

### 5.4 Legacy notification → EventBus bridge
- **Source**: `daemon.py:_bridge_to_event_bus()`, `_NOTIFICATION_TO_BUS`
- **Behavior**: maps legacy notification type strings to coarse EventBus types
- **Startup dependencies**: EventBus
- **Disposition**: `PORT` initially, then remove legacy paths once Rust owns eventing
- **Notes**: transitional; Rust daemon should emit events natively, not bridge

---

## 6. Protocol Layer

### 6.1 Protocol registry
- **Source**: `protocols/registry.py:ProtocolRegistry`
- **Behavior**: thread-safe protocol handler registration and LXMF message routing by `fields["protocol"]`
- **Startup dependencies**: none
- **Disposition**: `PORT`
- **Notes**: clean abstraction; Rust equivalent should be straightforward

### 6.2 Styrene protocol handler
- **Source**: `protocols/styrene.py:StyreneProtocol`
- **Behavior**: Styrene wire format handling, typed message dispatch, handler registration
- **Startup dependencies**: LXMF
- **Disposition**: `PORT`
- **Notes**: core to RPC and fleet management

### 6.3 Chat protocol handler
- **Source**: `protocols/chat.py`
- **Behavior**: chat message handling for ecosystem compatibility
- **Startup dependencies**: LXMF
- **Disposition**: `PORT`
- **Notes**: ecosystem interop

### 6.4 Wire protocol models
- **Source**: `models/styrene_wire.py:StyreneEnvelope`
- **Behavior**: wire format encode/decode, message type enum, envelope creation helpers
- **Startup dependencies**: none
- **Disposition**: `PORT` (partially done in styrene-mesh crate already)
- **Notes**: cross-language contract; Rust implementation exists in styrene-mesh

---

## 7. Overlay Network Adapters

### 7.1 I2P adapter
- **Source**: `services/i2p.py`
- **Behavior**: I2P tunnel management, b32 address resolution, SAM bridge integration
- **Startup dependencies**: config
- **Disposition**: `DEFER`
- **Notes**: complex external integration; should follow core daemon port

### 7.2 Yggdrasil adapter
- **Source**: `services/yggdrasil.py`
- **Behavior**: Yggdrasil daemon management, peer addition, address resolution, bootstrap from RNS
- **Startup dependencies**: config
- **Disposition**: `DEFER`
- **Notes**: handshake autodetect design already decided; implementation can follow core port

### 7.3 Adapter probe loop
- **Source**: `daemon.py:_start_adapter_probe_loop()`
- **Behavior**: periodic probing of overlay adapter health
- **Startup dependencies**: I2P/Ygg adapters
- **Disposition**: `DEFER`
- **Notes**: follows adapters

---

## 8. Direct Link and Datalink

### 8.1 Direct link service
- **Source**: `services/direct_link.py`
- **Behavior**: RNS link establishment for direct data transfer, /meta fetching, reconnection handling
- **Startup dependencies**: RNS
- **Disposition**: `BRIDGE` initially, `PORT` in follow-on wave
- **Notes**: used by Ygg bootstrap and page browser; non-trivial RNS link lifecycle

### 8.2 Datalink handlers and rate limiting
- **Source**: `daemon.py:_DataLinkRateLimiter`, datalink handler registration
- **Behavior**: RBAC-gated /ping, /meta, /info, /status, /speedtest, /relay handlers over RNS links; per-identity rate limiting with light/heavy tiers
- **Startup dependencies**: RNS, RBAC
- **Disposition**: `BRIDGE` initially, `PORT` in follow-on wave
- **Notes**: /meta enrichment depends on overlay adapters

---

## 9. Page Services

### 9.1 Page browser
- **Source**: `services/page_browser.py`
- **Behavior**: NomadNet page fetching via RNS links
- **Startup dependencies**: RNS, direct link
- **Disposition**: `BRIDGE`
- **Notes**: TUI consumer; can remain Python-side initially

### 9.2 Page cache
- **Source**: `services/page_cache.py`
- **Behavior**: local caching of fetched pages
- **Startup dependencies**: filesystem
- **Disposition**: `BRIDGE`
- **Notes**: follows page browser

### 9.3 Page server
- **Source**: `services/page_server.py`
- **Behavior**: serve local NomadNet pages to network
- **Startup dependencies**: RNS, config
- **Disposition**: `BRIDGE`
- **Notes**: can remain Python-side initially

---

## 10. Network Services

### 10.1 Mesh VPN
- **Source**: `services/mesh_vpn.py`
- **Behavior**: WireGuard mesh VPN management
- **Startup dependencies**: config
- **Disposition**: `DEFER`
- **Notes**: advanced feature; no urgency for first Rust wave

### 10.2 Relay service
- **Source**: `services/relay.py`
- **Behavior**: TURN-style relay for peers behind NAT
- **Startup dependencies**: RNS, RBAC
- **Disposition**: `DEFER`
- **Notes**: advanced feature

### 10.3 Hub connection
- **Source**: `services/hub_connection.py`
- **Behavior**: hub status tracking, configured flag
- **Startup dependencies**: config
- **Disposition**: `BRIDGE` initially, `PORT` later
- **Notes**: relatively simple state tracking

---

## 11. Security and Crypto

### 11.1 PQC session service
- **Source**: `services/pqc_session.py`
- **Behavior**: ML-KEM-768 + X25519 post-quantum key exchange, auto-initiation with discovered Styrene nodes
- **Startup dependencies**: StyreneProtocol, PQC config, liboqs
- **Disposition**: `DEFER`
- **Notes**: depends on liboqs availability; Rust side would use different crypto libs

### 11.2 YubiKey integration
- **Source**: `services/yubikey.py`
- **Behavior**: FIDO2/WebAuthn identity derivation from hardware token
- **Startup dependencies**: none
- **Disposition**: `DEFER`
- **Notes**: niche but valuable; can follow core port

---

## 12. Optional API and Provisioning

### 12.1 HTTP API
- **Source**: web module (FastAPI/uvicorn)
- **Behavior**: REST API, SSE event streaming, Prometheus metrics
- **Startup dependencies**: daemon services
- **Disposition**: `BRIDGE`
- **Notes**: optional `[web]` extra; Python can keep serving this initially

### 12.2 Binary provisioner
- **Source**: `services/binary_provisioner.py`
- **Behavior**: remote adapter binary provisioning over RPC
- **Startup dependencies**: RPC server
- **Disposition**: `DEFER`
- **Notes**: follows overlay adapter work

### 12.3 Terminal service
- **Source**: daemon terminal service
- **Behavior**: remote terminal sessions
- **Startup dependencies**: StyreneProtocol
- **Disposition**: `DEFER`
- **Notes**: advanced operational feature

---

## 13. Configuration and Diagnostics

### 13.1 Config service
- **Source**: `services/config.py`
- **Behavior**: YAML config loading/saving, default generation
- **Startup dependencies**: filesystem paths
- **Disposition**: `PORT`
- **Notes**: Rust daemon needs its own config parsing

### 13.2 Doctor / diagnostics
- **Source**: `services/doctor.py`
- **Behavior**: installation diagnostics, setup wizard, fix mode
- **Startup dependencies**: filesystem, RNS
- **Disposition**: `BRIDGE`
- **Notes**: operator tooling; can remain Python CLI

### 13.3 Hardware / system info
- **Source**: `services/hardware.py`, `services/system_info.py`
- **Behavior**: hardware detection, OS info gathering
- **Startup dependencies**: none
- **Disposition**: `PORT`
- **Notes**: needed for status responses

### 13.4 Auto-reply handler
- **Source**: `services/auto_reply.py`
- **Behavior**: automatic LXMF replies with cooldown tracking
- **Startup dependencies**: LXMF, config
- **Disposition**: `PORT`
- **Notes**: core daemon behavior for unattended operation

---

## Startup Order Map

The following captures the current observed startup order in `StyreneDaemon.start()`:

```
1.  CoreLifecycle.initialize()
    ├── 1a. RNS init (config resolution, port check, service init)
    └── 1b. LXMF init (router, delivery dest, announce)
2.  Operator destination init + reconnect callback registration
3.  RPC server start
4.  I2P adapter start (async)
5.  Yggdrasil adapter start (async)
6.  Adapter probe loop start
7.  LXMF RBAC injection
8.  Conversation service init
    ├── 8a. DB init + schema migration
    ├── 8b. Contact service creation
    ├── 8c. Contacts identity_hash backfill
    ├── 8d. ConversationService creation + init
    ├── 8e. LXMF callback registration (chat)
    └── 8f. Read receipt protocol init
9.  RPC server ← conversation service wiring
10. PQC service init
11. Auto-reply handler start
12. Hub status configuration
13. Device discovery start (with NodeStore, access mode, overlay config)
14. Path snapshot service start
15. HTTP API start (if enabled)
16. IPC control server start (if enabled)
17. Notification service init
18. Terminal service start (if enabled)
19. Page browser start
20. Page server start
21. Direct link start
22. Main run loop (periodic announces, cleanup)
```

## Reconnection Invalidation Map

When RNS interface reconnects (`_handle_rns_reconnection()`):

```
1. Clear RNS service cached destinations
2. Clear daemon cached operator destination
3. Reinitialize operator destination
4. Invalidate page browser links / force path re-discovery
5. Flag direct link service for path re-discovery
6. Re-enter eager discovery phase (15s intervals for 2 min)
7. Re-announce
```

When LXMF handles reconnection (`LXMFService._handle_reconnection()`):

```
1. Clear cached delivery destination
2. (Router left intact; next operation re-registers)
```

---

## Summary Classification

| Disposition | Count | Examples |
|---|---|---|
| **PORT** | ~22 | lifecycle, transport, discovery, messaging, RPC, eventing, protocols, config, auto-reply |
| **BRIDGE** | ~8 | page services, direct link, datalink, HTTP API, hub connection, doctor |
| **DEFER** | ~8 | overlays, VPN, relay, PQC, YubiKey, provisioning, terminal, group threads |

This inventory must be reviewed and finalized before Packages B–J proceed.