# Styrened RBAC — Preliminary Analysis & Recommendations

**Date:** 2026-03-06  
**Version:** v0.14.7  
**Status:** Phases 1–4 COMPLETE (v0.14.7) — Phase 5 (legacy removal) planned for v0.15.0

---

## 1. Executive Summary

Styrened has **five independent authorization surfaces**, each with its own identity whitelist, config knobs, and enforcement point. There is no unified role model — every subsystem reinvents "is this identity allowed?" with subtle behavioral differences. This creates operational complexity, inconsistent security posture, and no path to granular permissions.

This report maps the current state, identifies gaps, and proposes a unified RBAC model that can be adopted incrementally.

---

## 2. Current Authorization Surfaces

### 2.1 RPC Server (`rpc/server.py`)

| Aspect | Current State |
|--------|--------------|
| **Identity gate** | `authorized_identities: set[str]` — flat set of hex hashes |
| **File-based loading** | `authorized_identities_file` — one hash per line, `#` comments |
| **Command classes** | Binary: `PUBLIC_RPC_COMMANDS` (PING, STATUS_REQUEST) vs everything else |
| **Dangerous commands** | `enable_dangerous_commands` bool — gates EXEC, REBOOT, CONFIG_UPDATE, SELF_UPDATE |
| **Fail-open behavior** | If `authorized_identities` is empty, **all identities are authorized** (logged warning) |
| **Rate limiting** | Per-identity, 30 req/min default |
| **Replay protection** | 16-byte request_id tracking, 5-min expiry |

**Gap:** No middle ground between "can do STATUS_REQUEST" and "can do everything including EXEC." An operator who should manage config but not execute arbitrary commands cannot be expressed.

### 2.2 Terminal Service (`terminal/service.py`)

| Aspect | Current State |
|--------|--------------|
| **Identity gate** | `authorized_identities: set[str]` — same pattern as RPC |
| **Fail-closed** | If empty and `allow_unauthenticated=False`, **all connections rejected** (opposite of RPC!) |
| **Shell whitelist** | `allowed_shells` — path-based validation |
| **Command whitelist** | `allowed_commands` — optional, None = shells only |
| **Session limits** | Per-identity (3) and total (10) caps |
| **Rate limiting** | 10 session requests/min/identity |

**Gap:** Authorization is all-or-nothing per identity. No per-identity shell/command restrictions. An authorized identity gets full shell access to whatever shells are globally allowed.

### 2.3 Web API Auth (`web/auth.py`, `web/auth_middleware.py`)

| Aspect | Current State |
|--------|--------------|
| **Mechanism** | Ed25519 challenge-response using RNS identities |
| **Identity gate** | `WebAuthConfig.authorized_identities: set[str]` |
| **Allow-all mode** | `allow_unauthenticated` — any identity that completes challenge is granted session |
| **Localhost bypass** | `exempt_localhost` — loopback requests skip auth entirely |
| **Session management** | Cookie-based, configurable TTL (default 24h) |
| **Write protection** | `public_mode` — rejects all write operations (orthogonal to identity auth) |

**Gap:** No role distinction. An authenticated identity can do everything the API exposes (read + write) unless `public_mode` is globally on. No per-identity read-only vs read-write.

### 2.4 Blocklist / Banned Peers

| Aspect | Current State |
|--------|--------------|
| **Client-side block** | `Contact.blocked` field in DB, IPC commands `CMD_BLOCK_PEER`/`CMD_UNBLOCK_PEER`/`QUERY_BLOCKED_PEERS`. Drops inbound LXMF messages from blocked identity. |
| **Hub-side ban** | `CoreConfig.banned_peers: list[str]` — prefix-matching hex hashes. Seeded from config on startup via `_seed_config_bans()`. |
| **Persistence** | Client blocks: SQLite (survives restarts if DB persists). Hub bans: config file (must be in ArgoCD-tracked configmap for K8s). |

**Gap:** Blocklist is deny-only, no allow-list at the LXMF layer. A node cannot restrict who can *send* it chat messages to a known set — it can only reactively block after receiving unwanted messages.

