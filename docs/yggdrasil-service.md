---
id: yggdrasil-service
title: YggdrasilService — styrened-managed Yggdrasil daemon
status: implementing
parent: overlay-network-integration
tags: [yggdrasil, service, daemon, packaging, nix]
open_questions: []
branches: ["feature/yggdrasil-service"]
openspec_change: yggdrasil-service
---

# YggdrasilService — styrened-managed Yggdrasil daemon

## Overview

Explore what it means for styrened to own and manage the Yggdrasil daemon lifecycle — similar to how MeshVPNService manages WireGuard interfaces and how batman-mesh.nix manages BATMAN-ADV in styrene-edge. Covers: binary packaging, config generation, admin socket queries, dynamic peer management, NixOS module, and OCI container story.

## Research

### Precedent: how MeshVPNService manages WireGuard and batman-mesh.nix manages BATMAN

**WireGuard management (MeshVPNService)**:
- Generates `/etc/wireguard/wg-styrene.conf` from internal state
- Runs `wg-quick up` / `wg-quick down` to manage the interface
- Calls `wg set` to add/remove peers at runtime without full restart
- Creates VXLAN interfaces via `ip link add vxlan-<peer>` for each peer
- All operations are `asyncio.create_subprocess_exec` calls — no library, raw subprocess
- Manages its own keypair in `~/.styrene/wireguard_private_key`
- Service is only activated on Linux (runtime `platform.system()` check)

**BATMAN-ADV management (batman-mesh.nix)**:
- NixOS module in styrene-edge — declarative, not imperative
- NetworkManager mesh profile for 802.11s
- `batctl if add` via systemd oneshot service
- gwMode (off/client/server) configurable per device
- This is NOT managed by styrened the daemon — it's a NixOS system-level concern
- Styrened queries bat0 state but doesn't configure it

**Key distinction**: WireGuard is managed dynamically at runtime by styrened (peer list changes). BATMAN-ADV is managed statically at provision time by NixOS. The question is which model Yggdrasil follows.

