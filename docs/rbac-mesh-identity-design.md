# RBAC for Mesh Identity-Based Operations — Research & Design Assessment

**Status:** Research complete. Ready for implementation.  
**Date:** 2026-03-05  
**Context:** Follows `feat(discovery): default-deny mesh admission via allowlist policy` (commit `4d15edc`) and the TUI Security tab (commit `5d1f6a1`).

---

## 1. Problem Statement

Every identity-based operation in Styrene is currently guarded by a **separate, independent binary gate**.  A fleet manager's identity hash must be manually added to four different config sections to gain full access.  There is no shared notion of "this peer is trusted at level X."  The current model also leaves one inbound surface completely unguarded.

---

## 2. Current Enforcement Points (as-built)

Five subsystems each maintain their own identity list with binary admit/deny semantics:

| Subsystem | Config field | Gate type | What it guards |
|---|---|---|---|
| Discovery | `discovery.allowed_peers` | `set[str]` | Announce admission → device list |
| RPC server | *(passed at init)* `RPCServer._authorized_identities` | `set[str]` | Any non-PUBLIC RPC command |
| RPC dangerous | `rpc.allow_command_execution` | `bool` (global) | EXEC / REBOOT / CONFIG\_UPDATE / SELF\_UPDATE |
| Web API | `api.auth.authorized_identities` | `set[str]` | HTTP session issuance |
| Terminal | `terminal.authorized_identities` | `set[str]` | Remote shell sessions |

### RPC command classification (existing)

```
PUBLIC_RPC_COMMANDS    = { PING, STATUS_REQUEST }         # no auth required
DANGEROUS_RPC_COMMANDS = { EXEC, REBOOT, CONFIG_UPDATE, SELF_UPDATE }  # gated by enable_dangerous_commands
```

Everything between PUBLIC and DANGEROUS (currently nothing, but the slot exists in the dispatch table) is gated by `_authorized_identities`.

### Unguarded surface

`ChatProtocol.handle_message()` accepts any LXMF message from any source hash.  There is no identity check, no allowlist, no ban check.  This is the only inbound surface with zero access control.

### Problems

1. **Quadruple-entry burden.** Adding a trusted peer requires editing four config sections. Removing one requires finding all four.
2. **No differentiation within "authorized."** Once in `rpc._authorized_identities`, a peer can call any non-public RPC. There is no way to grant status queries without also granting exec capability (unless dangerous commands are globally disabled — which affects all peers).
3. **`banned_peers` is orthogonal to everything.** Lives on `CoreConfig` directly. Not consulted by terminal or web layers.
4. **Chat is uncontrolled.** Any node that can deliver an LXMF message can inject chat history and trigger auto-reply.
5. **No runtime management.** All lists are file-config-only; no IPC path to add/remove identities without a daemon restart.

---

## 3. Research: Access Control Model Selection

### NIST RBAC levels

| Level | Name | Description | Verdict for Styrene |
|---|---|---|---|
| 0 | Core RBAC | Users → Roles → Permissions, flat | **✓ Appropriate** |
| 1 | Hierarchical RBAC | Roles inherit from roles | Useful convention but not needed as a formal mechanism |
| 2 | Constrained RBAC | Mutually exclusive role sets, separation of duties | Overkill |
| 3 | Symmetric RBAC | Full constraint + cardinality limits | Enterprise-grade, not applicable |

**Selected: NIST Level 0 with cumulative-upward role ordering by convention.**  
The "hierarchy" is just an ordering of roles — each role grants all permissions of the level below it.  This is implemented as an integer comparison on a `dict[MeshRole, int]`, not a graph traversal.

### Why not ABAC?

Attribute-Based Access Control evaluates additional runtime attributes: location, time, device posture, department, risk score.  None of these attributes exist at Reticulum message delivery time.  The only attribute available is the identity hash — which is already a first-class principal.  ABAC would add policy-engine complexity with no additional discrimination power.

### Why not ReBAC (relationship-based)?

Relationship-based access control (used by Zanzibar/OpenFGA) is appropriate when permissions depend on graph relationships between resources — e.g. "Alice can edit the document because she owns the folder that contains it."  Styrene has no resource graph.  Operations are node-scoped, not resource-scoped.

### Why not delegated/capability-based?

