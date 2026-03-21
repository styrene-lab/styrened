# YggdrasilService — styrened-managed Yggdrasil daemon — Design

## Architecture Decisions

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

### Decision: The raw Ygg-address-in-announce idea is superseded by CAPABILITY_YGGDRASIL plus DirectLink /meta

**Status:** decided
**Rationale:** The node still carries older research text about embedding raw Ygg address bytes into announce app_data. That approach was rejected to preserve constrained-link bandwidth. The active design is capability bit only in announces, with address fetched via /meta when a peer actually wants to bootstrap.

## Research Context

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



### OpenSpec reconciliation note

styrened-side Yggdrasil work is effectively complete through adapter, capability, /meta, announce bootstrap, handshake extension, doctor, and setup CLI. The remaining blocker for closing the broader YggdrasilService effort is the external NixOS module work in styrene-edge (`styrene-edge/sbc/common/yggdrasil.nix`).

### Blocker update (2026-03-20)

The styrene-identity dependency is resolved. The actual remaining work is the NixOS module in styrene-edge (styrene-edge/sbc/common/yggdrasil.nix). styrened-side Yggdrasil work is complete. Keeping blocked status but updating the reason to reflect the real external dependency.

## File Changes

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

## Constraints

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
- File scope is STALE — all referenced Python modules (yggdrasil.py, reticulum.py, mesh_vpn.py, daemon.py, rpc/server.py) were deleted in v0.18.0 daemon removal. Remaining Python-side work (doctor checks, config parsing) is guarded with try/except. Implementation must target the Rust daemon (styrened-rs). External NixOS module (styrene-edge/sbc/common/yggdrasil.nix) is the remaining work outside Rust.