Yggdrasil is closer to WireGuard: its peer list is dynamic (add peers at runtime via admin socket), and it benefits from runtime management. But its keypair and base config are static (like WireGuard's key).

### YggdrasilService design: what it owns and what it delegates



### NixOS integration and OCI container story



### Yggdrasil address in RNS announces — extending app_data

The most powerful distribution mechanism: include the local Yggdrasil address in every RNS announce. Any node that hears the announce — via ANY transport (LoRa, WiFi, TCP) — learns the Ygg address and can optionally add the peer.

**Current app_data structure**: capabilities bitmap (one or two bytes).

**Extended app_data**: needs to remain compact (RNS announce overhead matters on LoRa). Options:

**Option A: Fixed-length extension**
```
[capabilities_bytes][ygg_present_flag][ygg_address_16_bytes]
```
Ygg IPv6 addresses are 16 bytes. Total addition: 17 bytes per announce. Acceptable — LoRa can carry this.

**Option B: TLV (type-length-value)**
More extensible but heavier. Overkill for current needs.

**Option C: Only in capabilities bitmap**
A `CAPABILITY_YGGDRASIL` bit signals "I have Ygg, ask me for the address." Interested nodes then do a DirectLink `/meta` request to get the actual address. Minimizes announce overhead but adds a round-trip.

**Recommendation: Option A with a feature flag**
Add `ygg_address: bytes | None` (16 bytes, raw IPv6) to the announce app_data only when Yggdrasil is running. Receiving nodes that understand the format extract it; older nodes see unknown bytes and ignore them if we handle versioning correctly in app_data parsing.

The CAPABILITY_YGGDRASIL bit (already in the capabilities bitmap framework) signals presence, and the address bytes follow the capabilities section. Parsers that don't know about it stop at the capabilities bytes — safe.

**Implementation touch points**:
- `services/reticulum.py`: announce construction — add Ygg address bytes if YggdrasilService is running
- `services/reticulum.py`: announce parsing — extract Ygg address bytes if present
- `models/mesh_device.py`: add `ygg_address: str | None` field to MeshDevice
- `node_store.py`: persist the field
- `YggdrasilService.add_peer()`: called when a new announce with Ygg address arrives (if `bootstrap_from_rns=True`)

### Option C flow: CAPABILITY bit → /meta request → add_peer



### Security properties of ephemeral peer model



### Eager vs lazy: config model and code path divergence



## Decisions

### Decision: Hybrid deployment model: NixOS delegates to system, others use managed process

**Status:** decided
**Rationale:** Matches existing BATMAN/WireGuard pattern. NixOS uses services.yggdrasil (declarative, system-managed). OCI container bundles binary and YggdrasilService manages process. PyPI install detects binary or guides install via doctor. YggdrasilService always communicates via admin socket — process management is optional and detected.

### Decision: RNS announces carry Ygg address (16 raw bytes) when Yggdrasil is running

**Status:** exploring
**Rationale:** Lowest-friction Ygg bootstrapping — every RNS announce passively distributes Ygg addresses to all reachable nodes. 16 bytes is acceptable overhead even on LoRa. A CAPABILITY_YGGDRASIL bit guards the extension so old parsers ignore it safely. Still need to confirm app_data format extensibility and whether 17 bytes affects LoRa MTU constraints.

### Decision: CAPABILITY_YGGDRASIL bit only in announces — address fetched via DirectLink /meta

**Status:** decided
**Rationale:** Option C. LoRa-only nodes must not be drowned by inflated app_data on every announce from every Yggdrasil-capable node. The capability bit is a single bit cost — negligible. Interested nodes then open a DirectLink /meta request to fetch the Ygg address. This is a deliberate round-trip: only nodes that actually want to peer make the request, rather than every node being forced to receive 16 bytes they may never use. Bandwidth on constrained transports belongs to real data, not network metadata.

### Decision: Yggdrasil peers discovered via RNS are ephemeral — no persistence across daemon restarts

**Status:** decided
**Rationale:** Trust is re-established from first principles on every restart, not assumed from a cached roster. Re-bootstrapping via the RNS virtuous cycle is the intended behavior — nodes re-announce, the CAPABILITY_YGGDRASIL bit is seen, /meta is requested, peers are re-added. Persisting peer lists introduces a class of vulnerabilities: stale entries for revoked/rotated keys, replay of old peer relationships, and the temptation to skip re-validation for speed. Aggressive reconnection caching is where security holes hide. The round-trip cost on restart is the correct price for maintaining integrity.

### Decision: Eager vs lazy /meta fetch is config-controlled: yggdrasil.peer_discovery = eager | lazy

**Status:** decided
**Rationale:** Eager (default): CAPABILITY_YGGDRASIL in any announce immediately triggers a /meta fetch and add_peer() call. Best for TCP/WiFi-connected nodes where a DirectLink round-trip is cheap. Lazy: /meta fetch deferred until a VPN handshake is actively being initiated for that peer. Best for LoRa-primary deployments where any unsolicited DirectLink open costs radio time. The operator knows their transport mix — this is a deliberate deployment-time choice, not a runtime heuristic. Default is eager because most non-LoRa nodes benefit from ambient mesh extension without explicit action.

### Decision: Option A (raw Ygg address bytes in announces) rejected

**Status:** rejected
**Rationale:** Superseded by Option C decision. LoRa bandwidth preservation takes priority. 17 bytes per announce from every Ygg-capable node would drown LoRa-only nodes in overhead they cannot use and cannot opt out of.

### Decision: manage_process: bool superseded — YggdrasilConfig.mode: DaemonMode replaces it

**Status:** decided
**Rationale:** The three-tier DaemonMode (DISABLED/ADOPT/MANAGED) pattern was established as universal across all optional daemons. YggdrasilConfig.manage_process (bool) was a two-state approximation that missed the ADOPT case cleanly. Replace with mode: DaemonMode = DaemonMode.DISABLED. YggdrasilAdapter subclasses DaemonAdapter. warm_up_seconds = 30.0 (fast, unlike i2pd's 480s).

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/yggdrasil.py` (new) — YggdrasilService: process lifecycle (optional), admin socket JSON-RPC, get_local_address(), add_peer() (ephemeral, socket-only), get_peers(), is_running property
- `src/styrened/models/config.py` (modified) — Add YggdrasilConfig dataclass: enabled, manage_process, binary_path, listen_port, admin_socket, multicast, bootstrap_from_rns, initial_peers. Add to CoreConfig.
- `src/styrened/models/mesh_device.py` (modified) — Add ygg_address: str | None field to MeshDevice
- `src/styrened/models/capabilities.py` (modified) — Add CAPABILITY_YGGDRASIL bit to capabilities bitmap
- `src/styrened/rpc/server.py` (modified) — _gather_meta() adds ygg_address + ygg_port fields when YggdrasilService is running
- `src/styrened/services/reticulum.py` (modified) — announce construction: set CAPABILITY_YGGDRASIL bit if ygg running. announce parsing: read ygg_address from MeshDevice, store in node. On CAPABILITY_YGGDRASIL announce: trigger /meta fetch (eager or lazy, TBD).
- `src/styrened/services/mesh_vpn.py` (modified) — _detect_yggdrasil_endpoint() via YggdrasilService.local_address. PeerInfo gains ygg_endpoint field. _select_peer_endpoint() prefers ygg over clearnet. On handshake: call ygg_service.add_peer() with remote's ygg address.
- `src/styrened/services/doctor.py` (modified) — Check for Yggdrasil binary presence, running state, admin socket accessibility. Surface in styrened doctor output.
- `src/styrened/daemon.py` (modified) — Instantiate YggdrasilService if config.yggdrasil.enabled. Pass to MeshVPNService. Pass to _gather_meta().
- `styrene-edge/sbc/common/yggdrasil.nix` (new) — NixOS services.yggdrasil module: persistentKeys, AdminListen at known socket path, multicast enabled, empty initial Peers list (styrened manages at runtime via admin socket).

### Constraints

- YggdrasilService.add_peer() is pure admin socket — never writes to yggdrasil.conf. Ephemeral by design.
- CAPABILITY_YGGDRASIL bit is the only announce-level signal. No address bytes in app_data.
- /meta response includes ygg_address only when Yggdrasil is running — receivers must handle absent field.
- Linux-only, same as MeshVPNService. platform.system() guard.
- YggdrasilService is optional — all callers must handle ygg_service=None gracefully.
- Static initial_peers in YggdrasilConfig ARE written to yggdrasil.conf — operator-intentional trust, not dynamic inference.
- peer_discovery=eager: _bootstrap_ygg_peer() fired as asyncio.create_task from announce handler — non-blocking, silent failure, retry on next announce cycle
- peer_discovery=lazy: /meta fetch happens inside initiate_handshake() before building WG payload — adds one round-trip to handshake but only when handshake is explicitly requested
- bootstrap_from_rns=false overrides peer_discovery entirely — no automatic fetching in either mode
- Per-interface peer_discovery granularity explicitly rejected — operator knows deployment profile at config time, RNS doesn't cleanly expose which interface an announce arrived on

## Config model

```python
from enum import Enum

class YggPeerDiscovery(str, Enum):
    EAGER = "eager"   # fetch /meta on every CAPABILITY_YGGDRASIL announce
    LAZY  = "lazy"    # fetch /meta only when initiating a VPN handshake

@dataclass
class YggdrasilConfig:
    enabled: bool = False
    manage_process: bool = True
    binary_path: str = "yggdrasil"
    listen_port: int = 9001
    admin_socket: str = ""                          # "" = styrene default
    multicast: bool = True
    bootstrap_from_rns: bool = True
    peer_discovery: YggPeerDiscovery = YggPeerDiscovery.EAGER  # ← new
    initial_peers: list[str] = field(default_factory=list)
```

YAML surface:
```yaml
yggdrasil:
  enabled: true
  peer_discovery: eager    # or: lazy
  initial_peers:
    - "tcp://[200:hub::1]:9001"
```

## Code path divergence

**Eager path** — lives in `services/reticulum.py` announce handler:
```python
async def _handle_announce(self, destination, announced_identity, app_data, is_path_response):
    ...
    device = self._parse_app_data(app_data, announced_identity)
    
    # NEW: eager Ygg peer bootstrapping
    if (device.capabilities & CAPABILITY_YGGDRASIL
            and self._ygg_service
            and self._ygg_service.is_running
            and self._config.yggdrasil.bootstrap_from_rns
            and self._config.yggdrasil.peer_discovery == YggPeerDiscovery.EAGER):
        asyncio.create_task(self._bootstrap_ygg_peer(destination.hash))
```

```python
async def _bootstrap_ygg_peer(self, identity_hash: str) -> None:
    """Fetch Ygg address via DirectLink /meta and add as peer."""
    try:
        response = await self._direct_link.request(
            identity_hash, "/meta", {}, timeout=15.0
        )
        ygg_addr = response.get("ygg_address")
        ygg_port = response.get("ygg_port", 9001)
        if ygg_addr:
            await self._ygg_service.add_peer(ygg_addr, ygg_port)
    except Exception as e:
        logger.debug(f"Ygg peer bootstrap failed for {identity_hash[:16]}: {e}")
        # Silent failure — the node may be unreachable via DirectLink right now.
        # They'll re-announce and we'll try again.
```

**Lazy path** — lives in `services/mesh_vpn.py` handshake initiation:
```python
async def initiate_handshake(self, target_hash: str, timeout: float = 30.0) -> PeerInfo | None:
    # NEW: lazy Ygg fetch before building our handshake payload
    ygg_endpoint = None
    if (self._ygg and self._ygg.is_running
            and self._config.yggdrasil.peer_discovery == YggPeerDiscovery.LAZY):
        meta = await self._direct_link.request(target_hash, "/meta", {}, timeout=10.0)
        remote_ygg = meta.get("ygg_address")
        if remote_ygg:
            await self._ygg.add_peer(remote_ygg, meta.get("ygg_port", 9001))
            # Now that Ygg is peered, our Ygg endpoint is usable for WG
    
    ygg_endpoint = await self._detect_yggdrasil_endpoint(self.config.port)
    endpoint = self.config.endpoint or self._detect_local_endpoint(self.config.port)
    ...
```

## Why not a per-interface flag?

The temptation would be to make this per-RNS-interface (e.g., eager on TCP interfaces, lazy on LoRa interfaces). But RNS doesn't expose which interface an announce arrived on in a clean way — path resolution is an internal detail. The operator knows their deployment profile at config time. A node that's LoRa-primary knows to set `lazy`; a hub with TCP-only connectivity knows to set `eager`. Interface-level granularity would add significant complexity for marginal benefit.

## Interaction with bootstrap_from_rns

`bootstrap_from_rns: bool` is the master switch — if False, no automatic /meta fetching happens in either mode. `peer_discovery` only applies when `bootstrap_from_rns: true`. This gives three meaningful states:

| bootstrap_from_rns | peer_discovery | Behavior |
|--------------------|----------------|----------|
| false | — | Manual only. Only initial_peers and explicit calls. |
| true | eager | Fetch /meta on every CAPABILITY_YGGDRASIL announce. |
| true | lazy | Fetch /meta only during VPN handshake initiation. |

## Why ephemeral is the right security posture

The restart-as-trust-reset pattern has deep precedent in security engineering. Every session is a fresh attestation. The alternative — persisting peer relationships and re-establishing them automatically on restart — is exactly the class of "optimization" that creates:

**Stale credential acceptance**: A persisted peer entry for a node whose Yggdrasil keypair rotated (legitimate key rotation, or compromise response) would mean styrened reconnects to an address that may now be controlled by a different identity. The old Ygg address might be reassigned or reused.

**Revocation blindness**: If Node A is removed from the RBAC roster (BLOCKED, kicked from enclave), its persisted Ygg peer entry in Node B's yggdrasil.conf would still allow Yggdrasil-layer connectivity. The RBAC gate is at the DirectLink/LXMF layer — but Yggdrasil itself doesn't know about styrene RBAC. A cached peer entry bypasses the RNS/RBAC path that would normally gate re-introduction.

**The virtuous cycle handles restart cost correctly**: After a daemon restart, RNS announces resume. Any online node with CAPABILITY_YGGDRASIL re-broadcasts within the normal announce interval. The /meta fetch happens, the peer is added. The delay is bounded by the announce interval (typically 60–300s). This is acceptable — the mesh is recovering, not failing.

**Initial peers list (static config) is the one exception**: `YggdrasilConfig.initial_peers` can contain static well-known peers (e.g., the public hub's Ygg address). These ARE written to `yggdrasil.conf` at startup — they're a deliberate, operator-configured trust decision, not a dynamic inference. The distinction:
- Dynamic RNS-discovered peers: ephemeral, re-bootstrapped each session
- Static configured peers: persistent, operator-intentional

This maps exactly to how SSH `known_hosts` works: you explicitly add trusted hosts, session keys are ephemeral.

## What "ephemeral" means in practice for YggdrasilService

On `start()`: load initial_peers from config → write to yggdrasil.conf → start daemon.

At runtime: `add_peer()` calls the admin socket `addPeer`. This is in-memory only — Yggdrasil holds it for the lifetime of the process. Not written back to yggdrasil.conf.

On `stop()`: the in-memory peer list evaporates. yggdrasil.conf still only contains initial_peers.

On next `start()`: begin with only initial_peers. RNS re-bootstraps the rest.

Implementation consequence: `add_peer()` never touches the filesystem. It is purely an admin socket call. This is simpler, not more complex — no file write, no parse, no merge logic needed.

## The full discovery flow with Option C

```
Node A (Yggdrasil running)
  → RNS announce: capabilities bitmap has CAPABILITY_YGGDRASIL set
  → app_data size: unchanged from today

Node B (hears announce, wants to peer)
  → detects CAPABILITY_YGGDRASIL in announce
  → opens DirectLink to Node A
  → sends GET /meta
  → Node A responds: { "styrene_version": "...", "capabilities": [...], 
                        "ygg_address": "200:dead:beef::1",
                        "ygg_port": 9001 }
  → Node B calls YggdrasilService.add_peer("200:dead:beef::1", 9001)
  → Yggdrasil TCP connection established between the two nodes
```

## What this requires from /meta

The `/meta` endpoint already exists and returns `styrene_version`, `profile`, `capabilities`, `arch`, `os_id`. It uses `ALLOW_ALL` — no RBAC gate, accessible to any node that can open a DirectLink.

The addition is minimal:
```python
def _gather_meta(config: CoreConfig) -> dict:
    return {
        "styrene_version": __version__,
        "profile": config.profile,
        "capabilities": [...],
        "arch": platform.machine(),
        "os_id": platform.system().lower(),
        # NEW — only present if Yggdrasil is running:
        "ygg_address": ygg_service.local_address if ygg_service else None,
        "ygg_port": config.yggdrasil.listen_port if ygg_service else None,
    }
```

`ygg_address` is None (or absent) when Yggdrasil isn't running. Receivers must handle both cases. The CAPABILITY_YGGDRASIL bit being set guarantees the field will be present and non-null — so the bit is the guard, not the null check.

## When does Node B initiate the /meta request?

Two trigger points:

**1. On announce receipt** — when `_handle_announce()` in `services/reticulum.py` sees CAPABILITY_YGGDRASIL in a new node's capabilities, and `config.yggdrasil.bootstrap_from_rns` is True, and we have Yggdrasil running locally. This is the passive ambient bootstrapping path.

**2. On VPN handshake initiation** — when `MeshVPNService.initiate_handshake()` is called for a target that has CAPABILITY_YGGDRASIL, fetch their Ygg address from /meta first, include our Ygg address in the handshake payload. This is the active mesh-extension path.

## Why /meta and not a new dedicated endpoint

`/meta` is already `ALLOW_ALL` — no DirectLink RBAC gating required. Creating a `/ygg` endpoint would require registering it in `DirectLinkService`, adding RBAC config, etc. The Ygg address is genuinely metadata about the node — it belongs in /meta alongside `arch` and `os_id`. Zero new endpoints needed.

## One subtlety: DirectLink requires an existing RNS path

Option C adds one round-trip (announce → DirectLink /meta request). That DirectLink requires the two nodes to have an RNS path to each other — either direct or via a hub. This is always true for nodes that share a hub enclave or have a direct RNS link. For truly disconnected nodes, the announce itself couldn't have been received.

The only edge case: a node heard an announce via a propagation store (delayed delivery). In that case, the originating node may no longer be reachable for a DirectLink. The capability bit is noted in the MeshDevice record; the /meta fetch is deferred until a live path is available. This is consistent with how other DirectLink features work — you can't speedtest a node you can't currently reach.

## NixOS (styrene-edge)

NixOS has a first-class `services.yggdrasil` module. The question is: do we use it, or does styrened manage its own process?

**Option A: Use system `services.yggdrasil`**
```nix
# styrene-edge/sbc/common/yggdrasil.nix
services.yggdrasil = {
  enable = true;
  persistentKeys = true;  # keys survive rebuild
  settings = {
    Listen = ["tcp://0.0.0.0:9001"];
    AdminListen = "unix:///var/run/yggdrasil/yggdrasil.sock";
    MulticastInterfaces = [{
      Regex = ".*";
      Beacon = true;
      Listen = true;
    }];
    # Peers populated by styrened at runtime via admin socket
  };
};
```
YggdrasilService in this case is **management-only** — no process lifecycle, just admin socket queries. Cleaner separation. Aligns with BATMAN-ADV model.

Pros: System manages uptime, log rotation, restart policy. Keys are NixOS-managed (reproducible). No subprocess management complexity.  
Cons: Peers can't be added dynamically to the NixOS config (must use admin socket, which works fine). Configuration changes require rebuild.

**Option B: styrened manages its own yggdrasil process**
Useful for non-NixOS installs (Debian, Raspberry Pi OS, OCI container). Full autonomy. Mirrors WireGuard approach.

**Recommendation**: Hybrid approach matching the existing pattern:
- NixOS: system `services.yggdrasil` (like BATMAN-ADV). `yggdrasil.nix` in styrene-edge. YggdrasilService = admin socket only.
- OCI container: bundle binary, YggdrasilService manages process.
- Other Linux: optional managed process, or detect system installation.

The `YggdrasilService` abstracts this: it tries the admin socket first (detecting a system or already-running instance), and only starts its own process if the socket is absent and `manage_process: true` in config.

## OCI container

The `nix build .#oci` derivation needs `yggdrasil` in its package set. Single Go binary, statically linked, cross-compiles for arm64/amd64. Add to the flake:

```nix
# flake.nix
packages = {
  oci = pkgs.dockerTools.buildImage {
    contents = with pkgs; [ styrened yggdrasil wireguard-tools ... ];
  };
};
```

Container needs `--cap-add NET_ADMIN` and `/dev/net/tun` device for Yggdrasil to create its TUN interface. Same requirement as WireGuard — already needed. No new container capability needed.

## Config model

```python
@dataclass
class YggdrasilConfig:
    enabled: bool = False
    manage_process: bool = True          # False if using system yggdrasil
    binary_path: str = "yggdrasil"       # or /nix/store/.../bin/yggdrasil
    listen_port: int = 9001
    admin_socket: str = ""               # "" = use styrene default
    multicast: bool = True               # LAN peer discovery
    bootstrap_from_rns: bool = True      # Add peers discovered via RNS
    initial_peers: list[str] = field(default_factory=list)  # static peers
```

Integrated into `CoreConfig` similarly to `relay: RelayConfig` and `mesh_vpn: MeshVPNConfig`.

## What YggdrasilService should own

**1. Keypair and config generation**
```
~/.styrene/yggdrasil_private_key   # hex, generated once, stable identity
~/.styrene/yggdrasil.conf          # generated config file
```
Config template:
```json
{
  "PrivateKey": "<hex>",
  "Listen": ["tcp://0.0.0.0:9001"],
  "AdminListen": "unix:///tmp/styrene-yggdrasil.sock",
  "Peers": [],        # managed dynamically at runtime
  "AllowedPublicKeys": [],
  "MulticastInterfaces": [{"Regex": ".*", "Beacon": true, "Listen": true}]
}
```
Note: `AdminListen` uses a styrene-owned socket path, not the system default. This avoids conflicts when system Yggdrasil is also running.

**2. Process lifecycle**
- `start()`: spawn `yggdrasil -useconf < yggdrasil.conf` as async subprocess, capture stdout/stderr
- `stop()`: SIGTERM the subprocess
- `restart()`: stop + start
- Health check: poll admin socket, restart if unresponsive

**3. Admin socket interface**
All Yggdrasil runtime management via JSON-RPC on the Unix socket:
- `getSelf` → local IPv6 address + public key
- `addPeer` / `removePeer` → dynamic peer management
- `getPeers` → current peer list + connectivity status
- `getDHT` → routing table (useful for mesh visualization)

**4. Peer management via RNS discovery**
When styrened learns a remote node's Ygg address (via handshake or announce app_data), call `addPeer` to extend the Ygg mesh. This is the "RNS bootstraps Yggdrasil" loop.

## What YggdrasilService does NOT own

**Binary acquisition**: Don't bundle the binary. Three deployment contexts:
- **NixOS (styrene-edge)**: `services.yggdrasil` NixOS module handles the binary. YggdrasilService detects the system instance OR starts its own with the nix-provided binary.
- **OCI container**: Include `yggdrasil` binary in the Nix OCI derivation (it's a single Go binary, ~10MB). Add to `nix build .#oci` inputs.
- **PyPI install**: Require user to install yggdrasil separately. `styrened doctor` checks for the binary and guides installation.

**OS-level routing**: Yggdrasil manages its own TUN interface and routing. YggdrasilService doesn't touch routing tables.

## Service interface exposed to the rest of styrened

```python
class YggdrasilService:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    
    async def get_local_address(self) -> str | None:
        """Return local Ygg IPv6 address, or None if not running."""
    
    async def get_local_public_key(self) -> str | None:
        """Return local Ygg public key (hex)."""
    
    async def add_peer(self, address: str, port: int = 9001) -> bool:
        """Add a discovered RNS peer to Yggdrasil. Returns success."""
    
    async def get_peers(self) -> list[YggPeer]:
        """List currently connected Yggdrasil peers with RTT."""
    
    @property
    def is_running(self) -> bool: ...
    
    @property  
    def local_address(self) -> str | None:
        """Cached local address, updated at startup."""
```

## Interaction with MeshVPNService

MeshVPNService gets a reference to YggdrasilService (optional, None if disabled):
```python
class MeshVPNService:
    def __init__(self, ..., yggdrasil: YggdrasilService | None = None):
        self._ygg = yggdrasil
    
    async def _detect_yggdrasil_endpoint(self, port: int) -> str | None:
        if self._ygg and self._ygg.is_running:
            addr = self._ygg.local_address
            return f"[{addr}]:{port}" if addr else None
        # Fallback: probe admin sockets if externally managed
        return await _probe_external_yggdrasil(port)
```

When handshake completes and remote has Ygg address, MeshVPNService calls `self._ygg.add_peer(remote_ygg_addr)` to bootstrap the Ygg connection.
