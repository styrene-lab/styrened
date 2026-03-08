# YggdrasilService — Tasks

**Dependency**: `optional-daemon-adoption-model` OpenSpec must be implemented first.
`YggdrasilAdapter` subclasses `DaemonAdapter` from `src/styrened/services/daemon_adapter.py`.
`YggdrasilConfig.mode: DaemonMode` replaces the earlier `manage_process: bool` design.

---

## Group 1: `YggdrasilAdapter` (`src/styrened/services/yggdrasil.py`)

- [ ] 1.1 Implement `YggdrasilAdapter(DaemonAdapter)` with `warm_up_seconds = 30.0`
- [ ] 1.2 Implement `_generate_yggdrasil_conf()` — writes `~/.styrene/yggdrasil/yggdrasil.conf` with: listen port 9002 (managed; avoids clash with system Yggdrasil on 9001), admin socket `~/.styrene/yggdrasil/yggdrasil.sock`, `initial_peers` from config, multicast settings. Calls `_ensure_config_dir()` from base class for `0700`/`0600` enforcement.
- [ ] 1.3 Implement `_start_managed()` — check binary at `config.binary_path` exists; fail fast with clear error if not (do NOT provision at start time). Call `_generate_yggdrasil_conf()`. Spawn subprocess capturing stdout/stderr to logger.
- [ ] 1.4 Implement `_stop_managed()` — SIGTERM, wait up to 5s, SIGKILL if still running
- [ ] 1.5 Implement `_probe()` — try admin socket paths in order: `~/.styrene/yggdrasil/yggdrasil.sock` first (MANAGED), then `/var/run/yggdrasil/yggdrasil.sock`, `/run/yggdrasil.sock`, `/tmp/yggdrasil.sock` (ADOPT). Return True if any responds to a `getSelf` call.
- [ ] 1.6 Implement `_admin_call(method: str, params: dict = {}) -> dict` — JSON-RPC over Unix socket with configurable timeout. Raise on connection failure or malformed response.
- [ ] 1.7 Implement `_gather_details() -> dict` — `getSelf` for address, `getPeers` for peer count. Returns `{"address": str, "peer_count": int}`.
- [ ] 1.8 Implement `get_local_address() -> str | None` — returns `_cached_details.get("address")` from base class cache, or None
- [ ] 1.9 Implement `add_peer(address: str, port: int = 9001) -> bool` — admin socket `addPeer` only. Never writes to yggdrasil.conf. Ephemeral by design.
- [ ] 1.10 Implement `provision()` — checks binary in PATH / Nix store. If missing: print human-readable instructions for `nix profile install nixpkgs#yggdrasil`. Does NOT install automatically.
- [ ] 1.11 Write unit tests: probe succeeds/fails per socket path order, `add_peer` calls socket and does NOT touch filesystem, `get_local_address` returns from cache, `_start_managed` fails fast on missing binary, config dir `0700` enforced, key file `0600` enforced

## Group 2: `models/capabilities.py` and `models/mesh_device.py`

- [ ] 2.1 Add `CAPABILITY_YGGDRASIL` bit to capabilities bitmap
- [ ] 2.2 Add `ygg_address: str | None = None` field to `MeshDevice`
- [ ] 2.3 Update `node_store` to persist/retrieve `ygg_address`
- [ ] 2.4 Write unit tests: capability bit round-trips through announce encode/decode, `MeshDevice` field persists

## Group 3: Announce integration (`src/styrened/services/reticulum.py`)

