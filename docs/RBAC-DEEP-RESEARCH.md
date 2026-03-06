# Styrened RBAC: Deep Implementation Research

**Date:** 2026-03-06  
**Prerequisite:** [RBAC-PRELIMINARY-REPORT.md](RBAC-PRELIMINARY-REPORT.md)  
**Status:** Phases 1–4 implemented (v0.14.7) — Phase 5 (legacy removal) planned for v0.15.0

---

## Table of Contents

1. [RNS Identity Primitives Available](#1-rns-identity-primitives-available)
2. [Prior Art Survey](#2-prior-art-survey)
3. [Architecture Options Evaluated](#3-architecture-options-evaluated)
4. [Recommended Architecture: Hybrid Capability-Role Model](#4-recommended-architecture-hybrid-capability-role-model)
5. [Data Model Design](#5-data-model-design)
6. [Enforcement Point Design](#6-enforcement-point-design)
7. [Configuration Schema](#7-configuration-schema)
8. [Wire Protocol Considerations](#8-wire-protocol-considerations)
9. [Migration Path from Current State](#9-migration-path-from-current-state)
10. [Edge Cases & Threat Model](#10-edge-cases--threat-model)

---

## 1. RNS Identity Primitives Available

Reticulum provides a rich identity layer that styrened can build RBAC directly on. Understanding these primitives is critical — they determine what's possible without inventing new crypto.

### 1.1 Identity Fundamentals

- **512-bit ECC keysets** (Curve25519 + Ed25519) — each node has a unique identity
- **Identity hash**: 128-bit truncated hash of the public key, used as the universal identifier
- **`RNS.Identity.recall(hash)`**: retrieve a previously-seen identity's public key from local storage
- **`RNS.Identity.sign(data)` / `validate(signature, data)`**: Ed25519 sign/verify

### 1.2 Link-Level Identity Verification

RNS Links provide built-in authenticated channels:

```python
# Initiator side: prove identity to remote
link.identify(my_identity)

# Responder side: check who connected
link.get_remote_identity()  # Returns Identity or None

# Callback when identification completes
link.set_remote_identified_callback(callback)
# callback(link, identity) — called with the verified Identity object
```

**Key insight**: `Link.identify()` sends `link_id + public_key` signed by the identity's private key. The responder verifies the signature cryptographically. This is **not** trust-on-first-use — it's a proper challenge-response. The identity is only revealed to the remote peer (not broadcast), preserving initiator anonymity until they choose to identify.

### 1.3 Request Handler Access Control

RNS `Destination.register_request_handler()` has built-in access control:

```python
destination.register_request_handler(
    "/path",
    response_generator=handler,
    allow=RNS.Destination.ALLOW_LIST,     # ALLOW_ALL | ALLOW_NONE | ALLOW_LIST
    allowed_list=[identity_hash_bytes, ...]  # bytes, not hex strings
)
```

**`ALLOW_LIST`** requires the link initiator to have called `link.identify()` with an identity whose hash is in the `allowed_list`. If they haven't identified, or their identity isn't in the list, the request is silently dropped by RNS itself — no application code needed.

**This is a free enforcement point** that styrened's DirectLink handlers currently bypass by using `ALLOW_ALL`.

### 1.4 LXMF Source Authentication

LXMF messages carry `source_hash` — the identity hash of the sender. LXMF ensures this is cryptographically authenticated (the message is signed by the source identity). This is the identity used for RPC and chat authorization checks.

### 1.5 What RNS Does NOT Provide

- **No role/group abstraction** — identity hashes only, flat namespace
- **No capability delegation** — no built-in way to say "A grants B the right to do X"
- **No certificate chains** — no hierarchical trust
- **No revocation protocol** — revocation is local (remove from allowed_list)
- **No identity metadata** — names/labels are application-layer

**Implication**: RBAC must be implemented entirely at the application layer. RNS gives us authenticated identities and access-controlled request handlers. We build roles and capabilities on top.

---

## 2. Prior Art Survey

### 2.1 rnsh (Reticulum Shell)

The closest prior art. `rnsh` implements identity-based authorization identically to styrened's current pattern:
- Flat list of allowed identity hashes
- `--allowed` CLI flag or identity file
- No roles, no granularity
- All-or-nothing: authorized = full shell access

**Lesson**: This pattern works for single-purpose tools. It fails for multi-capability systems like styrened.

### 2.2 RNS Remote Management

Reticulum's built-in `rnstatus`/`rnpath` remote management uses:
- `enable_remote_management = yes` in config
- `remote_management_allowed` list of identity hashes

Same pattern: flat identity list, binary access. But note the separate config key (`enable_remote_management`) that gates the entire capability — a primitive form of capability gating.

### 2.3 Object Capability (OCAP) Model

The OCAP model, as implemented in systems like Spritely Goblins and ZCAP-LD, represents capabilities as unforgeable tokens:

- **Capability = reference + authority** — possession of the token IS authorization
- **Delegation**: capability holders can create attenuated sub-capabilities
- **Revocation**: capabilities can be revoked by the granter
- **No ambient authority**: you can only do what your capabilities allow

**ZCAP-LD** (W3C CCG spec) implements this via signed JSON-LD documents with delegation chains:
```json
{
  "id": "urn:uuid:...",
  "parentCapability": "https://node/caps/admin",
  "controller": "did:key:...",
  "caveat": [{"type": "ValidUntil", "date": "2026-04-01"}],
  "proof": { "type": "Ed25519Signature2020", ... }
}
```

**Evaluation for Styrene**:
- ✅ Elegant delegation model (hub admin delegates monitor role to bot)
- ✅ Offline-verifiable (signed tokens)
- ❌ **Overkill for current fleet sizes** (< 100 nodes)
- ❌ Requires token storage and distribution infrastructure
- ❌ Revocation in a mesh is hard (how does node C know hub revoked B's token?)
- ❌ JSON-LD + linked data stack is heavyweight for embedded devices

**Verdict**: Interesting for v2+, but premature. The mesh doesn't yet have enough nodes to need delegation chains. **Adopt the mental model, not the protocol.**

### 2.4 SPIFFE/SPIRE (Workload Identity)

Cloud-native mutual authentication via short-lived X.509 SVIDs:
- Centralized identity server (SPIRE) attests workloads
- Identities are URIs: `spiffe://trust-domain/workload-id`
- Mutual TLS between services
- Policy enforcement via OPA or similar

**Evaluation for Styrene**:
- ❌ Requires centralized trust authority — antithetical to Reticulum's design
- ❌ X.509 certificate infrastructure is heavyweight
- ❌ Designed for datacenter, not mesh/LoRa
- ✅ The URI-based identity naming is worth borrowing

**Verdict**: Wrong paradigm entirely. Styrene operates in disconnected, decentralized mesh where a central SPIRE server is unreachable.

### 2.5 Capability-Based IoT Systems (CapBAC, IACAC)

Academic research on lightweight capability tokens for IoT:
- **CapBAC**: Capability token = JSON with {subject, resource, action, conditions, signature}
- **IACAC**: Identity Authentication + Capability Access Control — two-phase
- Common pattern: token is small enough for constrained devices, signed by issuer

**Evaluation for Styrene**:
- ✅ Lightweight, fits resource-constrained edge devices
- ✅ Token-based, works offline
- ❌ Still needs token distribution mechanism
- ❌ Single-issuer model doesn't map well to peer-to-peer

**Verdict**: Useful mental model. The "token = {identity, capabilities, signature}" pattern can be simplified to "config entry = {identity, role}" for v1.

### 2.6 BATMAN-ADV / Mesh Network Access Control

Relevant because styrened integrates BATMAN-ADV:
- BATMAN itself has **no access control** — L2 mesh is open
- WPA3-SAE (Simultaneous Authentication of Equals) handles auth at Wi-Fi layer
- Network-level access control is orthogonal to application-level RBAC

**Lesson**: Don't conflate L2 mesh access with application authorization. A node on the mesh can still be blocked at the styrened application layer.

---

## 3. Architecture Options Evaluated

### Option A: Flat Identity Lists (Current Model, Extended)

```yaml
rpc:
  authorized_identities: [hash1, hash2]
terminal:
  authorized_identities: [hash1]
datalink:
  authorized_identities: [hash1, hash2, hash3]
vpn:
  authorized_identities: [hash1]
```

**Pros**: Simple, already understood, minimal code change  
**Cons**: Identity duplication across sections, no grouping, N lists to maintain, no relationship between permissions  
**Verdict**: ❌ This is what we have. It doesn't scale.

### Option B: Pure RBAC (Role → Permission Matrix)

```yaml
rbac:
  roles:
    admin: [rpc.*, terminal.*, vpn.*, datalink.*]
    operator: [rpc.status, rpc.config, terminal.restricted]
    monitor: [rpc.status, rpc.ping, datalink.status]
    peer: [chat, page_browse, datalink.ping]
  assignments:
    hash1: admin
    hash2: operator
```

**Pros**: Clean separation, single roster, extensible  
**Cons**: Custom permission syntax, potential for overly complex role definitions, no delegation  
**Verdict**: ⚠️ Good but potentially over-engineered for current needs

### Option C: Hybrid Role + Capability (Recommended)

```yaml
rbac:
  default_role: peer
  roster:
    hash1: {role: admin}
    hash2: {role: operator}
    hash3: {role: peer, grants: [vpn]}  # peer + specific capability
  blocked: [ca3e9813]
```

**Pros**: Roles cover 90% of cases simply, explicit capability grants handle edge cases (e.g., VPN_PEER), single roster, backward-compatible  
**Cons**: Slightly more complex than pure RBAC  
**Verdict**: ✅ **Recommended.** Simple roles for common cases, capability grants for exceptions.

### Option D: OCAP / Capability Tokens

```python
# Node A creates a capability token for Node B
token = CapabilityToken(
    subject=hash_B,
    capabilities=[Capability.TERMINAL, Capability.VPN],
    issued_by=hash_A,
    expires=datetime(2026, 6, 1),
    signature=identity_A.sign(...)
)
# Token transmitted over LXMF or Link
```

**Pros**: Most flexible, supports delegation, offline-verifiable  
**Cons**: Token storage, distribution, revocation complexity, overkill for < 100 nodes  
**Verdict**: ❌ for v1. Consider for v2 when federation becomes real.

---

## 4. Recommended Architecture: Hybrid Capability-Role Model

### 4.1 Core Design Principles

1. **Single roster**: One place to define {identity → role + grants}
2. **Fail-closed default**: Unknown identities get `default_role`, which defaults to a safe value per profile
3. **RNS-native enforcement**: Use `ALLOW_LIST` on request handlers where possible (zero-cost enforcement)
4. **Layered enforcement**: LXMF (message-level) → Link (connection-level) → Request handler (path-level)
5. **Config-driven**: Roles defined in `core-config.yaml`, not code
6. **No new crypto**: Build entirely on RNS Ed25519 identity + signatures

### 4.2 Role Hierarchy

```
ADMIN (40)          ← Full control, unrestricted
  OPERATOR (30)     ← Fleet management, restricted terminal
    MONITOR (20)    ← Read-only queries and dashboards
      PEER (10)     ← Mesh peer, chat, page browse
        NONE (1)    ← No access (fail-closed default for ENDPOINT profile)
BLOCKED (0)         ← Explicit deny, all messages dropped

VPN (orthogonal)    ← Grant flag, not a role level
```

Roles are **hierarchical**: ADMIN includes all OPERATOR capabilities, which includes all MONITOR capabilities, etc.

VPN is an **orthogonal grant** — it doesn't fit the linear hierarchy. An ADMIN always has VPN. A PEER may or may not, depending on explicit grant.

### 4.3 Capability Set

```python
class Capability(Enum):
    # Tier: PEER (10)
    CHAT_SEND           = "chat.send"
    CHAT_RECEIVE        = "chat.receive"
    PAGE_BROWSE         = "page.browse"
    ANNOUNCE_RECEIVE    = "announce.receive"  # see announces from this node
    PING                = "rpc.ping"
    STATUS_QUERY        = "rpc.status"

    # Tier: MONITOR (20)
    WEB_READ            = "web.read"
    DATALINK_ESTABLISH  = "datalink.establish"
    DATALINK_STATUS     = "datalink.status"
    DATALINK_SPEEDTEST  = "datalink.speedtest"

    # Tier: OPERATOR (30)
    CONFIG_UPDATE       = "rpc.config_update"
    TERMINAL_RESTRICTED = "terminal.restricted"
    WEB_WRITE           = "web.write"

    # Tier: ADMIN (40)
    EXEC                = "rpc.exec"
    REBOOT              = "rpc.reboot"
    SELF_UPDATE         = "rpc.self_update"
    TERMINAL_FULL       = "terminal.full"

    # Orthogonal grants
    VPN_HANDSHAKE       = "vpn.handshake"
```

### 4.4 Resolution Logic

```python
def resolve(identity_hash: str) -> tuple[Role, set[Capability]]:
    # 1. Check blocked list (prefix matching)
    if is_blocked(identity_hash):
        return (Role.BLOCKED, set())

    # 2. Check explicit roster
    entry = roster.get(identity_hash)
    if entry:
        caps = ROLE_CAPABILITIES[entry.role]
        caps |= entry.grants  # add explicit grants
        return (entry.role, caps)

    # 3. Fall back to default role
    return (default_role, ROLE_CAPABILITIES[default_role])
```

---

## 5. Data Model Design

### 5.1 Core Types (`src/styrened/models/rbac.py`)

```python
"""Role-based access control model for Styrene identity authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import ClassVar


class Role(IntEnum):
    """Hierarchical role levels. Higher value = more privilege."""
    BLOCKED = 0
    NONE = 1
    PEER = 10
    MONITOR = 20
    OPERATOR = 30
    ADMIN = 40


class Capability(str, Enum):
    """Fine-grained capabilities. String values for config readability."""
    # PEER tier
    CHAT_SEND = "chat.send"
    CHAT_RECEIVE = "chat.receive"
    PAGE_BROWSE = "page.browse"
    PING = "rpc.ping"
    STATUS_QUERY = "rpc.status"

    # MONITOR tier
    WEB_READ = "web.read"
    DATALINK_ESTABLISH = "datalink.establish"
    DATALINK_STATUS = "datalink.status"
    DATALINK_SPEEDTEST = "datalink.speedtest"

    # OPERATOR tier
    CONFIG_UPDATE = "rpc.config_update"
    TERMINAL_RESTRICTED = "terminal.restricted"
    WEB_WRITE = "web.write"

    # ADMIN tier
    EXEC = "rpc.exec"
    REBOOT = "rpc.reboot"
    SELF_UPDATE = "rpc.self_update"
    TERMINAL_FULL = "terminal.full"

    # Orthogonal
    VPN_HANDSHAKE = "vpn.handshake"


# Role → capabilities mapping (cumulative)
_PEER_CAPS: frozenset[Capability] = frozenset({
    Capability.CHAT_SEND, Capability.CHAT_RECEIVE,
    Capability.PAGE_BROWSE, Capability.PING, Capability.STATUS_QUERY,
})

_MONITOR_CAPS: frozenset[Capability] = _PEER_CAPS | frozenset({
    Capability.WEB_READ, Capability.DATALINK_ESTABLISH,
    Capability.DATALINK_STATUS, Capability.DATALINK_SPEEDTEST,
})

_OPERATOR_CAPS: frozenset[Capability] = _MONITOR_CAPS | frozenset({
    Capability.CONFIG_UPDATE, Capability.TERMINAL_RESTRICTED,
    Capability.WEB_WRITE,
})

_ADMIN_CAPS: frozenset[Capability] = _OPERATOR_CAPS | frozenset({
    Capability.EXEC, Capability.REBOOT, Capability.SELF_UPDATE,
    Capability.TERMINAL_FULL, Capability.VPN_HANDSHAKE,
})

ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.BLOCKED: frozenset(),
    Role.NONE: frozenset(),
    Role.PEER: _PEER_CAPS,
    Role.MONITOR: _MONITOR_CAPS,
    Role.OPERATOR: _OPERATOR_CAPS,
    Role.ADMIN: _ADMIN_CAPS,
}


@dataclass(frozen=True)
class RosterEntry:
    """A single identity's role assignment."""
    identity_hash: str
    role: Role
    label: str = ""
    grants: frozenset[Capability] = field(default_factory=frozenset)

    @property
    def effective_capabilities(self) -> frozenset[Capability]:
        """All capabilities: role-derived + explicit grants."""
        return ROLE_CAPABILITIES[self.role] | self.grants


@dataclass
class RBACPolicy:
    """Central authorization policy for a styrened instance.

    Thread-safe: resolve_role() and has_capability() are read-only after init.
    Mutations (add/remove roster entries) should use a lock externally.
    """
    default_role: Role = Role.PEER
    roster: dict[str, RosterEntry] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)

    # Cached set of identity hashes with specific capabilities, for RNS ALLOW_LIST
    _allow_list_cache: dict[Capability, list[bytes]] = field(
        default_factory=dict, repr=False
    )

    def resolve_role(self, identity_hash: str) -> Role:
        """Resolve the effective role for an identity."""
        for prefix in self.blocked:
            if identity_hash.startswith(prefix) or prefix.startswith(identity_hash):
                return Role.BLOCKED
        entry = self.roster.get(identity_hash)
        if entry:
            return entry.role
        return self.default_role

    def has_capability(self, identity_hash: str, cap: Capability) -> bool:
        """Check if an identity has a specific capability."""
        role = self.resolve_role(identity_hash)
        if role == Role.BLOCKED:
            return False
        # Check role capabilities
        if cap in ROLE_CAPABILITIES[role]:
            return True
        # Check explicit grants
        entry = self.roster.get(identity_hash)
        if entry and cap in entry.grants:
            return True
        # Check default role capabilities (for unrostered identities)
        if identity_hash not in self.roster:
            return cap in ROLE_CAPABILITIES[self.default_role]
        return False

    def get_allow_list(self, cap: Capability) -> list[bytes]:
        """Get RNS-format allowed_list (bytes) for a capability.

        Returns list of identity hashes (as bytes) that hold the given
        capability. Used with RNS.Destination.register_request_handler(
            allow=ALLOW_LIST, allowed_list=result
        ).

        Note: This only includes explicitly rostered identities.
        If default_role grants the capability, use ALLOW_ALL instead.
        """
        if cap in self._allow_list_cache:
            return self._allow_list_cache[cap]

        result: list[bytes] = []
        for entry in self.roster.values():
            if cap in entry.effective_capabilities:
                result.append(bytes.fromhex(entry.identity_hash))
        self._allow_list_cache[cap] = result
        return result

    def invalidate_cache(self) -> None:
        """Clear allow list caches after roster mutation."""
        self._allow_list_cache.clear()

    def should_use_allow_all(self, cap: Capability) -> bool:
        """Check if default_role grants this capability.

        If True, request handlers should use ALLOW_ALL instead of ALLOW_LIST,
        because unidentified peers would also have access.
        """
        return cap in ROLE_CAPABILITIES[self.default_role]
```

### 5.2 Why Not SQLite for Roles?

The blocklist is in SQLite (contacts table). Should roles go there too?

**No.** Reasons:

1. **Config is source of truth**: Roles are declarative policy. They belong in `core-config.yaml`, versioned in git, deployed via ArgoCD. SQLite is runtime state.
2. **Restart resilience**: Config survives container restarts without PVCs. SQLite needs persistent storage.
3. **Auditability**: `git diff` on config shows policy changes. SQLite diffs are opaque.
4. **ArgoCD**: Hub deployments use ArgoCD → configmap. SQLite can't be managed this way.

The blocked list should **also** move to config-only (it's already in `banned_peers`). The `contacts.blocked` SQLite column becomes a cache/mirror, not the source of truth.

**Exception**: Runtime IPC mutations (block/unblock from TUI) should write to config file AND update in-memory policy. This is the same pattern as the Settings screen's config save flow.

---

## 6. Enforcement Point Design

### 6.1 Enforcement Architecture

```
┌─────────────────────────────────────────────────┐
│                   Daemon                         │
│                                                  │
│  ┌────────────┐                                  │
│  │ RBACPolicy │◄─── loaded from core-config.yaml │
│  └──────┬─────┘                                  │
│         │                                        │
│    ┌────┴─────────────────┐                      │
│    │    has_capability()  │                       │
│    └────┬────┬────┬───┬──┘                       │
│         │    │    │   │                           │
│    ┌────▼┐ ┌─▼──┐│ ┌─▼──────┐  ┌──────────────┐│
│    │ RPC │ │Term││ │DataLink │  │ LXMF Router  ││
│    │ Srv │ │Svc ││ │  Svc   │  │ (blocklist)  ││
│    └─────┘ └────┘│ └────────┘  └──────────────┘│
│                  │                               │
│              ┌───▼────┐  ┌──────────┐           │
│              │Web API │  │ Mesh VPN │           │
│              │  Auth  │  │   Svc    │           │
│              └────────┘  └──────────┘           │
└─────────────────────────────────────────────────┘
```

### 6.2 Per-Subsystem Integration

#### RPC Server (`rpc/server.py`)

**Current**: `_is_authorized(source_hash)` → checks flat `authorized_identities` set  
**New**: Replace with capability check per command type

```python
# In _protocol_handler():
# Replace binary authorized/not-authorized with per-capability check
COMMAND_CAPABILITIES: dict[StyreneMessageType, Capability] = {
    StyreneMessageType.PING: Capability.PING,
    StyreneMessageType.STATUS_REQUEST: Capability.STATUS_QUERY,
    StyreneMessageType.EXEC: Capability.EXEC,
    StyreneMessageType.REBOOT: Capability.REBOOT,
    StyreneMessageType.CONFIG_UPDATE: Capability.CONFIG_UPDATE,
    StyreneMessageType.SELF_UPDATE: Capability.SELF_UPDATE,
}

required_cap = COMMAND_CAPABILITIES.get(msg_type)
if required_cap and not self._rbac.has_capability(source_hash, required_cap):
    # reject
    ...
```

This eliminates both `authorized_identities` AND `enable_dangerous_commands` — they're subsumed by the capability model. An identity with role=OPERATOR can do CONFIG_UPDATE but not EXEC. No global toggle needed.

#### Terminal Service (`terminal/service.py`)

**Current**: `authorized_identities` set + `allow_unauthenticated` bool  
**New**: Check `TERMINAL_RESTRICTED` or `TERMINAL_FULL` capability

```python
# In session request handler:
if self._rbac.has_capability(source_hash, Capability.TERMINAL_FULL):
    shell = self.default_shell  # unrestricted
elif self._rbac.has_capability(source_hash, Capability.TERMINAL_RESTRICTED):
    shell = self._restricted_shell  # limited command set
else:
    # reject
    ...
```

This gives us per-identity shell restrictions without per-identity config — it falls out of the role hierarchy naturally.

#### DirectLink Service (`services/direct_link.py` + `daemon.py`)

**Current**: `ALLOW_ALL` on all request handlers  
**New**: Use RNS-native `ALLOW_LIST` for privileged handlers, capability check for link acceptance

```python
# In daemon._setup_datalink_destination():
if self._rbac.should_use_allow_all(Capability.DATALINK_STATUS):
    allow = RNS.Destination.ALLOW_ALL
    allowed_list = None
else:
    allow = RNS.Destination.ALLOW_LIST
    allowed_list = self._rbac.get_allow_list(Capability.DATALINK_STATUS)

self._datalink_destination.register_request_handler(
    "/status",
    response_generator=self._serve_datalink_status,
    allow=allow,
    allowed_list=allowed_list,
)

# /speedtest requires MONITOR+
self._datalink_destination.register_request_handler(
    "/speedtest",
    response_generator=self._serve_datalink_speedtest,
    allow=RNS.Destination.ALLOW_LIST,
    allowed_list=self._rbac.get_allow_list(Capability.DATALINK_SPEEDTEST),
)
```

**Important**: When `default_role >= PEER` and PEER includes `DATALINK_ESTABLISH`, link acceptance should remain open (the link itself is fine — it's the request handlers that gate specific actions). When `default_role == NONE`, the destination should reject unknown links entirely.

For link acceptance gating, use the `set_link_established_callback`:

```python
def _on_datalink_established(self, link):
    # Require identification for non-default-allowed connections
    link.set_remote_identified_callback(self._on_datalink_identified)

    # If default_role doesn't grant datalink, require identification
    if not self._rbac.should_use_allow_all(Capability.DATALINK_ESTABLISH):
        # Give peer 10 seconds to identify, then tear down
        asyncio.get_event_loop().call_later(
            10.0, self._check_link_identified, link
        )
```

#### VPN Handshake

**Current**: No auth  
**New**: VPN handshake (whether over LXMF or Link request) checks `VPN_HANDSHAKE` capability

```python
# In VPN handshake handler:
if not self._rbac.has_capability(source_hash, Capability.VPN_HANDSHAKE):
    logger.warning(f"[RBAC] VPN handshake rejected from {source_hash[:16]}...")
    return None  # RNS returns no response → timeout on requester
```

#### Web API Auth (`web/auth.py`)

**Current**: `WebAuthConfig.authorized_identities` + `public_mode`  
**New**: After challenge-response verification, check role for route access

```python
# In route middleware:
if request.method in ("POST", "PUT", "DELETE", "PATCH"):
    if not rbac.has_capability(identity_hash, Capability.WEB_WRITE):
        return JSONResponse({"error": "Insufficient privileges"}, 403)
else:
    if not rbac.has_capability(identity_hash, Capability.WEB_READ):
        return JSONResponse({"error": "Not authorized"}, 403)
```

`public_mode` becomes `default_role: monitor` — any authenticated identity gets read access.

#### LXMF Message Receipt (`services/lxmf_service.py`)

**Current**: `_is_blocked()` check on receive  
**New**: Replace with `has_capability(source_hash, Capability.CHAT_RECEIVE)`

Wait — this needs careful thought. The LXMF blocklist currently operates as a deny-list (block specific identities). The RBAC model introduces an allow-list dimension (only PEER+ can send chat). These compose:

```python
def _should_accept_message(self, source_hash: str) -> bool:
    """Check if an incoming message should be accepted."""
    # RBAC check replaces both blocklist and (future) allow-list
    return self._rbac.has_capability(source_hash, Capability.CHAT_RECEIVE)
```

When `default_role = PEER`, all unblocked identities can send chat (current behavior).  
When `default_role = NONE`, only rostered identities can send chat (new capability).

### 6.3 Enforcement Hierarchy (Defense in Depth)

Multiple layers, each independently enforceable:

```
Layer 1: RNS Transport
  └─ ALLOW_LIST on request handlers (RNS-native, zero application code)

Layer 2: LXMF Protocol
  └─ _is_blocked() / has_capability() on message receipt (drops before parsing)

Layer 3: Application (RPC/Terminal/Web)
  └─ has_capability() per-command/per-route (fine-grained)
```

If any layer rejects, the request fails. Compromising one layer doesn't bypass the others.

---

## 7. Configuration Schema

### 7.1 Proposed `core-config.yaml` Addition

```yaml
# Role-Based Access Control
rbac:
  # Role assigned to identities not in the roster.
  # Options: none, peer, monitor, operator, admin
  # Recommended defaults by profile:
  #   operator (personal node): peer
  #   endpoint (edge device):   none
  #   hub (public transport):   peer
  default_role: peer

  # Identity → role assignments
  roster:
    # Full identity hash (32 hex chars) → role
    - identity: "abc123def456789012345678abcdef01"
      role: admin
      label: "cwilson macbook"  # optional, for human reference

    - identity: "def456789012345678abcdef01234567"
      role: operator
      label: "monitoring bot"

    # Peer with VPN grant (peer capabilities + VPN handshake)
    - identity: "789012345678abcdef01234567890123"
      role: peer
      label: "edge-pi-01"
      grants:
        - vpn.handshake

  # Blocked identities — overrides any role assignment
  # Supports prefix matching (short hashes match full hashes)
  blocked:
    - "ca3e9813"  # spammer
    - "deadbeef12345678"
```

### 7.2 Parsing (`services/config.py`)

```python
def _parse_rbac(data: dict) -> RBACPolicy:
    """Parse rbac section from config dict."""
    rbac = data.get("rbac", {})

    default_role_str = rbac.get("default_role", "peer")
    default_role = Role[default_role_str.upper()]

    roster: dict[str, RosterEntry] = {}
    for entry_data in rbac.get("roster", []):
        identity = entry_data["identity"].lower()
        role = Role[entry_data["role"].upper()]
        label = entry_data.get("label", "")
        grants_raw = entry_data.get("grants", [])
        grants = frozenset(Capability(g) for g in grants_raw)
        roster[identity] = RosterEntry(
            identity_hash=identity, role=role, label=label, grants=grants
        )

    blocked = [str(h).lower() for h in rbac.get("blocked", [])]

    return RBACPolicy(default_role=default_role, roster=roster, blocked=blocked)
```

### 7.3 Legacy Compatibility

During migration, parse old fields and map them:

```python
def _migrate_legacy_auth(config: CoreConfig, rbac: RBACPolicy) -> RBACPolicy:
    """Map legacy authorized_identities to RBAC roster entries."""
    # terminal.authorized_identities → admin role
    for hash_hex in config.terminal.authorized_identities:
        if hash_hex not in rbac.roster:
            rbac.roster[hash_hex] = RosterEntry(
                identity_hash=hash_hex, role=Role.ADMIN,
                label="(migrated from terminal.authorized_identities)"
            )
            logger.warning(
                f"[RBAC] Migrated terminal identity {hash_hex[:16]}... to admin role. "
                f"Move to rbac.roster in config to silence this warning."
            )

    # web API authorized_identities → monitor role (at minimum)
    for hash_hex in config.api.auth.authorized_identities:
        if hash_hex not in rbac.roster:
            rbac.roster[hash_hex] = RosterEntry(
                identity_hash=hash_hex, role=Role.MONITOR,
                label="(migrated from api.auth.authorized_identities)"
            )

    # banned_peers → blocked
    for prefix in config.banned_peers:
        if prefix not in rbac.blocked:
            rbac.blocked.append(prefix)

    # enable_dangerous_commands=False → cap out at OPERATOR for all
    # (This is trickier — it's a global toggle, not per-identity)
    # For migration: if dangerous commands disabled, ADMIN role still exists
    # but EXEC/REBOOT/SELF_UPDATE caps are removed from ADMIN.
    # This preserves the safety semantics of the old toggle.

    return rbac
```

### 7.4 Config Serialization

```python
def _serialize_rbac(policy: RBACPolicy) -> dict:
    """Serialize RBACPolicy to config dict."""
    roster_list = []
    for entry in sorted(policy.roster.values(), key=lambda e: e.identity_hash):
        d = {"identity": entry.identity_hash, "role": entry.role.name.lower()}
        if entry.label:
            d["label"] = entry.label
        if entry.grants:
            d["grants"] = sorted(g.value for g in entry.grants)
        roster_list.append(d)

    return {
        "default_role": policy.default_role.name.lower(),
        "roster": roster_list,
        "blocked": policy.blocked,
    }
```

---

## 8. Wire Protocol Considerations

### 8.1 No Wire Protocol Changes Required

The RBAC model is **entirely local policy**. It doesn't change the Styrene wire protocol. Each node independently decides what capabilities to grant each identity. There's no need for:
- Capability tokens in messages
- Role negotiation handshakes
- Permission fields in the wire format

This is a critical advantage over OCAP/ZCAP-LD approaches — zero wire protocol impact.

### 8.2 Future: Capability Advertisement in Announces

In the future, a node could advertise its RBAC policy in announce data:
```python
app_data = {
    "name": "my-node",
    "version": "0.14.0",
    "rbac": {
        "default_role": "peer",
        "capabilities_available": ["chat", "pages", "datalink"]
    }
}
```

This allows clients to know before connecting what capabilities a node offers to default peers. **Not needed for v1** but the data model supports it.

### 8.3 IPC Commands for RBAC Management

New IPC commands for runtime management:

```python
class IPCMessageType(IntEnum):
    # ... existing ...
    CMD_RBAC_GET_POLICY    = 0x70  # Query current RBAC policy
    CMD_RBAC_SET_ROLE      = 0x71  # Set role for an identity
    CMD_RBAC_REMOVE_ENTRY  = 0x72  # Remove roster entry
    CMD_RBAC_BLOCK         = 0x73  # Block identity (replaces CMD_BLOCK_PEER)
    CMD_RBAC_UNBLOCK       = 0x74  # Unblock identity (replaces CMD_UNBLOCK_PEER)
    QUERY_RBAC_ROSTER      = 0x75  # List all roster entries
    QUERY_RBAC_CHECK       = 0x76  # Check capability for an identity
```

These subsume the existing `CMD_BLOCK_PEER` / `CMD_UNBLOCK_PEER` / `QUERY_BLOCKED_PEERS` commands. The old commands should be preserved as aliases during migration.

---

## 9. Migration Path from Current State

### Phase 1: Foundation (Non-Breaking) — ✅ COMPLETE (v0.14.3)

- [x] Create `src/styrened/models/rbac.py` with `Role`, `Capability`, `RBACPolicy`, `RosterEntry`
- [x] Add `rbac` section parsing to `services/config.py`
- [x] Add `RBACPolicy` field to `CoreConfig`
- [x] Instantiate `RBACPolicy` on daemon, inject into services
- [x] Write unit tests (~60 tests covering resolution, capabilities, grants, hierarchy, config, serialization)
- [x] **No behavioral changes** — all existing auth paths untouched

**Implementation note:** `Capability` uses `ClassVar[str]` constants (not `str, Enum`) for YAML config readability. `RosterEntry` supports per-identity `grants: frozenset[str]` for orthogonal capabilities.

### Phase 2: RPC + LXMF Integration (Behavioral) — ✅ COMPLETE (v0.14.6)

- [x] Replace `RPCServer._is_authorized()` with `rbac.has_capability(source, cap)`
- [x] Map each `StyreneMessageType` to a `Capability` via `MESSAGE_TYPE_CAPABILITY` dict
- [x] Fix fail-open vulnerability: empty whitelist now denies when RBAC active
- [x] Replace `lxmf_service._is_blocked()` with `rbac.resolve_role()==BLOCKED`
- [x] Dual-write: `block_peer()`/`unblock_peer()` write to both contacts DB and RBAC
- [x] `_seed_contacts_blocks_to_rbac()` loads runtime blocks into RBAC on startup
- [x] Added `INBOX_READ` capability at MONITOR tier
- [x] 61 RBAC tests across `test_rpc_rbac.py` and `test_lxmf_rbac.py`

**Implementation note:** `enable_dangerous_commands` NOT removed yet — preserved for legacy fallback. Removal deferred to Phase 5.

### Phase 3: DirectLink ALLOW_LIST Enforcement — ✅ COMPLETE (v0.14.7)

- [x] Switch all 5 datalink request handlers from `ALLOW_ALL` to capability-gated `ALLOW_LIST`
- [x] Added `DATALINK_PING`, `DATALINK_META`, `DATALINK_INFO` capabilities at PEER tier
- [x] Moved `DATALINK_STATUS` from MONITOR to PEER tier (app-layer gates full data to MONITOR+)
- [x] `DATALINK_HANDLER_CAPABILITY` dict, `_datalink_allow_mode()`, `_reregister_datalink_handlers()`
- [x] App-layer RBAC gates on all 5 handlers (defense-in-depth)
- [x] `get_allow_list()` cache invalidation via `invalidate_cache()` on roster mutations
- [x] 39 tests via strict TDD in `test_datalink_rbac.py`
- [ ] Link identification timeout for `default_role=NONE` — deferred (not critical with app-layer gates)
- [ ] VPN handshake gating — deferred (VPN handshake now uses LXMF, gated by Phase 2 RBAC)

### Phase 4: Terminal + Web API — ✅ COMPLETE (v0.14.7)

- [x] `TerminalService.is_authorized()` checks `TERMINAL_RESTRICTED`/`TERMINAL_FULL` via RBAC
- [x] `TerminalService.authorization_level()` returns "full", "restricted", or None
- [x] `TerminalService.set_rbac_policy()` for runtime policy injection
- [x] Web API `challenge()` checks `WEB_READ` via RBAC
- [x] Web API `verify()` re-checks RBAC before issuing session (TOCTOU fix)
- [x] `AuthMiddleware` gates POST/PUT/PATCH/DELETE on `WEB_WRITE` capability
- [x] Legacy fallback preserved when `rbac_policy=None` across all surfaces
- [x] 23 terminal RBAC tests + 16 web auth RBAC tests
- [ ] IPC commands `CMD_RBAC_*` (0x70-0x76) — deferred to Phase 5 or later
- [ ] TUI RBAC management screen — deferred to Phase 5 or later
- [ ] Map `public_mode` to `default_role: monitor` — deferred to Phase 5

### Phase 5: Cleanup + Legacy Removal — ⬜ PLANNED (v0.15.0)

**Scope:** Remove all legacy config fields and dual-path auth code.

Config fields to remove:
- [ ] `RPCConfig.authorized_identities` / `authorized_identities_file` (`models/config.py`)
- [ ] `RPCConfig.enable_dangerous_commands` (`models/config.py`)
- [ ] `TerminalConfig.authorized_identities` / `authorized_identities_file` (`models/config.py`)
- [ ] `TerminalConfig.allow_unauthenticated` (`models/config.py`)
- [ ] `WebAuthConfig.authorized_identities` (`models/config.py`)
- [ ] `WebAuthConfig.allow_unauthenticated` (`models/config.py`)
- [ ] `CoreConfig.banned_peers` (`models/config.py`)

Code to simplify (remove `if rbac is None` legacy branches):
- [ ] `RPCServer._is_authorized()` — remove legacy whitelist path
- [ ] `LXMFService._is_blocked()` — remove contacts.blocked fallback
- [ ] `TerminalService.is_authorized()` — remove `authorized_identities` + `allow_unauthenticated` path
- [ ] `web/auth.py challenge()` — remove legacy `authorized_identities` path
- [ ] `web/auth.py verify()` — RBAC check becomes unconditional
- [ ] `web/auth_middleware.py` — WEB_WRITE check becomes unconditional
- [ ] `daemon.py _datalink_allow_mode()` — remove `rbac is None` → ALLOW_ALL fallback
- [ ] `daemon.py _datalink_rbac_role()` — remove `rbac is None` → PEER fallback
- [ ] `daemon.py _serve_datalink_speedtest()` — remove `config.rbac is not None` conditional

Other cleanup:
- [ ] Remove `_seed_contacts_blocks_to_rbac()` — no longer needed when blocklist is RBAC-only
- [ ] Remove `_migrate_legacy_to_rbac()` config migration code
- [ ] Wire `set_rbac_policy()` into config reload path for terminal service
- [ ] Add deprecation warnings in a v0.14.x release before removal
- [ ] Migration guide documentation
- [ ] Update TUI settings screens (remove legacy auth fields)
- [ ] Bump to v0.15.0 (breaking config change)

---

## 10. Edge Cases & Threat Model

### 10.1 Edge Cases

**Self-authorization**: A node always has ADMIN over its own local IPC. RBAC only governs remote identities accessing the node over LXMF/Links. The local operator (via TUI/CLI/IPC socket) is implicitly ADMIN.

**Hub relay**: When a hub relays messages between peers, the hub's RBAC doesn't gate peer-to-peer messages — it only gates messages *addressed to the hub*. LXMF propagation is transport-layer, not application-layer.

**Identity rotation**: If an operator creates a new RNS identity, they need to update the roster on all nodes that authorize them. There's no identity continuity mechanism in RNS. This is a known limitation — not worse than the current `authorized_identities` model.

**Race on config reload**: If `core-config.yaml` is updated while the daemon is running, the RBAC policy needs to be reloaded. Current config reload mechanism (if any) should trigger `rbac.invalidate_cache()`.

**Prefix collision in blocked list**: A short blocked prefix (e.g., "ca") could inadvertently block legitimate identities. The current prefix-matching behavior is preserved — document the risk and recommend >= 8 chars.

### 10.2 Threat Model

| Threat | Mitigation |
|--------|------------|
| Attacker forges identity hash | Impossible — RNS identity is cryptographic (Ed25519), source_hash is verified by LXMF/Link signature |
| Attacker replays authorized request | RPC replay protection (existing), Link encryption provides session uniqueness |
| Compromised ADMIN identity | Revoke from roster + add to blocked list + restart daemon. No propagation needed (local policy). |
| Attacker brute-forces identity | 128-bit hash space — computationally infeasible |
| Insider adds themselves to config | Config file permissions (OS-level). ArgoCD-managed deployments require git commit. |
| Default role too permissive | Per-profile defaults: `ENDPOINT → NONE`, explicit opt-in for higher defaults |
| Capability escalation via VPN | VPN grant is orthogonal — having VPN doesn't grant ADMIN. BATMAN L2 access ≠ application auth. |

### 10.3 What This Does NOT Solve

- **Multi-node policy coordination**: Each node maintains its own RBAC policy independently. There's no "fleet-wide RBAC" — each node decides who can do what on that node. For fleet-wide policy, use config management (ArgoCD, Ansible, etc.) to push consistent configs.
- **Capability delegation**: An ADMIN cannot create a time-limited OPERATOR token for someone else without editing the config. This is a v2 concern.
- **Audit logging**: Who did what, when. This report doesn't cover audit trails, but the RBAC model provides the identity resolution needed for audit log entries.

---

## Appendix A: Comparison with Preliminary Report

| Preliminary Report Proposal | Deep Research Refinement |
|----------------------------|-------------------------|
| 6 roles (BLOCKED, PEER, VPN_PEER, MONITOR, OPERATOR, ADMIN) | 5 roles + 1 orthogonal grant (VPN as grant, not role) |
| Capability enum (plain Enum) | Capability as `str` enum (config-readable values like `"rpc.exec"`) |
| `RBACPolicy.has_capability()` | Same, plus `get_allow_list()` for RNS-native enforcement |
| Config: `roster: [{identity, role, label}]` | Same, plus `grants: [capability]` for orthogonal capabilities |
| Migration: 5 phases | Same 5 phases, with detailed per-phase scope and estimates |
| — | New: `should_use_allow_all()` for ALLOW_ALL vs ALLOW_LIST decision |
| — | New: Legacy field migration with deprecation warnings |
| — | New: IPC command family (0x70-0x76) for runtime management |
| — | New: Link identification timeout for fail-closed configurations |

## Appendix B: Test Plan Outline

```python
# tests/unit/test_rbac.py — targeting ~40 tests

# Role resolution
test_resolve_role_explicit_roster_entry()
test_resolve_role_default_when_not_in_roster()
test_resolve_role_blocked_overrides_roster()
test_resolve_role_blocked_prefix_matching()
test_resolve_role_blocked_short_prefix_warning()

# Capability checks
test_has_capability_admin_has_all()
test_has_capability_peer_lacks_exec()
test_has_capability_operator_has_config_update()
test_has_capability_none_has_nothing()
test_has_capability_blocked_has_nothing()
test_has_capability_with_explicit_grant()
test_has_capability_grant_on_peer_adds_vpn()

# Capability hierarchy
test_admin_includes_operator_caps()
test_operator_includes_monitor_caps()
test_monitor_includes_peer_caps()
test_peer_does_not_include_monitor_caps()

# Allow list generation
test_get_allow_list_returns_bytes()
test_get_allow_list_only_includes_capable_identities()
test_get_allow_list_cache_invalidation()
test_should_use_allow_all_when_default_role_grants()
test_should_use_allow_all_false_when_default_none()

# Config parsing
test_parse_rbac_minimal()
test_parse_rbac_full_roster()
test_parse_rbac_with_grants()
test_parse_rbac_missing_defaults_to_peer()
test_parse_rbac_case_insensitive_role_names()

# Legacy migration
test_migrate_terminal_authorized_to_admin()
test_migrate_web_authorized_to_monitor()
test_migrate_banned_peers_to_blocked()
test_migrate_no_duplicates()

# Serialization round-trip
test_serialize_deserialize_roundtrip()
test_serialize_sorts_roster_by_hash()

# Edge cases
test_empty_roster_uses_default_role()
test_empty_blocked_list()
test_identity_both_rostered_and_blocked_is_blocked()
```