### 2.5 Direct Link Service (`services/direct_link.py`)

| Aspect | Current State |
|--------|--------------|
| **Authorization** | **None.** Any peer that knows the datalink destination hash can establish an RNS.Link. |
| **Request handlers** | `/status`, `/ping`, `/vpn/handshake` — all open to any linked peer. |
| **Trust model** | Implicit — RNS.Link provides encryption and identity verification at the transport layer, but the service applies no application-level authorization. |

**Gap:** This is the most privileged channel (low-latency, persistent, used for VPN key exchange) and has the weakest authorization. Any peer that discovers the datalink destination can establish a link and request a VPN handshake.

### 2.6 Mesh VPN (`services/mesh_vpn.py`)

| Aspect | Current State |
|--------|--------------|
| **Authorization** | **None beyond DirectLinkService.** If a peer can establish a datalink, they can exchange WireGuard keys. |
| **Key exchange** | Over DirectLinkService `/vpn/handshake` path — inherits whatever (lack of) auth DirectLink has. |

**Gap:** VPN peering should require explicit trust. An identity that can chat with you should not automatically be able to join your WireGuard mesh.

---

## 3. Inconsistency Matrix

| Behavior | RPC Server | Terminal | Web API | DirectLink | LXMF/Chat |
|----------|-----------|----------|---------|------------|-----------|
| Empty whitelist | **Fail-open** | **Fail-closed** | Configurable | N/A (no whitelist) | Open |
| Per-identity granularity | Binary (public vs all) | All-or-nothing | All-or-nothing | None | Block-only |
| Rate limiting | ✅ 30/min | ✅ 10/min | ✅ (challenge only) | ❌ | ❌ |
| Replay protection | ✅ | ❌ | ❌ (nonce-based) | ❌ | ❌ |
| Config location | Constructor args | Constructor args | `WebAuthConfig` | None | `banned_peers` in `CoreConfig` |
| File-based identity loading | ✅ | ✅ | ❌ | ❌ | ❌ |

The most dangerous inconsistency: **RPC fails open, Terminal fails closed.** An operator who forgets to configure `authorized_identities` gets a wide-open RPC server but a locked-down terminal — the opposite of what you'd want (RPC includes EXEC which is equivalent to a shell).

---

## 4. Proposed Unified RBAC Model

### 4.1 Role Hierarchy (as implemented in `models/rbac.py`)

```
ADMIN (40)     — Full control: EXEC, REBOOT, SELF_UPDATE, TERMINAL_FULL
OPERATOR (30)  — Fleet management: CONFIG_UPDATE, TERMINAL_RESTRICTED, WEB_WRITE
MONITOR (20)   — Read-only: INBOX_READ, WEB_READ, DATALINK_ESTABLISH, DATALINK_SPEEDTEST
PEER (10)      — Mesh peer: chat, pages, ping, status, datalink info/meta/ping/status
NONE (1)       — No capabilities (fail-closed default for edge devices)
BLOCKED (0)    — Explicit deny: all requests dropped
```

Roles are **cumulative** — higher roles include all lower capabilities. `VPN_HANDSHAKE` is an **orthogonal grant** not included in any role tier — it must be explicitly granted per identity.

### 4.2 Capability Mapping (as implemented)

| Capability | BLOCKED | NONE | PEER | MONITOR | OPERATOR | ADMIN |
|-----------|---------|------|------|---------|----------|-------|
| chat.send / chat.receive | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| page.browse | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| rpc.ping / rpc.status | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| datalink.ping / meta / info / status | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| rpc.inbox_read | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| web.read | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| datalink.establish / speedtest | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| rpc.config_update | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| terminal.restricted | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| web.write | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| rpc.exec / rpc.reboot / rpc.self_update | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| terminal.full | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| vpn.handshake (orthogonal) | ❌ | grant | grant | grant | grant | ✅ |

### 4.3 Default Policy

The **default** (no explicit role assignment) should be configurable per deployment profile:

| Profile | Default for unknown identities |
|---------|-------------------------------|
| `OPERATOR` (personal node) | `PEER` — open mesh, chat with anyone |
| `ENDPOINT` (edge device) | `(none)` — fail-closed, only configured identities |
| `HUB` (public transport) | `PEER` — relay for all, admin restricted |

### 4.4 Configuration Design

```yaml
# core-config.yaml
rbac:
  # Default role for identities not in the roster
  default_role: peer  # or: none, monitor, peer

  # Identity → role roster
  roster:
    - identity: "abc123..."
      role: admin
      label: "cwilson macbook"  # optional human label

    - identity: "def456..."
      role: operator
      label: "monitoring bot"

    - identity: "cafe..."
      role: vpn_peer
      label: "edge-pi-01"

  # Blocked identities (replaces banned_peers)
  blocked:
    - "ca3e9813"  # prefix matching preserved

  # Legacy compatibility (map to roles automatically)
  # These would be deprecated but still parsed:
  # authorized_identities → admin
  # banned_peers → blocked
```

### 4.5 Implementation Model (actual — see `src/styrened/models/rbac.py`)

Capabilities use `ClassVar[str]` constants (not Enum) for config readability. `RosterEntry` supports per-identity `grants` for orthogonal capabilities (e.g., `vpn.handshake`). `RBACPolicy` includes `get_allow_list()` for RNS-native `ALLOW_LIST` enforcement and `should_use_allow_all()` for the ALLOW_ALL/ALLOW_LIST decision.

### 4.6 Integration Points (all implemented as of v0.14.7)

| Surface | Method | Gate |
|---------|--------|------|
| RPC | `RPCServer._is_authorized()` | `rbac.has_capability(source, MESSAGE_TYPE_CAPABILITY[msg_type])` |
| LXMF | `LXMFService._is_blocked()` | `rbac.resolve_role(source) == BLOCKED` |
| DirectLink | `daemon._datalink_allow_mode()` | RNS ALLOW_LIST per handler + app-layer RBAC |
| Terminal | `TerminalService.is_authorized()` | `rbac.has_capability(id, TERMINAL_RESTRICTED \| TERMINAL_FULL)` |
| Web challenge | `auth.challenge()` | `rbac.has_capability(id, WEB_READ)` |
| Web verify | `auth.verify()` | RBAC re-check before session issuance |
| Web middleware | `AuthMiddleware.dispatch()` | `rbac.has_capability(id, WEB_WRITE)` for POST/PUT/PATCH/DELETE |

---

## 5. Migration Strategy

### Phase 1: Model + Central Policy (non-breaking) — ✅ COMPLETE (v0.14.3)
- Added `src/styrened/models/rbac.py` with `Role`, `Capability`, `RBACPolicy`, `RosterEntry`
- Added `rbac` section to `CoreConfig` with parsing in `services/config.py`
- Added `RBACPolicy` to daemon, populated from config
- ~60 unit tests covering role resolution, capability checks, grants, hierarchy

### Phase 2: RPC + LXMF Integration — ✅ COMPLETE (v0.14.6)
- Replaced RPC `_is_authorized()` with `rbac.has_capability()` per message type
- Fixed fail-open vulnerability: empty whitelist now denies when RBAC active
- Unified LXMF blocklist: `_is_blocked()` uses `rbac.resolve_role()==BLOCKED`
- Dual-write: `block_peer()`/`unblock_peer()` write to both contacts DB and RBAC
- `_seed_contacts_blocks_to_rbac()` loads runtime blocks into RBAC on startup
- 61 RBAC tests across `test_rpc_rbac.py` and `test_lxmf_rbac.py`

### Phase 3: DirectLink ALLOW_LIST Enforcement — ✅ COMPLETE (v0.14.7)
- All 5 DirectLink handlers switched from ALLOW_ALL to RBAC-gated allow mode
- Added `DATALINK_PING`, `DATALINK_META`, `DATALINK_INFO` capabilities at PEER tier
- Moved `DATALINK_STATUS` from MONITOR to PEER tier (app-layer still gates full data)
- `_datalink_allow_mode()` computes (allow_flag, allowed_list) per capability
- `_reregister_datalink_handlers()` for roster-change re-registration
- App-layer RBAC gates on all 5 handlers (defense-in-depth)
- 39 tests via strict TDD in `test_datalink_rbac.py`