A capability model would let an ADMIN node issue signed capability tokens to other nodes.  This is interesting for large autonomous mesh deployments but introduces token revocation, replay, and distribution complexity that is out of scope.  The mesh's decentralised nature is a feature here — **each node maintains its own policy; no remote node can grant itself a role.**

### RBAC in IoT/edge context (literature)

Research on RBAC for IoT networks (ResearchGate 2024, 2025) consistently recommends:

- Flat or shallow hierarchies for resource-constrained devices.
- Policy evaluation as a static lookup (pre-compiled permission sets), not a runtime engine.
- Local policy storage with no central authority dependency.
- Cryptographic identity (PKI / public key) as the principal — which Reticulum already provides.

All four recommendations align with the design below.

---

## 4. Proposed Role Set

Four roles, ordered `OBSERVER < MONITOR < OPERATOR < ADMIN`.  Each role cumulatively inherits all permissions of roles below it.

| Role | Typical persona | Principle |
|---|---|---|
| `OBSERVER` | Any admitted peer; anonymous node on open mesh | Lowest trust. Can exist on the mesh and exchange messages. |
| `MONITOR` | Read-only dashboard node; external alerting scraper | Trusted to query state but not mutate anything. |
| `OPERATOR` | Fleet manager's workstation | Trusted to run non-destructive commands and write config via API. |
| `ADMIN` | Local/physically-present admin node | Full control including destructive RPC and terminal shell. |

---

## 5. Permission Set

Twelve named permissions.  Each maps to one enforcement point.

| Permission | Minimum role | Subsystem | Notes |
|---|---|---|---|
| `mesh.announce` | OBSERVER | Discovery (`StyreneAnnounceHandler`) | Admitted to device list |
| `mesh.chat` | OBSERVER | `ChatProtocol.handle_message()` | **New gate — currently unguarded** |
| `rpc.ping` | *(public)* | RPCServer | PING stays public; still blocked for denied peers |
| `rpc.status` | MONITOR | RPCServer | STATUS\_REQUEST |
| `rpc.exec_safe` | OPERATOR | RPCServer EXEC handler | EXEC within `allowed_commands` allowlist |
| `rpc.exec_dangerous` | ADMIN | RPCServer DANGEROUS\_RPC | EXEC unrestricted |
| `rpc.reboot` | ADMIN | RPCServer REBOOT | |
| `rpc.config_update` | ADMIN | RPCServer CONFIG\_UPDATE | |
| `rpc.self_update` | ADMIN | RPCServer SELF\_UPDATE | |
| `web.read` | MONITOR | WebAuth middleware | HTTP GET endpoints |
| `web.write` | OPERATOR | WebAuth middleware | HTTP POST/PUT/DELETE endpoints |
| `terminal.connect` | ADMIN | `TerminalService` | Remote shell session |

### Role → permission matrix

| Permission | OBSERVER | MONITOR | OPERATOR | ADMIN |
|---|:---:|:---:|:---:|:---:|
| `mesh.announce` | ✓ | ✓ | ✓ | ✓ |
| `mesh.chat` | ✓ | ✓ | ✓ | ✓ |
| `rpc.ping` | ✓ | ✓ | ✓ | ✓ |
| `rpc.status` | | ✓ | ✓ | ✓ |
| `rpc.exec_safe` | | | ✓ | ✓ |
| `rpc.exec_dangerous` | | | | ✓ |
| `rpc.reboot` | | | | ✓ |
| `rpc.config_update` | | | | ✓ |
| `rpc.self_update` | | | | ✓ |
| `web.read` | | ✓ | ✓ | ✓ |
| `web.write` | | | ✓ | ✓ |
| `terminal.connect` | | | | ✓ |

---

## 6. Data Model Design

### New types in `models/config.py`

