# turn-relay — Tasks

## 1. Relay data models and error hierarchy

Models layer — no service logic, no daemon wiring. Pure dataclasses and exceptions.

- [x] 1.1 Create src/styrened/models/relay.py with RelayConfig dataclass (enabled, max_sessions, max_per_identity, max_bytes_per_session, idle_timeout, allow_permanent, allowed_identities) with defaults per spec
- [x] 1.2 Add RelaySession dataclass (requester_hash, target_hash, bytes_forwarded, is_permanent, is_priority, created_at, last_activity) with record_bytes() method
- [x] 1.3 Add LinkType enum (DIRECT, RELAYED) to models/relay.py
- [x] 1.4 Add RelayError base exception with error_code, plus 12 subclasses (RelayDisabled, RelayMaxSessions, RelayMaxPerIdentity, RelayByteLimitExceeded, RelayIdleTimeout, RelayUnauthorized, RelayPermanentDenied, RelayTargetRejected, RelayTargetOffline, RelayPermanentConsentDenied, RelayEvicted, RelayBridgeDenied) each with unique error_code
- [x] 1.5 Create tests/unit/test_relay_errors.py — 12 error type tests (distinct classes, unique codes, inheritance), RelayConfig defaults, RelaySession creation + byte tracking, LinkType enum

## 2. RBAC relay capabilities

Add 10 relay.* capabilities to existing RBAC model and role tiers. No service changes.

- [x] 2.1 Add to src/styrened/models/rbac.py: relay.request, relay.list, relay.teardown, relay.accept, relay.reject at PEER tier
- [x] 2.2 Add relay.request_permanent, relay.accept_permanent, relay.prioritize, relay.bridge at OPERATOR tier
- [x] 2.3 Add relay.admin at ADMIN tier
- [x] 2.4 Ensure all 10 relay.* capabilities are in Capability.ALL registry
- [x] 2.5 Create tests/unit/test_relay_rbac.py — tier membership tests, ALL registry inclusion, has_capability checks for relay.request (PEER grants), relay.request_permanent (PEER denied, OPERATOR grants), relay.admin (ADMIN only), relay.reject override behavior

## 3. RelayService core + config integration

Hub-side service with session lifecycle, limit enforcement, eviction. Config parsing.

- [x] 3.1 Create src/styrened/services/relay.py with RelayService class — init takes RelayConfig, tracks active sessions dict
- [x] 3.2 Implement create_session(requester_hash, target_hash, permanent=False, priority=False) — enforces enabled check, global cap, per-identity cap, RBAC checks, target online check. Returns RelaySession
- [x] 3.3 Implement teardown_session(session_id) — removes session, handles disconnect propagation (default: tear down both halves; permanent: keep surviving half, attempt reconnect for grace period)
- [x] 3.4 Implement _idle_check() periodic task — scans sessions, tears down idle non-permanent sessions, records RelayIdleTimeout
- [x] 3.5 Implement _enforce_byte_limit(session, nbytes) — raises RelayByteLimitExceeded and tears down if exceeded (skipped for permanent)
- [x] 3.6 Implement LRU eviction in create_session — when at max_sessions, evict oldest non-priority session (RelayEvicted); if all priority, raise RelayMaxSessions
- [x] 3.7 Add relay: section parsing in src/styrened/services/config.py — maps YAML to RelayConfig, add RelayConfig field to CoreConfig in src/styrened/models/config.py
- [x] 3.8 Config serialization round-trip: save_core_config/load_core_config preserves relay section
- [x] 3.9 Create tests/unit/test_relay.py — session lifecycle (create, teardown, disconnect propagation), all limit enforcement (global cap, per-identity cap, byte limit, idle timeout), permanent session exemptions, LRU eviction (priority vs non-priority), disabled hub rejection, target offline detection. Config parse + round-trip tests.

## 4. DirectLink integration and daemon wiring

Wire RelayService into DirectLink and daemon. Add /relay endpoint, RELAYED link type tracking.

- [x] 4.1 Add link_type field (LinkType.DIRECT default) to DirectLinkService link entry tracking
- [x] 4.2 Add /relay DirectLink endpoint handler on hub — accepts relay requests, delegates to RelayService, bridges request forwarding between two links
- [x] 4.3 Implement request forwarding: hub receives link.request() from peer A, forwards to peer B's link, returns response. Channel-based signaling for relay control (setup, teardown, keepalive)
- [x] 4.4 Wire RelayService into daemon.py — init in _start_direct_link(), inject RBAC policy, shutdown cleanup
- [x] 4.5 Add relay config to daemon config loading path
- [x] 4.6 Add tests for DirectLink relay endpoint, RELAYED link type, daemon wiring (RelayService started/stopped with daemon)
