# YggdrasilService — styrened-managed Yggdrasil daemon — Design Spec (extracted)

> Auto-extracted from docs/yggdrasil-service.md at decide-time.

## Decisions

### Hybrid deployment model: NixOS delegates to system, others use managed process (decided)

Matches existing BATMAN/WireGuard pattern. NixOS uses services.yggdrasil (declarative, system-managed). OCI container bundles binary and YggdrasilService manages process. PyPI install detects binary or guides install via doctor. YggdrasilService always communicates via admin socket — process management is optional and detected.

### RNS announces carry Ygg address (16 raw bytes) when Yggdrasil is running (exploring)

Lowest-friction Ygg bootstrapping — every RNS announce passively distributes Ygg addresses to all reachable nodes. 16 bytes is acceptable overhead even on LoRa. A CAPABILITY_YGGDRASIL bit guards the extension so old parsers ignore it safely. Still need to confirm app_data format extensibility and whether 17 bytes affects LoRa MTU constraints.

### CAPABILITY_YGGDRASIL bit only in announces — address fetched via DirectLink /meta (decided)

Option C. LoRa-only nodes must not be drowned by inflated app_data on every announce from every Yggdrasil-capable node. The capability bit is a single bit cost — negligible. Interested nodes then open a DirectLink /meta request to fetch the Ygg address. This is a deliberate round-trip: only nodes that actually want to peer make the request, rather than every node being forced to receive 16 bytes they may never use. Bandwidth on constrained transports belongs to real data, not network metadata.

### Yggdrasil peers discovered via RNS are ephemeral — no persistence across daemon restarts (decided)

Trust is re-established from first principles on every restart, not assumed from a cached roster. Re-bootstrapping via the RNS virtuous cycle is the intended behavior — nodes re-announce, the CAPABILITY_YGGDRASIL bit is seen, /meta is requested, peers are re-added. Persisting peer lists introduces a class of vulnerabilities: stale entries for revoked/rotated keys, replay of old peer relationships, and the temptation to skip re-validation for speed. Aggressive reconnection caching is where security holes hide. The round-trip cost on restart is the correct price for maintaining integrity.

### Eager vs lazy /meta fetch is config-controlled: yggdrasil.peer_discovery = eager | lazy (decided)

Eager (default): CAPABILITY_YGGDRASIL in any announce immediately triggers a /meta fetch and add_peer() call. Best for TCP/WiFi-connected nodes where a DirectLink round-trip is cheap. Lazy: /meta fetch deferred until a VPN handshake is actively being initiated for that peer. Best for LoRa-primary deployments where any unsolicited DirectLink open costs radio time. The operator knows their transport mix — this is a deliberate deployment-time choice, not a runtime heuristic. Default is eager because most non-LoRa nodes benefit from ambient mesh extension without explicit action.

### Option A (raw Ygg address bytes in announces) rejected (rejected)

Superseded by Option C decision. LoRa bandwidth preservation takes priority. 17 bytes per announce from every Ygg-capable node would drown LoRa-only nodes in overhead they cannot use and cannot opt out of.

### manage_process: bool superseded — YggdrasilConfig.mode: DaemonMode replaces it (decided)

The three-tier DaemonMode (DISABLED/ADOPT/MANAGED) pattern was established as universal across all optional daemons. YggdrasilConfig.manage_process (bool) was a two-state approximation that missed the ADOPT case cleanly. Replace with mode: DaemonMode = DaemonMode.DISABLED. YggdrasilAdapter subclasses DaemonAdapter. warm_up_seconds = 30.0 (fast, unlike i2pd's 480s).

### The raw Ygg-address-in-announce idea is superseded by CAPABILITY_YGGDRASIL plus DirectLink /meta (decided)

The node still carries older research text about embedding raw Ygg address bytes into announce app_data. That approach was rejected to preserve constrained-link bandwidth. The active design is capability bit only in announces, with address fetched via /meta when a peer actually wants to bootstrap.

## Research Summary

### Precedent: how MeshVPNService manages WireGuard and batman-mesh.nix manages BATMAN

**WireGuard management (MeshVPNService)**:
- Generates `/etc/wireguard/wg-styrene.conf` from internal state
- Runs `wg-quick up` / `wg-quick down` to manage the interface
- Calls `wg set` to add/remove peers at runtime without full restart
- Creates VXLAN interfaces via `ip link add vxlan-<peer>` for each peer
- All operations are `asyncio.create_subprocess_exec` calls — no library, raw subprocess
- Manages its own keypair in `~/.styrene/wireguard_private_key`
- Service is only activated on Linu…

### YggdrasilService design: what it owns and what it delegates



### NixOS integration and OCI container story



### Yggdrasil address in RNS announces — extending app_data

The most powerful distribution mechanism: include the local Yggdrasil address in every RNS announce. Any node that hears the announce — via ANY transport (LoRa, WiFi, TCP) — learns the Ygg address and can optionally add the peer.

**Current app_data structure**: capabilities bitmap (one or two bytes).

**Extended app_data**: needs to remain compact (RNS announce overhead matters on LoRa). Options:

**Option A: Fixed-length extension**
```
[capabilities_bytes][ygg_present_flag][ygg_address_16_byt…

### Option C flow: CAPABILITY bit → /meta request → add_peer



### Security properties of ephemeral peer model



### Eager vs lazy: config model and code path divergence



### OpenSpec reconciliation note

styrened-side Yggdrasil work is effectively complete through adapter, capability, /meta, announce bootstrap, handshake extension, doctor, and setup CLI. The remaining blocker for closing the broader YggdrasilService effort is the external NixOS module work in styrene-edge (`styrene-edge/sbc/common/yggdrasil.nix`).

### Blocker update (2026-03-20)

The styrene-identity dependency is resolved. The actual remaining work is the NixOS module in styrene-edge (styrene-edge/sbc/common/yggdrasil.nix). styrened-side Yggdrasil work is complete. Keeping blocked status but updating the reason to reflect the real external dependency.