```python
class MeshRole(Enum):
    OBSERVER  = "observer"
    MONITOR   = "monitor"
    OPERATOR  = "operator"
    ADMIN     = "admin"

# Role ordering — used for "≥" comparisons only
_ROLE_ORDER: dict[MeshRole, int] = {
    MeshRole.OBSERVER:  0,
    MeshRole.MONITOR:   1,
    MeshRole.OPERATOR:  2,
    MeshRole.ADMIN:     3,
}

def role_gte(role: MeshRole, minimum: MeshRole) -> bool:
    """True if `role` grants at least the permissions of `minimum`."""
    return _ROLE_ORDER[role] >= _ROLE_ORDER[minimum]


@dataclass
class PeerPolicy:
    """Role assignment for a single identity on this node's policy."""
    identity_hash: str           # 32-char hex, lower-cased, validated on load
    role: MeshRole = MeshRole.OBSERVER
    label: str | None = None     # Human-readable; NEVER used for auth decisions


@dataclass
class MeshPolicyConfig:
    """Unified identity-to-role policy for all subsystems.

    Replaces the four independent authorized_identities sets and the
    top-level banned_peers list.

    Attributes:
        default_role: Role granted to any admitted peer whose identity hash
            is not in `peers`.  Only applies when discovery.access_mode is
            OPEN.  In ALLOWLIST mode, unlisted identities get no role (None).
        peers: Ordered list of per-identity role assignments.
        denied_peers: Identity hashes that are explicitly blocked regardless
            of any role assignment.  Evaluated before `peers`.  Supersedes
            the legacy CoreConfig.banned_peers.
    """
    default_role: MeshRole = MeshRole.OBSERVER
    peers: list[PeerPolicy] = field(default_factory=list)
    denied_peers: set[str] = field(default_factory=set)
```

Add `mesh_policy: MeshPolicyConfig` to `CoreConfig`.

### New service: `services/mesh_policy.py`

```python
# Permission → minimum role required
_PERMISSION_MINIMUM_ROLE: dict[str, MeshRole] = {
    "mesh.announce":      MeshRole.OBSERVER,
    "mesh.chat":          MeshRole.OBSERVER,
    "rpc.ping":           MeshRole.OBSERVER,   # effectively public; denied if in denied_peers
    "rpc.status":         MeshRole.MONITOR,
    "rpc.exec_safe":      MeshRole.OPERATOR,
    "rpc.exec_dangerous": MeshRole.ADMIN,
    "rpc.reboot":         MeshRole.ADMIN,
    "rpc.config_update":  MeshRole.ADMIN,
    "rpc.self_update":    MeshRole.ADMIN,
    "web.read":           MeshRole.MONITOR,
    "web.write":          MeshRole.OPERATOR,
    "terminal.connect":   MeshRole.ADMIN,
}


class MeshPolicy:
    """Compiled policy object constructed from MeshPolicyConfig at daemon start.

    Immutable after construction.  Thread-safe for concurrent read access.
    """

    def __init__(
        self,
        config: MeshPolicyConfig,
        access_mode: MeshAccessMode,
    ) -> None:
        self._denied: frozenset[str] = frozenset(h.lower() for h in config.denied_peers)
        self._peer_map: dict[str, MeshRole] = {
            p.identity_hash.lower(): p.role for p in config.peers
        }
        self._default_role: MeshRole = config.default_role
        self._access_mode: MeshAccessMode = access_mode

    def role_for(self, identity_hash: str) -> MeshRole | None:
        """Return the effective role for an identity, or None if blocked/not admitted."""
        h = identity_hash.lower()
        if h in self._denied:
            return None
        entry = self._peer_map.get(h)
        if entry is not None:
            return entry
        if self._access_mode == MeshAccessMode.OPEN:
            return self._default_role
        return None  # ALLOWLIST mode, identity not in peers list

    def has_permission(self, identity_hash: str, permission: str) -> bool:
        """True if the identity holds the role that grants `permission`."""
        role = self.role_for(identity_hash)
        if role is None:
            return False
        minimum = _PERMISSION_MINIMUM_ROLE.get(permission)
        if minimum is None:
            return False  # Unknown permission → deny
        return role_gte(role, minimum)
```

---

## 7. YAML Config Shape

```yaml
# ~/.config/styrene/core-config.yaml

discovery:
  access_mode: allowlist   # or "open"
  allowed_peers: []        # deprecated in favour of mesh_policy.peers;
                           # retained for backward compat during transition

mesh_policy:
  default_role: observer   # what open-mode unlisted peers receive

  denied_peers:            # replaces top-level banned_peers
    - deadbeefdeadbeefdeadbeef

  peers:
    - identity_hash: aabbccddeeff0011aabbccddeeff0011
      role: admin
      label: "My laptop"

    - identity_hash: 1122334455667788aabbccddeeff0011
      role: monitor
      label: "Grafana scraper"

    - identity_hash: ffeeddccbbaa9988776655443322aabb
      role: operator
      label: "Fleet manager node"
```

