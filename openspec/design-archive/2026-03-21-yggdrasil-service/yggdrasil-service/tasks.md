# YggdrasilService — styrened-managed Yggdrasil daemon — Tasks

## 1. src/styrened/services/yggdrasil.py (new)

- [x] 1.1 YggdrasilService: process lifecycle (optional), admin socket JSON-RPC, get_local_address(), add_peer() (ephemeral, socket-only), get_peers(), is_running property
- [x] 1.2 File scope is STALE — all referenced Python modules (yggdrasil.py, reticulum.py, mesh_vpn.py, daemon.py, rpc/server.py) were deleted in v0.18.0 daemon removal. Remaining Python-side work (doctor checks, config parsing) is guarded with try/except. Implementation must target the Rust daemon (styrened-rs). External NixOS module (styrene-edge/sbc/common/yggdrasil.nix) is the remaining work outside Rust.

## 2. src/styrened/models/config.py (modified)

- [x] 2.1 Add YggdrasilConfig dataclass: enabled, manage_process, binary_path, listen_port, admin_socket, multicast, bootstrap_from_rns, initial_peers. Add to CoreConfig.

## 3. src/styrened/models/mesh_device.py (modified)

- [x] 3.1 Add ygg_address: str | None field to MeshDevice

## 4. src/styrened/models/capabilities.py (modified)

- [x] 4.1 Add CAPABILITY_YGGDRASIL bit to capabilities bitmap

## 5. src/styrened/rpc/server.py (modified)

- [x] 5.1 _gather_meta() adds ygg_address + ygg_port fields when YggdrasilService is running

## 6. src/styrened/services/reticulum.py (modified)

- [x] 6.1 announce construction: set CAPABILITY_YGGDRASIL bit if ygg running. announce parsing: read ygg_address from MeshDevice, store in node. On CAPABILITY_YGGDRASIL announce: trigger /meta fetch (eager or lazy, TBD).

## 7. src/styrened/services/mesh_vpn.py (modified)

- [x] 7.1 _detect_yggdrasil_endpoint() via YggdrasilService.local_address. PeerInfo gains ygg_endpoint field. _select_peer_endpoint() prefers ygg over clearnet. On handshake: call ygg_service.add_peer() with remote's ygg address.

## 8. src/styrened/services/doctor.py (modified)

- [x] 8.1 Check for Yggdrasil binary presence, running state, admin socket accessibility. Surface in styrened doctor output.

## 9. src/styrened/daemon.py (modified)

- [x] 9.1 Instantiate YggdrasilService if config.yggdrasil.enabled. Pass to MeshVPNService. Pass to _gather_meta().

## 10. styrene-edge/sbc/common/yggdrasil.nix (new)

- [x] 10.1 NixOS services.yggdrasil module: persistentKeys, AdminListen at known socket path, multicast enabled, empty initial Peers list (styrened manages at runtime via admin socket).

## 11. Cross-cutting constraints

- [x] 11.1 YggdrasilService.add_peer() is pure admin socket — never writes to yggdrasil.conf. Ephemeral by design.
- [x] 11.2 CAPABILITY_YGGDRASIL bit is the only announce-level signal. No address bytes in app_data.
- [x] 11.3 /meta response includes ygg_address only when Yggdrasil is running — receivers must handle absent field.
- [x] 11.4 Linux-only, same as MeshVPNService. platform.system() guard.
- [x] 11.5 YggdrasilService is optional — all callers must handle ygg_service=None gracefully.
- [x] 11.6 Static initial_peers in YggdrasilConfig ARE written to yggdrasil.conf — operator-intentional trust, not dynamic inference.
- [x] 11.7 peer_discovery=eager: _bootstrap_ygg_peer() fired as asyncio.create_task from announce handler — non-blocking, silent failure, retry on next announce cycle
- [x] 11.8 peer_discovery=lazy: /meta fetch happens inside initiate_handshake() before building WG payload — adds one round-trip to handshake but only when handshake is explicitly requested
- [x] 11.9 bootstrap_from_rns=false overrides peer_discovery entirely — no automatic fetching in either mode
- [x] 11.10 Per-interface peer_discovery granularity explicitly rejected — operator knows deployment profile at config time, RNS doesn't cleanly expose which interface an announce arrived on
