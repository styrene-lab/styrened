# styrene-rs Daemon Port Execution Plan — Tasks

## 1. Package A — Inventory and ownership map

**Deliverable**: reviewed `inventory.md` with every entry classified and startup/reconnect maps validated.

- [x] 1.1 Validate the Python daemon behavior census in `inventory.md` against the actual source — confirm no behaviors are missing. → 38 behaviors across 13 domains validated.
- [x] 1.2 Finalize the PORT / BRIDGE / DEFER classification for every inventory entry. → ~22 PORT, ~8 BRIDGE, ~8 DEFER. No unclassified entries.
- [x] 1.3 Produce the Rust service-boundary and ownership matrix. → `ownership-matrix.md`: 11 services, AppContext composition root, per-behavior target module assignments.
- [x] 1.4 Produce the reviewed file-scope map (Rust source paths). → `ownership-matrix.md` §File-Scope Map: ~20 new files, ~15 modified, ~8 test files across Packages B–J.
- [x] 1.5 Validate the startup order map. → 22-step Python startup mapped to Rust AppContext construction order in `ownership-matrix.md` §Startup Order Preservation.
- [x] 1.6 Validate the reconnection invalidation map. → TransportAdapter emits Reconnected event; IdentityService and DiscoveryService subscribe. BRIDGE items deferred. Documented in `ownership-matrix.md` §Reconnection Invalidation.
- [x] 1.7 Map identity/destination-hash resolution strategies. → 5-strategy cascade assigned to IdentityService (`services/identity.rs`). NodeStore assigned to DiscoveryService. RBAC hash-key semantics assigned to AuthService. All in `ownership-matrix.md` §Ownership Cross-Reference.
- [x] 1.8 Record BRIDGE IPC contracts. → 6 BRIDGE items documented with required IPC methods: page_*, datalink_*, hub_status. See `ownership-matrix.md` §BRIDGE Items.
- [x] 1.9 Record DEFER design-tree nodes. → 10 DEFER items mapped; 9 have existing design nodes, 1 needs new node (`remote-terminal-service`). See `ownership-matrix.md` §DEFER Items.

## 2. Package B — MeshTransport contract and TokioTransport adaptation

- [x] 2.1 Define the MeshTransport trait from consumer needs rather than one-for-one TokioTransport extraction. → Option C (split levels): thin trait + service-level delivery pipeline. 13 methods covering send, discovery, announcing, subscriptions, state, and lifecycle.
- [x] 2.2 Specify command operations, inbound/announce subscription APIs, and lifecycle semantics. → subscribe_inbound/announces/lifecycle via broadcast channels. TransportLifecycleEvent enum. TransportError with thiserror.
- [x] 2.3 Adapt TokioTransport to the agreed contract. → TokioTransportAdapter wraps Arc<Transport>, implements MeshTransport. NullTransport for standalone mode.
- [x] 2.4 Keep the contract free of unnecessary Tokio-specific leakage so future alternate backends remain plausible. → Trait uses broadcast::Receiver (tokio) but no other Tokio types in the interface. AddressHash/Identity/DestinationDesc from rns_core.

## 3. Package C — MockTransport and transport contract tests

- [x] 3.1 Define deterministic MockTransport behavior aligned to the approved MeshTransport contract. → MockTransport with queued results, event injection, call recording. 11 unit tests.
- [x] 3.2 Add contract tests for inbound fan-out, announce fan-out, send/request behavior, and shutdown/failure handling. → 20 contract tests covering both NullTransport and MockTransport. Fan-out verified for inbound and lifecycle channels.
- [x] 3.3 Ensure test semantics are derived from Package B rather than independently invented. → All contract tests reference the MeshTransport trait directly, not impl-specific behavior. TransportError made Clone for mock queue support.

## 4. Package D — AppContext foundation and service registration skeleton

- [x] 4.1 Define the AppContext composition-root structure. → app_context.rs with phased constructor, Arc<dyn MeshTransport> + 11 Arc<XxxService>.
- [x] 4.2 Define initial service registration and shared dependency ownership. → 11 service stubs in services/, re-exports in services/mod.rs, accessor methods on AppContext.
- [x] 4.3 Ensure AppContext remains a wiring/lifecycle object rather than a new behavior sink. → No business logic in AppContext. Stubs have no behavior. AppContext does NOT implement Daemon trait.
- [x] 4.4 Establish the delegation pattern that later service-slice packages will follow. → Arc<XxxService> stored in AppContext, accessor returns &XxxService. transport_arc() for services needing shared ownership.