---

## 8. Enforcement Point Migration

Each subsystem's authorization check becomes a one-liner:

| Subsystem | Before | After |
|---|---|---|
| `StyreneAnnounceHandler.received_announce()` | `identity_hash in self._allowed_peers` | `policy.has_permission(identity_hash, "mesh.announce")` |
| `ChatProtocol.handle_message()` | *(no gate)* | `policy.has_permission(source_hash, "mesh.chat")` |
| `RPCServer._is_authorized()` | `source_hash in self._authorized_identities` | `policy.has_permission(source_hash, "rpc.status")` |
| RPCServer DANGEROUS gate | `self._enable_dangerous_commands` (bool, global) | `policy.has_permission(source_hash, "rpc.exec_dangerous")` |
| `WebAuth.create_auth_router()` | `identity_hash in auth_config.authorized_identities` | `policy.has_permission(identity_hash, "web.read")` (GET) / `"web.write"` (mutations) |
| `TerminalService._check_authorized()` | `identity_hash in terminal_config.authorized_identities` | `policy.has_permission(identity_hash, "terminal.connect")` |

The `MeshPolicy` instance is constructed once at daemon startup (`daemon.py`) and injected as a dependency alongside the existing config objects — the same pattern used for `RPCServer`, `TerminalService`, etc. today.

---

## 9. Migration Strategy (two phases)

### Phase 1 — Config consolidation (~1 day)

Goal: new config model lands; zero behaviour change for existing installs.

1. Add `MeshRole`, `PeerPolicy`, `MeshPolicyConfig` to `models/config.py`.
2. Parse and serialize `mesh_policy` section in `services/config.py`.
3. Implement `MeshPolicy` service in `services/mesh_policy.py`.
4. At config load time, populate the legacy per-subsystem `authorized_identities` from `MeshPolicyConfig` via a **compatibility shim**:

```python
# In load_core_config(), after parsing mesh_policy:
policy = MeshPolicy(config.mesh_policy, config.discovery.access_mode)
config.rpc._authorized_identities_derived = {
    p.identity_hash for p in config.mesh_policy.peers
    if role_gte(p.role, MeshRole.MONITOR)
}
config.api.auth.authorized_identities = {
    p.identity_hash for p in config.mesh_policy.peers
    if role_gte(p.role, MeshRole.MONITOR)
}
config.terminal.authorized_identities = {
    p.identity_hash for p in config.mesh_policy.peers
    if role_gte(p.role, MeshRole.ADMIN)
}
config.banned_peers = list(config.mesh_policy.denied_peers)
```

Subsystem code needs **zero changes** in Phase 1.  The compat shim makes `mesh_policy` the single source of truth without touching any enforcement code.

5. Update TUI Settings > Security tab: replace the current flat `allowed_peers` hash list with role-aware rows (`identity hash` + `role select` + `label` + remove button).

### Phase 2 — Enforcement point migration (~1 day)

Goal: remove the compat shim; enforcement points call `policy.has_permission()` directly.

1. Inject `MeshPolicy` into `RPCServer`, `ChatProtocol`, `WebAuth`, `TerminalService`, `StyreneAnnounceHandler`.
2. Replace each `_is_authorized()` / `authorized_identities` check with `policy.has_permission(identity_hash, "<permission>")`.
3. Add the **currently-missing `mesh.chat` gate** to `ChatProtocol.handle_message()`.
4. The `enable_dangerous_commands` boolean gate on `RPCServer` becomes: `policy.has_permission(source_hash, "rpc.exec_dangerous")` — per-identity rather than global.
5. Deprecate `rpc.allow_command_execution`, `api.auth.authorized_identities`, `terminal.authorized_identities`, and `discovery.allowed_peers` in config (keep loading them for one release cycle; log a deprecation warning).
6. Add IPC commands for runtime management (no daemon restart required):
   - `LIST_PEERS` — returns all peer policies with their roles
   - `ADD_PEER` / `REMOVE_PEER` — add/remove identity from `mesh_policy.peers`
   - `SET_PEER_ROLE` — update an existing identity's role