### Phase 4: Terminal + Web API — ✅ COMPLETE (v0.14.7)
- `TerminalService.is_authorized()` checks `TERMINAL_RESTRICTED`/`TERMINAL_FULL`
- `TerminalService.authorization_level()` returns "full", "restricted", or None
- Web API `challenge()` checks `WEB_READ` via RBAC before issuing challenge nonce
- Web API `verify()` re-checks RBAC before issuing session token (TOCTOU fix)
- `AuthMiddleware` gates mutating methods (POST/PUT/PATCH/DELETE) on `WEB_WRITE`
- GET-only endpoints require `WEB_READ` (session) only
- Legacy fallback preserved when `rbac_policy=None` across all surfaces
- 23 terminal RBAC tests + 16 web auth RBAC tests

### Phase 5: Cleanup — ⬜ PLANNED (v0.15.0)
- Remove all per-subsystem `authorized_identities` fields
- Remove `enable_dangerous_commands` (replaced by role-based capability)
- Remove `banned_peers` (replaced by `rbac.blocked`)
- Remove `allow_unauthenticated` fields
- Update all documentation and TUI settings screens
- **Breaking config change** → major version bump

---

## 6. Open Questions

1. **Should roles be mutable at runtime via IPC?** Currently blocked peers can be added/removed via IPC. Should `rbac.roster` be editable via IPC/TUI, or config-file-only?

2. **Role inheritance vs explicit capabilities?** The proposal uses a hierarchy. Alternative: each identity gets an explicit set of capabilities (more flexible, more complex to configure).

3. **Group/tag support?** Should identities be groupable (e.g., "all edge devices" → OPERATOR) or is per-identity assignment sufficient for the expected fleet sizes?

4. **Transitive trust?** If node A trusts node B as ADMIN, and B vouches for C, does C get any implicit trust? (Probably not for v1, but relevant for mesh-native identity.)

5. **PQC integration?** The PQC session layer (`models/pqc.py`) adds post-quantum key exchange. Should RBAC roles interact with PQC tiers (e.g., ADMIN requires PQC session)?

6. **Announce-based role advertisement?** Should a node's RBAC policy be discoverable via announce data (e.g., "this node requires ADMIN for terminal"), or is it opaque until you try?

---

## 7. Risk Assessment (updated post-Phase 4)

| Risk | Severity | Status |
|------|----------|--------|
| DirectLink has zero auth today | **High** | ✅ RESOLVED — Phase 3 (ALLOW_LIST + app-layer gates) |
| RPC fail-open on empty whitelist | **High** | ✅ RESOLVED — Phase 2 (fail-closed when RBAC active) |
| Migration breaks existing configs | **Medium** | ✅ MITIGATED — Legacy fallback preserved through Phase 4; removal in Phase 5 (v0.15.0) |
| Role hierarchy too rigid | **Low** | ✅ MITIGATED — Orthogonal grants (vpn.handshake) prove extensibility |
| Complexity for single-node operators | **Low** | ✅ MITIGATED — `default_role: peer` + single admin identity covers 90% |
| Phase 5 config breakage | **Medium** | ⬜ PENDING — Needs migration tooling and deprecation warnings before removal |

---

## 8. Current Status & Next Steps

Phases 1–4 are complete as of v0.14.7. All 6 auth surfaces are RBAC-gated with legacy fallback. 2608 unit tests pass.

**Phase 5 (v0.15.0)** is the final step: remove all legacy config fields. This is a **breaking config change** requiring:
1. Deprecation warnings in a v0.14.x release for any config still using legacy fields
2. Migration guide documentation
3. `_migrate_legacy_to_rbac()` config rewriter (optional CLI tool)
4. Major version bump to signal the break
