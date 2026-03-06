# Styrened RBAC — Preliminary Analysis & Recommendations

**Date:** 2026-03-06  
**Version:** v0.13.43  
**Status:** Exploratory / RFC

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

### 4.1 Role Hierarchy

```
ADMIN          — Full control: EXEC, REBOOT, CONFIG, SELF_UPDATE, terminal, VPN peering
OPERATOR       — Fleet management: STATUS, CONFIG_UPDATE, terminal (restricted shells)
MONITOR        — Read-only: STATUS, PING, page browsing, web dashboard (read-only)
PEER           — Mesh peer: chat, page browsing, datalink (no VPN)
VPN_PEER       — Trusted VPN peer: everything PEER has + VPN key exchange
BLOCKED        — Explicit deny: all messages dropped
```

Roles are **cumulative** — higher roles include all lower capabilities. Exception: `VPN_PEER` is an explicit grant orthogonal to the main hierarchy (a MONITOR should not get VPN access, but a PEER might).

### 4.2 Capability Mapping

| Capability | BLOCKED | (default) | PEER | VPN_PEER | MONITOR | OPERATOR | ADMIN |
|-----------|---------|-----------|------|----------|---------|----------|-------|
| Receive chat | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Browse pages | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| PING/STATUS | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Establish datalink | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VPN handshake | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Web API (read) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Web API (write) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| CONFIG_UPDATE | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Terminal (restricted) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| EXEC / REBOOT | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Terminal (full shell) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| SELF_UPDATE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

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

### 4.5 Implementation Model

```python
# src/styrened/models/rbac.py

from enum import IntEnum, auto
from dataclasses import dataclass, field

class Role(IntEnum):
    """Ordered role hierarchy. Higher value = more privilege."""
    BLOCKED = 0
    NONE = 1        # No explicit assignment, subject to default_role
    PEER = 10
    VPN_PEER = 15   # PEER + VPN capability
    MONITOR = 20
    OPERATOR = 30
    ADMIN = 40

class Capability(Enum):
    CHAT_RECEIVE = auto()
    PAGE_BROWSE = auto()
    PING_STATUS = auto()
    DATALINK = auto()
    VPN_HANDSHAKE = auto()
    WEB_READ = auto()
    WEB_WRITE = auto()
    CONFIG_UPDATE = auto()
    TERMINAL_RESTRICTED = auto()
    EXEC = auto()
    TERMINAL_FULL = auto()
    SELF_UPDATE = auto()
    REBOOT = auto()

# Role → capability mapping
ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = { ... }

@dataclass
class RBACPolicy:
    """Central authorization policy."""
    default_role: Role = Role.PEER
    roster: dict[str, Role] = field(default_factory=dict)  # identity_hash → Role
    blocked: list[str] = field(default_factory=list)  # prefix-matching

    def resolve_role(self, identity_hash: str) -> Role:
        """Resolve effective role for an identity."""
        # Check blocked first (prefix matching)
        for prefix in self.blocked:
            if identity_hash.startswith(prefix):
                return Role.BLOCKED
        # Check explicit roster
        if identity_hash in self.roster:
            return self.roster[identity_hash]
        # Fall back to default
        return self.default_role

    def has_capability(self, identity_hash: str, cap: Capability) -> bool:
        role = self.resolve_role(identity_hash)
        return cap in ROLE_CAPABILITIES[role]
```

### 4.6 Integration Points

Each subsystem replaces its own auth check with a single call:

```python
# Before (RPC server):
if not self._is_authorized(source_hash):
    ...

# After:
if not self._rbac.has_capability(source_hash, Capability.EXEC):
    ...
```

The `RBACPolicy` instance lives on the daemon and is injected into every service that needs authorization.

---

## 5. Migration Strategy

### Phase 1: Model + Central Policy (non-breaking)
- Add `src/styrened/models/rbac.py` with `Role`, `Capability`, `RBACPolicy`
- Add `rbac` section to `CoreConfig` with parsing in `services/config.py`
- Add `RBACPolicy` to daemon, populated from config
- **No behavioral changes** — existing `authorized_identities` still works

### Phase 2: RPC + Terminal Integration
- Replace RPC `_is_authorized()` with capability checks
- Replace Terminal identity check with capability checks
- Map legacy `authorized_identities` → `admin` role, `enable_dangerous_commands` → preserved as override
- Fix fail-open/fail-closed inconsistency (both should respect `default_role`)
- **Deprecation warnings** for `authorized_identities` in config

### Phase 3: DirectLink + VPN Gating
- Add capability check to DirectLink incoming link acceptance
- Gate VPN handshake behind `VPN_HANDSHAKE` capability
- Add capability check to datalink request handlers

### Phase 4: Web API + LXMF Layer
- Replace `WebAuthConfig.authorized_identities` with RBAC role check
- Map `public_mode` to `default_role: monitor`
- Add optional LXMF-layer allow-list (inbound chat restricted to PEER+ roles)
- Deprecate `banned_peers` in favor of `rbac.blocked`

### Phase 5: Cleanup
- Remove all per-subsystem `authorized_identities` fields
- Remove `enable_dangerous_commands` (replaced by role-based capability)
- Remove `banned_peers` (replaced by `rbac.blocked`)
- Update all documentation and TUI settings screens

---

## 6. Open Questions

1. **Should roles be mutable at runtime via IPC?** Currently blocked peers can be added/removed via IPC. Should `rbac.roster` be editable via IPC/TUI, or config-file-only?

2. **Role inheritance vs explicit capabilities?** The proposal uses a hierarchy. Alternative: each identity gets an explicit set of capabilities (more flexible, more complex to configure).

3. **Group/tag support?** Should identities be groupable (e.g., "all edge devices" → OPERATOR) or is per-identity assignment sufficient for the expected fleet sizes?

4. **Transitive trust?** If node A trusts node B as ADMIN, and B vouches for C, does C get any implicit trust? (Probably not for v1, but relevant for mesh-native identity.)

5. **PQC integration?** The PQC session layer (`models/pqc.py`) adds post-quantum key exchange. Should RBAC roles interact with PQC tiers (e.g., ADMIN requires PQC session)?

6. **Announce-based role advertisement?** Should a node's RBAC policy be discoverable via announce data (e.g., "this node requires ADMIN for terminal"), or is it opaque until you try?

---

## 7. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| DirectLink has zero auth today | **High** | Phase 3 priority; VPN handshake over unauthenticated channel is the worst gap |
| RPC fail-open on empty whitelist | **High** | Phase 2 — default_role=none for ENDPOINT profile |
| Migration breaks existing configs | **Medium** | Legacy field parsing preserved through Phase 4, deprecation warnings in Phase 2 |
| Role hierarchy too rigid | **Low** | VPN_PEER orthogonal grant demonstrates extensibility; can add more |
| Complexity for single-node operators | **Low** | `default_role: peer` + single admin identity covers 90% of deployments |

---

## 8. Recommendation

**Start with Phase 1 immediately** — the model is additive and non-breaking. Phase 2 should follow quickly to fix the fail-open RPC inconsistency, which is the most operationally dangerous gap today. Phase 3 (DirectLink/VPN gating) is the most security-critical and should land before any VPN feature is promoted beyond experimental.

The existing `authorized_identities` pattern has reached its limits. Five independent whitelists with inconsistent fail-open/fail-closed semantics is a bug farm. A unified RBAC model is the right abstraction for a fleet management daemon.