- [ ] 3.1 In announce construction: set `CAPABILITY_YGGDRASIL` bit in capabilities bitmap if `YggdrasilAdapter.is_running`. No address bytes in app_data — capability bit only.
- [ ] 3.2 In announce parsing: detect `CAPABILITY_YGGDRASIL` in received capabilities, store on `MeshDevice.ygg_address = None` (address unknown until /meta fetch)
- [ ] 3.3 Implement `_bootstrap_ygg_peer(identity_hash: str)` — async, fetches `/meta` via DirectLink, extracts `ygg_address` + `ygg_port`, calls `YggdrasilAdapter.add_peer()`. Silent on failure — retry on next announce cycle.
- [ ] 3.4 In announce handler: if `CAPABILITY_YGGDRASIL` set AND `config.yggdrasil.bootstrap_from_rns=True` AND `config.yggdrasil.peer_discovery == EAGER` AND local Yggdrasil running → `asyncio.create_task(_bootstrap_ygg_peer(hash))`. Non-blocking.
- [ ] 3.5 Write unit tests: eager path fires task on CAPABILITY_YGGDRASIL announce, lazy path does NOT fire task, `bootstrap_from_rns=False` suppresses both, silent failure on bootstrap does not propagate

## Group 4: `/meta` response extension (`src/styrened/rpc/server.py`)

- [ ] 4.1 In `_gather_meta(config)`: add `"ygg_address"` and `"ygg_port"` fields when `YggdrasilAdapter.is_running`. Omit both fields (not null) when Yggdrasil not running — receivers check key presence, not null.
- [ ] 4.2 Write unit tests: `ygg_address` present when adapter running, fields absent (not null) when adapter not running

## Group 5: Handshake extension (`src/styrened/services/mesh_vpn.py`)

- [ ] 5.1 Add `ygg_endpoint: str | None = None` to `PeerInfo` dataclass
- [ ] 5.2 Extend `build_handshake_request()` and `build_handshake_response()` to include `"ygg_endpoint"` field. Empty string when unknown (consistent with existing `"endpoint"` field pattern).
- [ ] 5.3 Extend `parse_handshake_request()` and `parse_handshake_response()` to extract `ygg_endpoint` via `.get()` — backward-compatible, old senders omit field.
- [ ] 5.4 Implement `_detect_yggdrasil_endpoint(port: int) -> str | None` — delegates to `YggdrasilAdapter.get_local_address()` if adapter present and running, else probes external admin sockets (same path order as `_probe()`). Returns `"[addr]:port"` IPv6 format or None.
- [ ] 5.5 Implement `_select_peer_endpoint(peer: PeerInfo) -> str | None` — prefers `peer.ygg_endpoint` if set AND local Yggdrasil running, else `peer.endpoint`, else None.
- [ ] 5.6 In `initiate_handshake()`: if `peer_discovery == LAZY` and target has `CAPABILITY_YGGDRASIL`, fetch `/meta` before building payload, call `add_peer()` if ygg_address found. Then detect local ygg endpoint for our payload.
- [ ] 5.7 In `handle_handshake_response()` / `_add_wireguard_peer()`: use `_select_peer_endpoint()` for WG peer endpoint. Call `add_peer()` with remote's `ygg_address` if present.
- [ ] 5.8 Write unit tests: ygg_endpoint preferred over clearnet, clearnet fallback when no Ygg, None endpoint handled, backward-compat with old handshake missing ygg_endpoint field, lazy fetch fires on LAZY mode, lazy fetch suppressed on EAGER mode

## Group 6: `doctor.py` and `styrened setup` CLI

- [ ] 6.1 Add Yggdrasil check in `doctor.py`: DISABLED → skip. ADOPT + not found → WARNING. ADOPT + found → OK with address/peers. MANAGED + binary missing → ERROR + setup hint. MANAGED + running → OK.
- [ ] 6.2 Add `setup --enable yggdrasil` to CLI: calls `YggdrasilAdapter.provision()`, updates config `yggdrasil.mode = managed`, saves.
- [ ] 6.3 Write unit tests covering all mode × running state combinations for doctor output

## Group 7: NixOS (`styrene-edge/sbc/common/yggdrasil.nix`)

- [ ] 7.1 Add `yggdrasil.nix` module: `services.yggdrasil.enable`, `persistentKeys = true`, `AdminListen` at `/var/run/yggdrasil/yggdrasil.sock`, multicast enabled, empty `Peers` list (styrened manages at runtime via admin socket)
- [ ] 7.2 Document that NixOS deployments should use `mode: adopt` in styrened config — system `services.yggdrasil` is the managed instance, styrened adopts it
