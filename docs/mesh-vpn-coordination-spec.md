# Mesh VPN Coordination Spec

**Date**: 2026-03-07
**Status**: Implementation-ready
**Supersedes**: Portions of `mesh-vpn-architecture.md` (bilateral-only design)
**Design rationale**: `styrene-lab/styrene/research/mesh-vpn-coordination.md` and 5 linked research docs

## Overview

Hub-coordinated WireGuard mesh VPN where the Styrene Hub acts as a fleet-scoped coordination server (analogous to Tailscale's control plane) riding LXMF instead of HTTPS. Existing bilateral VPN_HANDSHAKE_REQUEST/RESPONSE (0x34/0x35) remains as cross-fleet/ad-hoc escape hatch.

**Community hub (`rns.styrene.io:4242`) does NOT coordinate VPN.** VPN coordination is an "enclave" feature requiring a user-operated hub with an RBAC roster granting `vpn.handshake`.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Topology | Full mesh for v1 (<50 nodes) | O(n²) but simple; hub automates bilateral handshakes |
| WG interfaces | Single `wg-styrene`, multiple IPv6 addresses | One per enclave /64; cryptokey routing provides isolation |
| Subnet derivation | SHA-256 of hub identity → ULA /64 | Deterministic, no coordination between operators |
| Wire protocol | 2 new types: VPN_REGISTER (0x36), VPN_PEER_UPDATE (0x37) | Minimal surface; existing 0x34/0x35 unchanged |
| NAT traversal | Hub as WG relay (/64 catch-all, overridden by /128 direct) | Tailscale DERP model but at WG level |
| Key rotation | Deferred to v2 | Small fleets, no Curve25519 attacks, adds coordination complexity |
| Multi-enclave | Day-one internal model, single-enclave UX | `_enclaves` dict prevents data model migration later |
| Gateway election | Hub-authoritative, priority-based | Prevents split-brain when multiple gateways exist |
| VXLAN isolation | Per-enclave VNI derived from hub hash | One enclave bridged per bat interface |
| LoRa announces | Suppress when WiFi is up; 30-min keepalive only | Spectrum preservation; RNode airtime limits as v1 safety net |
| Announce timeouts | Tiered: stale 3×, offline 6×, expired 24h; per-transport profiles | WG handles unreachable peers gracefully; premature removal is costly |
| Coordinator location | In styrened, not public-hub | Hub is just styrened + deployment config; zero custom hub Python |

## Config Schema

### Before (current)

```python
# models/config.py line 682
@dataclass
class MeshVPNConfig:
    enable: bool = False
    listen_port: int = 51820
    subnet_prefix: str = "fd73:7479:7265:6e65"
    gateway: bool = False
    endpoint: str = ""
```

### After (target)

```python
@dataclass
class GatewayConfig:
    """Gateway settings for VPN-to-bat0 bridging.
    
    Hub elects one active gateway per enclave by priority.
    """
    enable: bool = False
    priority: int = 0               # Higher wins. Hub uses 255.
    bridge_enclave: str = ""        # Hub identity hash of enclave to VXLAN bridge.
                                    # Empty = first enclave. "none" = L3 only.
    bridge_interface: str = "bat0"  # Which bat interface. "bat-home" for dedicated RF.


@dataclass
class CoordinatorConfig:
    """VPN coordination hub settings. Activates the fleet topology manager.
    
    When enabled, this styrened instance watches for vpn.handshake-granted
    nodes via announces, pushes VPN_PEER_UPDATE topology, manages gateway
    election, and handles VPN_REGISTER from fleet nodes.
    """
    enable: bool = False
    announce_timeout_multiplier: int = 6   # × announce_interval → offline threshold
    gateway_failover_delay: float = 30.0   # Seconds before promoting standby
    flap_threshold: int = 3                # State changes in window → dampening
    flap_window: float = 1800.0            # 30 min flap detection window


@dataclass
class MeshVPNConfig:
    enable: bool = False
    listen_port: int = 51820
    enclaves: list[str] = field(default_factory=list)       # Hub identity hashes
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)
    endpoint: str = ""
    allow_bilateral: bool = True   # Accept VPN_HANDSHAKE from non-enclave peers
```

### Backward Compatibility

- `subnet_prefix` in old config → ignored with deprecation log warning. Now derived from hub identity.
- `gateway: true` (bare bool) → parser detects bool vs dict, converts to `GatewayConfig(enable=True)`.
- `enclaves` absent → empty list (bilateral-only, same as current behavior).
- All new fields default to preserving current behavior.

```python
def _parse_mesh_vpn(raw: dict) -> MeshVPNConfig:
    gw = raw.get("gateway", False)
    if isinstance(gw, bool):
        gateway_config = GatewayConfig(enable=gw)
    elif isinstance(gw, dict):
        gateway_config = GatewayConfig(**gw)
    else:
        gateway_config = GatewayConfig()
    
    coord = raw.get("coordinator", {})
    if isinstance(coord, dict):
        coordinator_config = CoordinatorConfig(**coord)
    else:
        coordinator_config = CoordinatorConfig()
    
    if "subnet_prefix" in raw:
        logger.warning(
            "mesh_vpn.subnet_prefix is deprecated and ignored. "
            "Subnet prefixes are now derived from enclave hub identity."
        )
    
    return MeshVPNConfig(
        enable=raw.get("enable", False),
        listen_port=raw.get("listen_port", 51820),
        enclaves=raw.get("enclaves", []),
        gateway=gateway_config,
        coordinator=coordinator_config,
        endpoint=raw.get("endpoint", ""),
        allow_bilateral=raw.get("allow_bilateral", True),
    )
```

## Wire Protocol

### Existing (unchanged)

| Type | Code | Direction | Purpose |
|---|---|---|---|
| VPN_HANDSHAKE_REQUEST | 0x34 | Node → Node | Bilateral P2P key exchange |
| VPN_HANDSHAKE_RESPONSE | 0x35 | Node → Node | Bilateral P2P key exchange response |

### New

| Type | Code | Direction | Purpose |
|---|---|---|---|
| VPN_REGISTER | 0x36 | Node → Hub | Register/update VPN info with fleet hub |
| VPN_PEER_UPDATE | 0x37 | Hub → Node | Add/remove/sync VPN peer configs |

### VPN_REGISTER Payload (0x36, Node → Hub)

```json
{
  "version": 1,
  "wg_pubkey": "<base64 WireGuard public key>",
  "mesh_ip": "fdab:1234:5678:9abc:xxxx:xxxx:xxxx:xxxx",
  "endpoint": "203.0.113.5:51820",
  "gateway": {
    "enable": true,
    "priority": 100
  },
  "transports": {
    "wifi": true,
    "internet": true,
    "lora": true,
    "primary": "internet"
  }
}
```

### VPN_PEER_UPDATE Payload (0x37, Hub → Node)

```json
{
  "version": 1,
  "hub_identity": "a1b2c3d4...",
  "subnet_prefix": "fdab:1234:5678:9abc",
  "action": "sync",
  "sequence": 42,
  "peers": [
    {
      "identity_hash": "peer1...",
      "wg_pubkey": "<base64>",
      "mesh_ip": "fdab:1234:5678:9abc:xxxx:xxxx:xxxx:xxxx",
      "endpoint": "203.0.113.5:51820",
      "gateway": false,
      "label": "pi-kitchen"
    }
  ],
  "rf_profile": null
}
```

- `action`: `"sync"` (full replacement), `"add"`, `"remove"`
- `sequence`: monotonic per hub; node rejects updates with sequence ≤ last seen
- `subnet_prefix`: node validates `== derive_enclave_prefix(hub_identity)`, reject on mismatch
- `rf_profile`: null for v1. v2 adds `{"meshId": "...", "channel": 36, "band": "5ghz"}`

## Derived Functions (Not Config)

```python
DEFAULT_SUBNET_PREFIX = "fd73:7479:7265:6e65"  # bilateral/community peering

def derive_enclave_prefix(hub_identity_hash: str) -> str:
    """Deterministic ULA /64 from hub's RNS identity hash."""
    digest = hashlib.sha256(hub_identity_hash.encode()).digest()
    return "fd{:02x}:{:02x}{:02x}:{:02x}{:02x}:{:02x}{:02x}".format(
        digest[0], digest[1], digest[2],
        digest[3], digest[4], digest[5], digest[6],
    )

def derive_vxlan_vni(hub_identity_hash: str) -> int:
    """Deterministic VXLAN VNI (24-bit) from hub identity hash."""
    digest = hashlib.sha256(hub_identity_hash.encode()).digest()
    vni = (digest[0] << 16) | (digest[1] << 8) | digest[2]
    return max(1, vni % 16777214) + 1
```

## Data Model

### Node-Side Peer Tracking

```python
@dataclass
class VPNPeerRecord:
    """A single VPN peer known to this node."""
    identity_hash: str
    wg_pubkey: str
    mesh_ip: str
    endpoint: str | None
    gateway: bool
    last_updated: float
    source: str               # "enclave:<hub_hash>" | "bilateral"
    label: str = ""

@dataclass
class EnclaveVPNState:
    """VPN state for a single enclave membership."""
    hub_identity: str
    subnet_prefix: str        # Derived from hub identity
    my_mesh_ip: str
    peers: dict[str, VPNPeerRecord]
    sequence: int = 0
    registered: bool = False

class MeshVPNService:
    _enclaves: dict[str, EnclaveVPNState]       # hub_identity → state
    _bilateral_peers: dict[str, VPNPeerRecord]   # identity_hash → peer
```

### NodeStore Persistence (new table: `vpn_peers`)

```sql
CREATE TABLE IF NOT EXISTS vpn_peers (
    identity_hash TEXT NOT NULL,
    wg_pubkey TEXT NOT NULL,
    mesh_ip TEXT NOT NULL,
    endpoint TEXT,
    gateway INTEGER DEFAULT 0,
    enclave_hub TEXT,          -- hub identity hash, NULL for bilateral
    label TEXT DEFAULT '',
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (identity_hash, enclave_hub)
);
```

### Hub-Side Coordinator State

```python
@dataclass
class VPNNodeRegistration:
    """A fleet node registered with the coordinator."""
    identity_hash: str
    wg_pubkey: str
    mesh_ip: str
    endpoint: str | None
    gateway_enable: bool
    gateway_priority: int
    transports: dict           # {"wifi": bool, "internet": bool, "lora": bool, "primary": str}
    last_seen: float           # time.monotonic()
    registered_at: float
    state: str = "online"      # "online" | "stale" | "offline"
```

## RBAC Enforcement

### Existing Model (no changes to `models/rbac.py`)

- `Capability.VPN_HANDSHAKE = "vpn.handshake"` (line 83) — orthogonal grant
- Intentionally excluded from all role tiers including ADMIN (line 135-137)
- Must be explicitly granted per-identity: `grants: [vpn.handshake]`
- `RBACPolicy.has_capability()` checks role-derived + explicit grants

### Enforcement Points

| Point | Phase | Location | Check |
|---|---|---|---|
| Bilateral handshake (node) | 1 | `mesh_vpn.py handle_handshake_request()` | `rbac.has_capability(source_hash, VPN_HANDSHAKE)` |
| Unsolicited response (node) | 1 | `mesh_vpn.py handle_handshake_response()` | Reject if no pending outbound handshake |
| Topology computation (hub) | 2 | `vpn_coordinator.py handle_announce()` | Only track nodes with `vpn.handshake` in roster |
| Registration acceptance (hub) | 2 | `vpn_coordinator.py handle_register()` | Reject `VPN_REGISTER` from nodes without grant |
| Topology push (hub) | 2 | `vpn_coordinator.py _push_topology()` | Only push to `vpn.handshake`-granted nodes |
| Revocation (hub) | 2 | On roster change | Push `action=remove` for revoked node; push `action=sync(empty)` to revoked node |

## Sequence Diagrams

### Node Joins Fleet VPN (Phase 2)

```
Node                          Hub (Coordinator)           Existing Peers
  │                            │                              │
  │──── RNS Announce ─────────>│                              │
  │                            │ (sees vpn.handshake grant)   │
  │                            │                              │
  │<── VPN_PEER_UPDATE ────────│  (action=sync, all peers)    │
  │    (full peer list)        │                              │
  │                            │                              │
  │── VPN_REGISTER ───────────>│  (my pubkey + endpoint)      │
  │                            │                              │
  │                            │── VPN_PEER_UPDATE ──────────>│
  │                            │   (action=add, new node)     │
  │                            │                              │
  │ (configure WG peers)       │                    (add WG peer)
  │                            │                              │
  │<═══════ WireGuard tunnels established ═══════════════════>│
```

### Revocation

```
Operator                      Hub (Coordinator)           Node    Other Peers
  │                            │                           │          │
  │── remove vpn.handshake ──>│                           │          │
  │   (RBAC roster update)     │                           │          │
  │                            │── VPN_PEER_UPDATE ──────>│          │
  │                            │   (action=sync, empty)    │          │
  │                            │── VPN_PEER_UPDATE ───────────────────>│
  │                            │   (action=remove, node)              │
  │                            │                           │          │
  │                            │              (tear down WG) (remove peer)
```

---

## Phase 1: RBAC Enforcement + Peer Persistence

*Node-side only. No hub changes. Hardens what exists.*

### Current State

| Component | File | State |
|---|---|---|
| RBAC model | `models/rbac.py` | **Complete.** `vpn.handshake` defined as orthogonal capability (line 83), excluded from all roles including ADMIN (line 135-137). `has_capability()` works. |
| MeshVPNService | `services/mesh_vpn.py` | **RBAC not enforced.** `handle_handshake_request()` (line 441) processes every incoming handshake with zero authorization checks. No import of rbac module. |
| Daemon integration | `daemon.py` | Wires handler at line 1564-1565. Does NOT pass RBAC policy to MeshVPNService. `self.config.rbac` is available on daemon. |
| Config model | `models/config.py` line 682 | `MeshVPNConfig` has 5 fields. Needs expansion. |
| Peer storage | `services/mesh_vpn.py` | `_peers: dict[str, PeerInfo]` in-memory only. Lost on restart. |
| NodeStore | `services/node_store.py` | SQLite-backed persistent store. Has `nodes` and `paths` tables. No `vpn_peers` table. |

### Tasks

#### 1.1 Config Schema Migration

**Files**: `models/config.py`

- [ ] Add `GatewayConfig` dataclass
- [ ] Add `CoordinatorConfig` dataclass  
- [ ] Replace `MeshVPNConfig` with new schema (enclaves list, gateway block, coordinator block, allow_bilateral)
- [ ] Remove `subnet_prefix` field (keep `DEFAULT_SUBNET_PREFIX` constant in `mesh_vpn.py`)
- [ ] Add backward-compat parser: detect `gateway: true` (bool) vs `gateway: {enable: true}` (dict)
- [ ] Log deprecation warning if `subnet_prefix` present in config

**Tests**: Parse old config format → new dataclass. Parse new config format. Bool gateway compat. subnet_prefix warning.

#### 1.2 RBAC Injection into MeshVPNService

**Files**: `services/mesh_vpn.py`, `daemon.py`

- [ ] Add `rbac_policy: RBACPolicy` parameter to `MeshVPNService.__init__()` (line 319)
- [ ] In `daemon.py _start_mesh_vpn()` (line 1535): pass `self.config.rbac` to MeshVPNService constructor
- [ ] In `handle_handshake_request()` (line 441): add early return if `self._rbac_policy.has_capability(remote_hash, Capability.VPN_HANDSHAKE)` is False. Log warning with truncated hash.
- [ ] In `handle_handshake_response()`: track pending outbound handshakes in `_pending_handshakes` dict. Reject responses for handshakes we didn't initiate.

**Tests**: Handshake rejected when source lacks `vpn.handshake` (assert handler returns without configuring peer). Handshake accepted when granted. Unsolicited response rejected. Solicited response accepted.

#### 1.3 Data Model Refactor

**Files**: `services/mesh_vpn.py`

- [ ] Replace `_peers: dict[str, PeerInfo]` with `_enclaves: dict[str, EnclaveVPNState]` + `_bilateral_peers: dict[str, VPNPeerRecord]`
- [ ] Add `derive_enclave_prefix()` and `derive_vxlan_vni()` functions
- [ ] Add `effective_peers` property: union of all enclave peers + bilateral peers
- [ ] Add `_generate_wg_peer_config()`: merge allowed-ips across enclaves for same pubkey
- [ ] Update `_configure_peer()` to use new data model
- [ ] Update `VXLAN_VNI = 7379` (line 758) to use `derive_vxlan_vni()` per enclave
- [ ] Update all references to `self._peers` → appropriate new dict
- [ ] Update gateway checks: `self.config.gateway` (bool) → `self.config.gateway.enable`

**Tests**: Enclave prefix derivation is deterministic. VNI derivation is deterministic. Effective peers merges correctly. Same pubkey in multiple enclaves produces merged allowed-ips.

#### 1.4 Peer Persistence

**Files**: `services/node_store.py`, `services/mesh_vpn.py`

- [ ] Add `vpn_peers` table to NodeStore schema (CREATE TABLE in `_ensure_schema()`)
- [ ] Add `upsert_vpn_peer()`, `get_vpn_peers()`, `delete_vpn_peer()` methods to NodeStore
- [ ] In `mesh_vpn.py`: after successful handshake, write peer to NodeStore
- [ ] In `MeshVPNService.start()`: load persisted peers from NodeStore, add to WG interface
- [ ] On hub topology push (Phase 2): persisted peers are "best effort" until hub re-pushes authoritative state

**Tests**: Peer persisted after handshake. Peers reloaded on restart. Peer removed from store on explicit removal. Schema migration doesn't break existing tables.

### Phase 1 Acceptance Criteria

- [ ] Unauthorized VPN handshake is rejected with warning log
- [ ] Authorized VPN handshake succeeds as before
- [ ] Unsolicited handshake response is rejected
- [ ] Peers survive daemon restart
- [ ] Old config format still works (backward compat)
- [ ] `_enclaves` dict used internally even for single/no enclave case
- [ ] VXLAN VNI derived from hub identity (or default for bilateral)
- [ ] All existing mesh_vpn tests still pass

---

## Phase 2: Hub Registration + Topology Push

*Hub becomes the coordination server. All code lives in styrened.*

### Current State

| Component | File | State |
|---|---|---|
| public-hub | `public-hub/` | Zero custom Python. `src/vanderlyn_reticulum/__init__.py` is just `__version__`. Hub is styrened + NomadNet via `entrypoint-consolidated.sh`. |
| StyreneProtocol | `protocols/styrene.py` line 64 | `register_handler(StyreneMessageType, async_callback)` — the extension point. Handlers stored in `_external_handlers` dict. |
| Daemon RBAC access | `daemon.py` | `self.config.rbac` available. Already injected into LXMF service via `_inject_lxmf_rbac()` (line 283). |
| StyreneProtocol lifecycle | `daemon.py` line 1177 | Created after LXMF service starts. Set on services post-construction (monkey-patch pattern). |
| Announce tracking | `services/reticulum.py` | `_announce_handler.discovered_devices` dict tracks announces. No callback/event system for announce arrival. |
| Wire types | `models/styrene_wire.py` | 0x34-0x35 defined. 0x36-0x37 free in network block (0x30-0x3F). |

### Tasks

#### 2.1 Wire Protocol

**Files**: `models/styrene_wire.py`

- [ ] Add `VPN_REGISTER = 0x36` and `VPN_PEER_UPDATE = 0x37` to `StyreneMessageType` enum
- [ ] Add encode/decode functions for both payload types (JSON, schemas per "Wire Protocol" section above)

**Tests**: Round-trip encode/decode for both message types. Invalid payloads raise appropriate errors.

#### 2.2 VPNCoordinatorService

**New file**: `services/vpn_coordinator.py` (~300-500 lines)

- [ ] **Constructor**: Takes `CoordinatorConfig`, `RBACPolicy`, `StyreneProtocol`, `identity_hash`
- [ ] **`start()`**: Register handler for VPN_REGISTER (0x36). Start periodic `_check_timeouts()` task (every 30s).
- [ ] **`handle_register(message, envelope)`**: Validate sender has `vpn.handshake`. Parse VPN_REGISTER payload. Store/update in `_registry`. If new: push `action=add` to all existing peers. If updated: push `action=sync` to all.
- [ ] **`handle_announce(identity_hash)`**: Called on announce from vpn.handshake-granted identity. Update last_seen if in registry. If not in registry: push `VPN_PEER_UPDATE action=sync` (invitation). Node responds with VPN_REGISTER.
- [ ] **`_check_timeouts()`**: Per-node timeout check using `announce_timeout_multiplier × interval` (interval from `transports.primary`). Tiered: stale → log. Offline → push `action=remove`. Expired (24h) → delete from registry.
- [ ] **`_elect_gateway()`**: Sort candidates by priority (descending), tiebreak by `registered_at`. Active gateway gets /64 in topology. Demoted → /128. Apply `gateway_failover_delay` before promoting standby after loss.
- [ ] **`_push_topology(target, action, peers)`**: Build VPN_PEER_UPDATE payload. Increment monotonic sequence. Send via StyreneProtocol.
- [ ] **`FlapDetector`**: Track state changes per node. ≥ `flap_threshold` in `flap_window` → suppress topology pushes until stable.

**Tests**:
- Coordinator pushes `action=sync` on new node announce (mock StyreneProtocol, verify `send_message` calls)
- Coordinator pushes `action=add` to existing peers on VPN_REGISTER
- Coordinator rejects VPN_REGISTER from node without `vpn.handshake`
- Timeout detection: stale → no push; offline → `action=remove` pushed
- Gateway election: highest priority wins; failover on loss after delay
- Flap detection: 3 state changes in 30 min → pushes suppressed

#### 2.3 Daemon Integration

**Files**: `daemon.py`

- [ ] **New `_start_vpn_coordinator()`**: Check `self.config.mesh_vpn.coordinator.enable`. Create VPNCoordinatorService. Pass `self.config.rbac`, `self._styrene_protocol`, operator identity hash. Register VPN_REGISTER handler.
- [ ] **Announce callback hook**: Add `_announce_callbacks: list[Callable]` to daemon. In existing announce processing path, call each callback with identity_hash. Coordinator registers itself via this hook.
- [ ] **Startup order**: `_start_vpn_coordinator()` after `_start_mesh_vpn()` and after StyreneProtocol is initialized.

**Tests**: Coordinator not started when `coordinator.enable: false`. Coordinator receives announce callbacks.

#### 2.4 Node-Side VPN_PEER_UPDATE Handler

**Files**: `services/mesh_vpn.py`

- [ ] Register handler for VPN_PEER_UPDATE (0x37) in `_start_mesh_vpn()`
- [ ] **`handle_peer_update(message, envelope)`**:
  - Validate `hub_identity` is in `self.config.enclaves`
  - Validate `subnet_prefix == derive_enclave_prefix(hub_identity)`
  - Check `sequence > enclave.sequence` (reject stale)
  - `action=sync`: replace enclave's peer dict entirely
  - `action=add`: add/update peers in enclave's peer dict
  - `action=remove`: remove peers from enclave's peer dict
  - Recompute effective WG peers and apply to interface
  - Persist updated peers to NodeStore
- [ ] **Send VPN_REGISTER** after first VPN_PEER_UPDATE from each hub
- [ ] **Re-register on reconnect**: After eager discovery re-announce, send VPN_REGISTER to all enclave hubs
- [ ] **Re-register on state change**: Endpoint or key change → re-register with all hubs

**Tests**:
- `action=sync` replaces enclave peers
- `action=add` / `action=remove` work incrementally
- Stale sequence rejected
- Mismatched subnet_prefix rejected
- Hub_identity not in enclaves list → rejected
- VPN_REGISTER sent after first topology push

### Phase 2 Acceptance Criteria

- [ ] Node announces → coordinator pushes topology → node registers → coordinator pushes add to peers (full flow)
- [ ] Node goes offline → coordinator pushes remove after timeout
- [ ] RBAC revocation → coordinator pushes remove to fleet + empty sync to revoked node
- [ ] Gateway election picks highest priority; failover works
- [ ] Flapping node doesn't cause topology churn
- [ ] Sequence numbers prevent stale topology application
- [ ] Coordinator and MeshVPNService coexist on same node

---

## Phase 3: NAT Relay via Hub Gateway

*Hub as relay of last resort for double-NAT pairs.*

### Current State

- MeshVPNService already supports `gateway: true` — VXLAN bridge, /64 allowed-ips, ip forwarding.
- `_detect_local_endpoint()` (line 345) returns `"IP:port"` or empty. No public/private classification.
- Hub has public IP (k8s LoadBalancer on 4242). WG needs separate port 51820/UDP.
- Phase 2 coordinator already builds peer lists. Just needs to inject itself as gateway.

### Tasks

#### 3.1 Hub as WG Gateway

**Files**: `services/vpn_coordinator.py`

- [ ] In `_push_topology()`: always include hub's own WG pubkey, mesh_ip, endpoint with `gateway: true` in peer list
- [ ] Hub MeshVPNService config: `gateway.enable: true`, `gateway.priority: 255`, `endpoint: "<public_ip>:51820"`

#### 3.2 Route Priority Logic

**Files**: `services/mesh_vpn.py`

- [ ] Gateway peers: `allowed_ips = "<enclave_prefix>::/64"` (catch-all)
- [ ] Non-gateway peers: `allowed_ips = "<mesh_ip>/128"` (direct)
- [ ] WG longest-prefix-match means /128 overrides /64 when direct tunnel works
- [ ] Persistent-keepalive 25s on gateway peer (keep NAT mapping open)

#### 3.3 Endpoint Classification

**Files**: `services/mesh_vpn.py`

- [ ] Add `EndpointInfo` dataclass: `address: str`, `classification: str` ("public"/"private"/"unknown")
- [ ] Classify RFC 1918 / RFC 4193 → "private". Configured endpoint → "public". Failed detection → "unknown".
- [ ] Include classification in VPN_REGISTER so hub can make relay decisions

#### 3.4 Hub Deployment

**Files**: `public-hub/deploy/`

- [ ] Add port 51820/UDP to k8s service
- [ ] WG private key in Vault-backed Secret (same pattern as hub-identities)
- [ ] Enclave hub example config in docker-compose

### Phase 3 Acceptance Criteria

- [ ] Hub appears as gateway peer in every topology push
- [ ] Direct /128 route takes priority over /64 gateway
- [ ] Traffic between two NAT'd nodes routes through hub gateway
- [ ] Endpoint classification correct for RFC 1918 and public IPs

---

## Phase 4: Key Rotation (v2, deferred)

Design sketched in research docs. Not specified here. Implement when fleet sizes warrant.

---

## Example Configs

### Node (single enclave member)

```yaml
mesh_vpn:
  enable: true
  enclaves:
    - "a1b2c3d4e5f6..."   # home fleet hub identity hash
  allow_bilateral: true
```

### Gateway Node (GL-iNet router, enclave isolation)

```yaml
mesh_vpn:
  enable: true
  enclaves:
    - "a1b2c3d4e5f6..."
  gateway:
    enable: true
    priority: 100
    bridge_enclave: "a1b2c3d4e5f6..."
    bridge_interface: "bat-home"    # dedicated 5 GHz enclave mesh
```

### Enclave Hub (coordinator + gateway)

```yaml
mesh_vpn:
  enable: true
  endpoint: "203.0.113.5:51820"
  allow_bilateral: false
  enclaves: []                      # hub IS the enclave, doesn't join itself
  gateway:
    enable: true
    priority: 255
    bridge_enclave: ""
    bridge_interface: "bat0"
  coordinator:
    enable: true
    announce_timeout_multiplier: 6
    gateway_failover_delay: 30
    flap_threshold: 3
    flap_window: 1800

# RBAC roster granting vpn.handshake to fleet nodes
rbac:
  default_role: peer
  roster:
    "deadbeef01...":
      role: operator
      grants: [vpn.handshake]
    "cafebabe02...":
      role: peer
      grants: [vpn.handshake]
    "feedface03...":
      role: peer
      grants: [vpn.handshake]
```

### Community Hub (NO VPN coordination)

```yaml
# Current community hub config — unchanged
mesh_vpn:
  enable: false
  # coordinator.enable defaults to false
  # No vpn.handshake grants in RBAC roster
```

---

## IPC Wiring (TUI ↔ Daemon)

The TUI communicates with the daemon over a Unix socket IPC protocol (msgpack frames). VPN state must be queryable and VPN config adjustable through this channel for the TUI to expose it.

### Current IPC Architecture

```
TUI (settings.py)
  │  reads/writes ~/.config/styrene/config.yaml (StyreneConfig)
  │  calls IPCBridge for runtime daemon interaction
  ▼
IPCBridge (ipc/client.py)
  │  async methods: query_status(), query_config(), set_identity(), ...
  │  each wraps a Request dataclass → encode_frame() → Unix socket → decode_frame() → Response
  ▼
IPC Server (ipc/server.py)
  │  dispatches to IPCHandler methods by IPCMessageType
  ▼
IPCHandler (ipc/handlers.py)
  │  handle_query_config(), handle_query_status(), handle_cmd_*()
  │  accesses self.daemon.config, self.daemon._mesh_vpn_service, etc.
  ▼
Daemon (daemon.py)
  │  owns all services: MeshVPNService, VPNCoordinatorService, etc.
```

### Gap: mesh_vpn Absent from IPC

`handle_query_config()` (handlers.py line 359) returns a sanitized config dict but **completely omits `mesh_vpn`**. There are no VPN-specific IPC commands. The TUI settings screen has no VPN tab.

### New IPC Types Needed

Add to `IPCMessageType` enum (`ipc/protocol.py`):

```python
# VPN query/command range (0x70-0x7F)
QUERY_VPN_STATUS = 0x70       # Get VPN service state + peer list
QUERY_VPN_PEERS = 0x71        # Get detailed peer info
CMD_VPN_ENABLE = 0x72         # Enable/disable VPN service at runtime
CMD_VPN_ADD_ENCLAVE = 0x73    # Join an enclave (add hub identity to config)
CMD_VPN_REMOVE_ENCLAVE = 0x74 # Leave an enclave
CMD_VPN_TRIGGER_HANDSHAKE = 0x75  # Initiate bilateral handshake with a peer

# VPN events (pushed to subscribers)
EVENT_VPN_PEER = 0xC7         # Peer added/removed/state change
EVENT_VPN_ENCLAVE = 0xC8      # Enclave topology update
```

### New IPC Messages (`ipc/messages.py`)

```python
# --- Requests ---

@dataclass
class QueryVPNStatusRequest(IPCRequest):
    """Query VPN service status and summary."""
    MSG_TYPE = IPCMessageType.QUERY_VPN_STATUS

@dataclass
class QueryVPNPeersRequest(IPCRequest):
    """Query detailed VPN peer list, optionally filtered by enclave."""
    MSG_TYPE = IPCMessageType.QUERY_VPN_PEERS
    enclave_hub: str | None = None  # None = all enclaves + bilateral

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.enclave_hub is not None:
            payload["enclave_hub"] = self.enclave_hub
        return payload

@dataclass
class CmdVPNEnableRequest(IPCRequest):
    """Enable or disable VPN service at runtime."""
    MSG_TYPE = IPCMessageType.CMD_VPN_ENABLE
    enable: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {"enable": self.enable}

@dataclass
class CmdVPNAddEnclaveRequest(IPCRequest):
    """Join a VPN enclave by hub identity hash."""
    MSG_TYPE = IPCMessageType.CMD_VPN_ADD_ENCLAVE
    hub_identity: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"hub_identity": self.hub_identity}

@dataclass
class CmdVPNRemoveEnclaveRequest(IPCRequest):
    """Leave a VPN enclave."""
    MSG_TYPE = IPCMessageType.CMD_VPN_REMOVE_ENCLAVE
    hub_identity: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"hub_identity": self.hub_identity}

@dataclass
class CmdVPNTriggerHandshakeRequest(IPCRequest):
    """Initiate bilateral VPN handshake with a specific peer."""
    MSG_TYPE = IPCMessageType.CMD_VPN_TRIGGER_HANDSHAKE
    peer_identity: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"peer_identity": self.peer_identity}
```

### New IPC Response Data (`ipc/messages.py`)

```python
@dataclass
class VPNStatusInfo:
    """VPN service status for IPC responses."""
    enabled: bool
    started: bool
    interface_name: str
    public_key: str
    mesh_ip: str
    listen_port: int
    endpoint: str
    allow_bilateral: bool
    enclave_count: int
    total_peer_count: int
    bilateral_peer_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "started": self.started,
            "interface_name": self.interface_name,
            "public_key": self.public_key,
            "mesh_ip": self.mesh_ip,
            "listen_port": self.listen_port,
            "endpoint": self.endpoint,
            "allow_bilateral": self.allow_bilateral,
            "enclave_count": self.enclave_count,
            "total_peer_count": self.total_peer_count,
            "bilateral_peer_count": self.bilateral_peer_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VPNStatusInfo":
        return cls(**{k: data.get(k, v) for k, v in cls.__dataclass_fields__.items()
                      if k in data})


@dataclass
class VPNPeerInfo:
    """Single VPN peer for IPC responses."""
    identity_hash: str
    wg_pubkey: str
    mesh_ip: str
    endpoint: str | None
    gateway: bool
    source: str           # "enclave:<hub_hash>" | "bilateral"
    label: str
    last_handshake: float | None   # WG last handshake timestamp
    rx_bytes: int | None
    tx_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_hash": self.identity_hash,
            "wg_pubkey": self.wg_pubkey,
            "mesh_ip": self.mesh_ip,
            "endpoint": self.endpoint,
            "gateway": self.gateway,
            "source": self.source,
            "label": self.label,
            "last_handshake": self.last_handshake,
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VPNPeerInfo":
        return cls(
            identity_hash=data.get("identity_hash", ""),
            wg_pubkey=data.get("wg_pubkey", ""),
            mesh_ip=data.get("mesh_ip", ""),
            endpoint=data.get("endpoint"),
            gateway=data.get("gateway", False),
            source=data.get("source", "bilateral"),
            label=data.get("label", ""),
            last_handshake=data.get("last_handshake"),
            rx_bytes=data.get("rx_bytes"),
            tx_bytes=data.get("tx_bytes"),
        )


@dataclass
class VPNEnclaveInfo:
    """VPN enclave membership status for IPC responses."""
    hub_identity: str
    subnet_prefix: str
    my_mesh_ip: str
    peer_count: int
    sequence: int
    registered: bool       # Have we sent VPN_REGISTER to this hub?
    gateway_identity: str | None   # Active gateway for this enclave

    def to_dict(self) -> dict[str, Any]:
        return {
            "hub_identity": self.hub_identity,
            "subnet_prefix": self.subnet_prefix,
            "my_mesh_ip": self.my_mesh_ip,
            "peer_count": self.peer_count,
            "sequence": self.sequence,
            "registered": self.registered,
            "gateway_identity": self.gateway_identity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VPNEnclaveInfo":
        return cls(
            hub_identity=data.get("hub_identity", ""),
            subnet_prefix=data.get("subnet_prefix", ""),
            my_mesh_ip=data.get("my_mesh_ip", ""),
            peer_count=data.get("peer_count", 0),
            sequence=data.get("sequence", 0),
            registered=data.get("registered", False),
            gateway_identity=data.get("gateway_identity"),
        )
```

### IPC Handler Additions (`ipc/handlers.py`)

```python
async def handle_query_vpn_status(self, request: IPCRequest) -> IPCResponse:
    """Return VPN service state summary."""
    vpn = self.daemon._mesh_vpn_service
    if vpn is None:
        return ResultResponse(data={"vpn": VPNStatusInfo(
            enabled=False, started=False, interface_name="wg-styrene",
            public_key="", mesh_ip="", listen_port=51820, endpoint="",
            allow_bilateral=True, enclave_count=0,
            total_peer_count=0, bilateral_peer_count=0,
        ).to_dict()})
    
    return ResultResponse(data={
        "vpn": VPNStatusInfo(
            enabled=vpn.config.enable,
            started=vpn._started,
            interface_name=vpn._interface_name,
            public_key=vpn.public_key,
            mesh_ip=vpn.mesh_ip,
            listen_port=vpn.config.listen_port,
            endpoint=vpn.config.endpoint or vpn._detect_local_endpoint(vpn.config.listen_port),
            allow_bilateral=vpn.config.allow_bilateral,
            enclave_count=len(vpn._enclaves),
            total_peer_count=sum(len(e.peers) for e in vpn._enclaves.values()) + len(vpn._bilateral_peers),
            bilateral_peer_count=len(vpn._bilateral_peers),
        ).to_dict(),
        "enclaves": [VPNEnclaveInfo(
            hub_identity=hub,
            subnet_prefix=state.subnet_prefix,
            my_mesh_ip=state.my_mesh_ip,
            peer_count=len(state.peers),
            sequence=state.sequence,
            registered=state.registered,
            gateway_identity=next((p.identity_hash for p in state.peers.values() if p.gateway), None),
        ).to_dict() for hub, state in vpn._enclaves.items()],
    })


async def handle_query_vpn_peers(self, request: IPCRequest) -> IPCResponse:
    """Return detailed VPN peer list."""
    vpn = self.daemon._mesh_vpn_service
    if vpn is None:
        return ResultResponse(data={"peers": []})
    
    enclave_filter = getattr(request, "enclave_hub", None)
    peers = []
    
    # Collect enclave peers
    for hub, state in vpn._enclaves.items():
        if enclave_filter and hub != enclave_filter:
            continue
        for p in state.peers.values():
            peers.append(VPNPeerInfo(
                identity_hash=p.identity_hash,
                wg_pubkey=p.wg_pubkey,
                mesh_ip=p.mesh_ip,
                endpoint=p.endpoint,
                gateway=p.gateway,
                source=f"enclave:{hub}",
                label=p.label,
                last_handshake=None,  # populated from `wg show` in Phase 3
                rx_bytes=None,
                tx_bytes=None,
            ).to_dict())
    
    # Collect bilateral peers (unless filtered to specific enclave)
    if not enclave_filter:
        for p in vpn._bilateral_peers.values():
            peers.append(VPNPeerInfo(
                identity_hash=p.identity_hash,
                wg_pubkey=p.wg_pubkey,
                mesh_ip=p.mesh_ip,
                endpoint=p.endpoint,
                gateway=p.gateway,
                source="bilateral",
                label=p.label,
                last_handshake=None,
                rx_bytes=None,
                tx_bytes=None,
            ).to_dict())
    
    return ResultResponse(data={"peers": peers})
```

Also update `handle_query_config()` to include mesh_vpn:

```python
# In handle_query_config(), add after existing sections:
if hasattr(config, "mesh_vpn"):
    config_dict["mesh_vpn"] = {
        "enable": config.mesh_vpn.enable,
        "listen_port": config.mesh_vpn.listen_port,
        "endpoint": config.mesh_vpn.endpoint,
        "allow_bilateral": config.mesh_vpn.allow_bilateral,
        "enclaves": config.mesh_vpn.enclaves,
        "gateway": {
            "enable": config.mesh_vpn.gateway.enable,
            "priority": config.mesh_vpn.gateway.priority,
            "bridge_enclave": config.mesh_vpn.gateway.bridge_enclave,
            "bridge_interface": config.mesh_vpn.gateway.bridge_interface,
        },
        "coordinator": {
            "enable": config.mesh_vpn.coordinator.enable,
            "announce_timeout_multiplier": config.mesh_vpn.coordinator.announce_timeout_multiplier,
            "gateway_failover_delay": config.mesh_vpn.coordinator.gateway_failover_delay,
        },
    }
```

### IPC Client Additions (`ipc/client.py`)

```python
async def query_vpn_status(self) -> dict[str, Any]:
    """Query VPN service status."""
    data = await self._request(QueryVPNStatusRequest())
    return data

async def query_vpn_peers(self, enclave_hub: str | None = None) -> list[dict[str, Any]]:
    """Query VPN peer list, optionally filtered by enclave."""
    data = await self._request(QueryVPNPeersRequest(enclave_hub=enclave_hub))
    return cast(list[dict[str, Any]], data.get("peers", []))

async def vpn_enable(self, enable: bool = True) -> None:
    """Enable or disable VPN service."""
    await self._request(CmdVPNEnableRequest(enable=enable))

async def vpn_add_enclave(self, hub_identity: str) -> None:
    """Join a VPN enclave."""
    await self._request(CmdVPNAddEnclaveRequest(hub_identity=hub_identity))

async def vpn_remove_enclave(self, hub_identity: str) -> None:
    """Leave a VPN enclave."""
    await self._request(CmdVPNRemoveEnclaveRequest(hub_identity=hub_identity))

async def vpn_trigger_handshake(self, peer_identity: str) -> None:
    """Initiate bilateral VPN handshake."""
    await self._request(CmdVPNTriggerHandshakeRequest(peer_identity=peer_identity))
```

### IPC Event Wiring

```python
# VPN events pushed to SUB_ACTIVITY subscribers

@dataclass
class VPNPeerEventPayload:
    """Payload for EVENT_VPN_PEER notifications."""
    event_type: str          # "added" | "removed" | "updated" | "handshake_complete"
    identity_hash: str
    mesh_ip: str
    source: str              # "enclave:<hub>" | "bilateral"
    label: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "identity_hash": self.identity_hash,
            "mesh_ip": self.mesh_ip,
            "source": self.source,
            "label": self.label,
        }

@dataclass
class VPNEnclaveEventPayload:
    """Payload for EVENT_VPN_ENCLAVE notifications."""
    event_type: str          # "joined" | "left" | "topology_sync" | "gateway_changed"
    hub_identity: str
    subnet_prefix: str
    peer_count: int = 0
    gateway_identity: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "hub_identity": self.hub_identity,
            "subnet_prefix": self.subnet_prefix,
            "peer_count": self.peer_count,
            "gateway_identity": self.gateway_identity,
        }
```

Events are emitted by MeshVPNService when peers change, and by VPNCoordinatorService when topology updates are received. The IPC server pushes them to all `SUB_ACTIVITY` subscribers. The TUI subscribes on startup and updates the VPN dashboard/peer list reactively.

### IPC Handler Registration (`ipc/server.py`)

The server's `_register_handlers()` maps `IPCMessageType` → handler. Add:

```python
self._handlers[IPCMessageType.QUERY_VPN_STATUS] = self._handler.handle_query_vpn_status
self._handlers[IPCMessageType.QUERY_VPN_PEERS] = self._handler.handle_query_vpn_peers
self._handlers[IPCMessageType.CMD_VPN_ENABLE] = self._handler.handle_cmd_vpn_enable
self._handlers[IPCMessageType.CMD_VPN_ADD_ENCLAVE] = self._handler.handle_cmd_vpn_add_enclave
self._handlers[IPCMessageType.CMD_VPN_REMOVE_ENCLAVE] = self._handler.handle_cmd_vpn_remove_enclave
self._handlers[IPCMessageType.CMD_VPN_TRIGGER_HANDSHAKE] = self._handler.handle_cmd_vpn_trigger_handshake
```

### `create_request()` Factory (`ipc/messages.py`)

Add to the factory switch:

```python
elif msg_type == IPCMessageType.QUERY_VPN_STATUS:
    return QueryVPNStatusRequest()
elif msg_type == IPCMessageType.QUERY_VPN_PEERS:
    return QueryVPNPeersRequest(enclave_hub=payload.get("enclave_hub"))
elif msg_type == IPCMessageType.CMD_VPN_ENABLE:
    return CmdVPNEnableRequest(enable=payload.get("enable", True))
elif msg_type == IPCMessageType.CMD_VPN_ADD_ENCLAVE:
    return CmdVPNAddEnclaveRequest(hub_identity=payload.get("hub_identity", ""))
elif msg_type == IPCMessageType.CMD_VPN_REMOVE_ENCLAVE:
    return CmdVPNRemoveEnclaveRequest(hub_identity=payload.get("hub_identity", ""))
elif msg_type == IPCMessageType.CMD_VPN_TRIGGER_HANDSHAKE:
    return CmdVPNTriggerHandshakeRequest(peer_identity=payload.get("peer_identity", ""))
```

### DaemonStatus Extension (`ipc/messages.py`)

Add VPN summary fields to `DaemonStatus` so the dashboard header shows VPN state without a separate query:

```python
@dataclass
class DaemonStatus:
    # ... existing fields ...
    vpn_enabled: bool = False
    vpn_started: bool = False
    vpn_peer_count: int = 0
    vpn_enclave_count: int = 0
```

Populated in `handle_query_status()`:

```python
# In handle_query_status(), after existing status assembly:
vpn = self.daemon._mesh_vpn_service
if vpn is not None:
    status.vpn_enabled = vpn.config.enable
    status.vpn_started = vpn._started
    status.vpn_peer_count = sum(len(e.peers) for e in vpn._enclaves.values()) + len(vpn._bilateral_peers)
    status.vpn_enclave_count = len(vpn._enclaves)
```

### TUI Settings Screen: VPN Tab

New tab in `SettingsScreen.compose()` (after Security tab, before System tab):

```python
# ── Tab: VPN ─────────────────────────────────────────
with TabPane("VPN", id="tab-vpn"):
    with VerticalScroll():
        # Enable/disable
        with HighlightedPanel("Mesh VPN", border_title_align="left"):
            with Horizontal(classes="setting-row"):
                Label("Enable VPN:", classes="setting-label")
                Switch(value=self.config.core.mesh_vpn.enable, id="vpn_enable")
            with Horizontal(classes="setting-row"):
                Label("Listen Port:", classes="setting-label")
                Input(str(self.config.core.mesh_vpn.listen_port), id="vpn_listen_port")
            with Horizontal(classes="setting-row"):
                Label("Endpoint:", classes="setting-label")
                Input(self.config.core.mesh_vpn.endpoint, id="vpn_endpoint", placeholder="auto-detect")
            with Horizontal(classes="setting-row"):
                Label("Allow Bilateral:", classes="setting-label")
                Switch(value=self.config.core.mesh_vpn.allow_bilateral, id="vpn_allow_bilateral")

        # Enclaves
        with HighlightedPanel("Enclave Memberships", border_title_align="left"):
            # Dynamic list of hub identity hashes
            for i, hub in enumerate(self.config.core.mesh_vpn.enclaves):
                with Horizontal(classes="setting-row"):
                    Input(hub, id=f"vpn_enclave_{i}", classes="enclave-hash-input")
                    Button("✕", id=f"vpn_enclave_remove_{i}", variant="error", classes="remove-btn")
            Button("+ Add Enclave", id="vpn_enclave_add", variant="primary")

        # Gateway
        with HighlightedPanel("Gateway", border_title_align="left"):
            with Horizontal(classes="setting-row"):
                Label("Enable Gateway:", classes="setting-label")
                Switch(value=self.config.core.mesh_vpn.gateway.enable, id="vpn_gateway_enable")
            with Horizontal(classes="setting-row"):
                Label("Priority:", classes="setting-label")
                Input(str(self.config.core.mesh_vpn.gateway.priority), id="vpn_gateway_priority")
            with Horizontal(classes="setting-row"):
                Label("Bridge Enclave:", classes="setting-label")
                Input(self.config.core.mesh_vpn.gateway.bridge_enclave, id="vpn_bridge_enclave", placeholder="first enclave")
            with Horizontal(classes="setting-row"):
                Label("Bridge Interface:", classes="setting-label")
                Input(self.config.core.mesh_vpn.gateway.bridge_interface, id="vpn_bridge_interface")

        # Coordinator (hub-only, shown conditionally)
        with HighlightedPanel("Coordinator (Hub Only)", border_title_align="left"):
            with Horizontal(classes="setting-row"):
                Label("Enable Coordinator:", classes="setting-label")
                Switch(value=self.config.core.mesh_vpn.coordinator.enable, id="vpn_coord_enable")
            with Horizontal(classes="setting-row"):
                Label("Timeout Multiplier:", classes="setting-label")
                Input(str(self.config.core.mesh_vpn.coordinator.announce_timeout_multiplier), id="vpn_coord_timeout_mult")
            with Horizontal(classes="setting-row"):
                Label("Failover Delay (s):", classes="setting-label")
                Input(str(self.config.core.mesh_vpn.coordinator.gateway_failover_delay), id="vpn_coord_failover_delay")
```

### TUI Save Handler Additions (`settings.py action_save`)

```python
# Read VPN settings
vpn_enable = self.query_one("#vpn_enable", Switch).value
vpn_port_str = self.query_one("#vpn_listen_port", Input).value
vpn_endpoint = self.query_one("#vpn_endpoint", Input).value.strip()
vpn_bilateral = self.query_one("#vpn_allow_bilateral", Switch).value

try:
    vpn_port = int(vpn_port_str)
except ValueError:
    self._show_error("VPN listen port must be a number")
    return

self.config.core.mesh_vpn.enable = vpn_enable
self.config.core.mesh_vpn.listen_port = vpn_port
self.config.core.mesh_vpn.endpoint = vpn_endpoint
self.config.core.mesh_vpn.allow_bilateral = vpn_bilateral

# Enclaves (dynamic list)
enclaves = []
i = 0
while True:
    try:
        inp = self.query_one(f"#vpn_enclave_{i}", Input)
        val = inp.value.strip()
        if val:
            enclaves.append(val)
        i += 1
    except Exception:
        break
self.config.core.mesh_vpn.enclaves = enclaves

# Gateway
self.config.core.mesh_vpn.gateway.enable = self.query_one("#vpn_gateway_enable", Switch).value
gw_priority_str = self.query_one("#vpn_gateway_priority", Input).value
try:
    self.config.core.mesh_vpn.gateway.priority = int(gw_priority_str)
except ValueError:
    self._show_error("Gateway priority must be a number")
    return
self.config.core.mesh_vpn.gateway.bridge_enclave = self.query_one("#vpn_bridge_enclave", Input).value.strip()
self.config.core.mesh_vpn.gateway.bridge_interface = self.query_one("#vpn_bridge_interface", Input).value.strip()

# Coordinator
self.config.core.mesh_vpn.coordinator.enable = self.query_one("#vpn_coord_enable", Switch).value
coord_mult_str = self.query_one("#vpn_coord_timeout_mult", Input).value
try:
    self.config.core.mesh_vpn.coordinator.announce_timeout_multiplier = int(coord_mult_str)
except ValueError:
    self._show_error("Timeout multiplier must be a number")
    return
coord_delay_str = self.query_one("#vpn_coord_failover_delay", Input).value
try:
    self.config.core.mesh_vpn.coordinator.gateway_failover_delay = float(coord_delay_str)
except ValueError:
    self._show_error("Failover delay must be a number")
    return
```

### Summary: Files Changed Per Layer

| Layer | File | Changes |
|---|---|---|
| Wire protocol | `ipc/protocol.py` | 8 new `IPCMessageType` values (0x70-0x75, 0xC7-0xC8) |
| Messages | `ipc/messages.py` | 6 request classes, 3 info dataclasses, 2 event payloads, factory additions |
| Handlers | `ipc/handlers.py` | 6 new `handle_*` methods, `handle_query_config()` mesh_vpn addition, `handle_query_status()` VPN fields |
| Server | `ipc/server.py` | 6 handler registrations in `_register_handlers()` |
| Client | `ipc/client.py` | 6 new async methods |
| TUI models | `tui/models/config.py` | Import/re-export `MeshVPNConfig`, `GatewayConfig`, `CoordinatorConfig` |
| TUI settings | `tui/screens/settings.py` | New VPN tab in `compose()`, save handler additions |
| Events | `ipc/handlers.py` + `services/mesh_vpn.py` | Emit `EVENT_VPN_PEER` / `EVENT_VPN_ENCLAVE` on state changes |

### Phase Alignment

| IPC Addition | Phase |
|---|---|
| `QUERY_VPN_STATUS` + response | Phase 1 (reports RBAC-enforced bilateral state) |
| `QUERY_VPN_PEERS` + response | Phase 1 (bilateral peers only initially) |
| `CMD_VPN_ENABLE` | Phase 1 |
| `CMD_VPN_TRIGGER_HANDSHAKE` | Phase 1 |
| `handle_query_config()` mesh_vpn block | Phase 1 |
| `DaemonStatus` VPN fields | Phase 1 |
| Settings VPN tab (basic: enable, port, endpoint, bilateral) | Phase 1 |
| `CMD_VPN_ADD_ENCLAVE` / `CMD_VPN_REMOVE_ENCLAVE` | Phase 2 |
| `EVENT_VPN_PEER` / `EVENT_VPN_ENCLAVE` | Phase 2 |
| Settings VPN tab (full: enclaves, gateway, coordinator) | Phase 2 |
| `QUERY_VPN_PEERS` with WG stats (last_handshake, rx/tx) | Phase 3 |