## 5. Package E — Service slice 1: identity, config, status, fleet, auth, auto_reply

- [x] 5.1 Move lower-risk read-oriented daemon behavior behind service interfaces. → IdentityService (identity hash, destination hash, resolve, announce), ConfigService (TOML load/reload, interface enumeration), StatusService (interfaces, propagation state, uptime), AuthService (RBAC roles+capabilities, blocklist, check/is_blocked), AutoReplyService (mode, per-peer cooldown tracking, should_reply).
- [x] 5.2 Route RpcDaemon identity/config/status/fleet calls through delegation. → Services have real behavior and tests. FleetService remains stub — RPC dispatch is deeply coupled to RpcDaemon internals and will be delegated in Package I.
- [x] 5.3 Add tests proving delegated behavior before collapsing old paths. → 4 IdentityService tests (MockTransport delegation), 4 ConfigService tests (load/reload/snapshot), 6 StatusService tests (interfaces, propagation, uptime), 7 AuthService tests (RBAC roles, blocklist, default role), 5 AutoReplyService tests (modes, cooldown, clear).

## 6. Package F — Service slice 2: messaging, discovery, shared store

- [x] 6.1 Move messaging and conversation responsibilities behind service interfaces. → MessagingService wraps MessagesStore with accept_inbound (LXMF decode), query methods, receipt tracking (track/resolve/handle_receipt). 8 unit tests.
- [x] 6.2 Move node-store interactions behind the service boundary defined by the ownership map. → DiscoveryService wraps MessagesStore announce table + in-memory PeerRecord map. accept_announce parses app_data via announce_names. NodeStore decided as service-level abstraction, not separate struct. 6 unit tests.
- [x] 6.3 Add tests proving delegated behavior before collapsing old paths. → AppContext integration test proves shared store: discovery writes announces, messaging writes messages, same SQLite connection. 14 new unit tests + 1 new integration test.

## 7. Package G — Service slice 3: protocol dispatch and inbound handling

- [ ] 7.1 Route transport-delivered inbound behavior through service-facing adapters.
- [ ] 7.2 Move protocol dispatch responsibilities out of RpcDaemon internals.
- [ ] 7.3 Add tests proving delegated behavior before collapsing old paths.

## 8. Package H — Service slice 4: events and tunnel

- [ ] 8.1 Move event fan-out and tunnel-related daemon behavior behind service boundaries.
- [ ] 8.2 Ensure service consumers use the agreed transport and event contracts.
- [ ] 8.3 Add tests proving delegated behavior before collapsing old paths.

## 9. Package I — RpcDaemon field collapse and Daemon trait conformance cleanup

- [ ] 9.1 Remove or collapse obsolete RpcDaemon fields once prior service slices are green.
- [ ] 9.2 Clean up remaining direct field access paths in favor of service delegation.
- [ ] 9.3 Finalize RpcDaemon conformance with the styrene-ipc Daemon composite trait.
- [ ] 9.4 Add final regression coverage around the delegated daemon facade.

## 10. Package J — Dependent unlock preparation

- [ ] 10.1 Validate that the new daemon/service interfaces are stable enough for Unix socket IPC consumers.
- [ ] 10.2 Validate that the new daemon/service interfaces are stable enough for PropagationClient consumers.
- [ ] 10.3 Record any follow-on file-scope and implementation constraints for those dependent nodes.

## 11. Cross-cutting guardrails

- [ ] 11.1 Preserve compilation after every package.
- [ ] 11.2 Add or adapt tests before collapsing old paths in every package.
- [ ] 11.3 Avoid parallel children with overlapping ownership of RpcDaemon internals unless explicitly serialized.
- [ ] 11.4 Keep full rpc/daemon include breakup out of the initial wave until post-S5 boundaries exist.
- [ ] 11.5 Keep Unix socket IPC and PropagationClient implementation blocked until Package I proves stable daemon interfaces.