---

## 10. What Is Explicitly Out of Scope

| Capability | Rationale for exclusion |
|---|---|
| **Role delegation over the mesh** | A remote ADMIN node cannot grant roles to a third node. Role assignment is local-config-only. The config file is the root of trust, not the mesh. |
| **Hierarchical RBAC (NIST Level 1+)** | Four flat roles covers all realistic use cases at current scale. Role explosion is not a concern with ~10 identities. |
| **ABAC runtime attributes** | Reticulum provides no ambient context at message delivery time. Identity hash is the only available attribute. |
| **Central policy authority** | Each node maintains its own `MeshPolicyConfig`. No hub distributes policy. Preserves the mesh's decentralised nature. |
| **Per-command EXEC scoping** | `rpc.exec_safe` covers all allowlisted commands for OPERATOR. Per-identity per-command scoping is a Phase 3 consideration if a real need emerges. |
| **Token/capability delegation** | Signed capability tokens would enable autonomous trust propagation but introduce revocation and replay complexity out of scope for the current threat model. |

---

## 11. Implementation Checklist

### Phase 1

- [ ] `models/config.py`: add `MeshRole`, `_ROLE_ORDER`, `role_gte()`, `PeerPolicy`, `MeshPolicyConfig`; add `mesh_policy: MeshPolicyConfig` to `CoreConfig`
- [ ] `services/config.py`: parse `mesh_policy` section (YAML → dataclass, normalise hashes to lowercase, validate role strings); serialize (dataclass → YAML); add compat shim to populate legacy fields
- [ ] `services/mesh_policy.py`: implement `_PERMISSION_MINIMUM_ROLE`, `MeshPolicy` (constructor, `role_for()`, `has_permission()`)
- [ ] Unit tests: role ordering, permission lookup, `role_for()` in OPEN/ALLOWLIST mode, denied-peer override, config round-trip
- [ ] TUI `screens/settings.py` Security tab: replace flat hash list with `(identity_hash, role select, label)` rows; update `_save_settings()` to write `PeerPolicy` list to `config.core.mesh_policy.peers`

### Phase 2

- [ ] `services/reticulum.py`: `StyreneAnnounceHandler` accepts `MeshPolicy`; use `has_permission(identity_hash, "mesh.announce")`
- [ ] `protocols/chat.py`: add `has_permission(source_hash, "mesh.chat")` gate in `handle_message()`
- [ ] `rpc/server.py`: inject `MeshPolicy`; replace `_is_authorized()` with `has_permission(source_hash, "rpc.status")`; replace global `_enable_dangerous_commands` gate with per-identity `has_permission(source_hash, "rpc.exec_dangerous")`
- [ ] `web/auth.py`: inject `MeshPolicy`; use `has_permission(identity_hash, "web.read")` / `"web.write"`
- [ ] `terminal/service.py`: inject `MeshPolicy`; use `has_permission(identity_hash, "terminal.connect")`
- [ ] `daemon.py`: construct `MeshPolicy` at startup; pass to all subsystems
- [ ] Deprecation warnings on load when legacy fields (`rpc.allow_command_execution`, `api.auth.authorized_identities`, `terminal.authorized_identities`, `discovery.allowed_peers`) are populated but `mesh_policy.peers` is empty
- [ ] IPC: `LIST_PEERS`, `ADD_PEER`, `REMOVE_PEER`, `SET_PEER_ROLE` request/response types and handlers
- [ ] Unit tests: each enforcement point; chat gate; per-identity dangerous RPC; denied-peer blocks at each layer
- [ ] Remove compat shim after one release cycle

---

## 12. Summary

The proposed model replaces five fragmented binary gates with a single unified `MeshPolicyConfig` containing a short list of `(identity_hash, role)` pairs.  The `MeshPolicy` evaluation object is O(1) dict lookup — suitable for resource-constrained edge devices.  The four roles (`OBSERVER`, `MONITOR`, `OPERATOR`, `ADMIN`) and twelve permissions cover every current and near-future identity-based operation.  

Phase 1 is a pure config consolidation with no behaviour change.  Phase 2 migrates enforcement points one at a time with no flag day.  The total new code is approximately 200 lines across three files, replacing approximately 400 lines of duplicated per-subsystem identity management.
