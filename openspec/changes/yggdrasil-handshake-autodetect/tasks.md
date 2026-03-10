# Yggdrasil VPN Handshake Auto-detection — Tasks

**Dependency**: `yggdrasil-service` OpenSpec (Groups 1–4) must be implemented first.
`_detect_yggdrasil_endpoint()` and `_select_peer_endpoint()` are implemented in this change.
`PeerInfo.ygg_endpoint` field and handshake wire format changes are also in this change.

**Note**: Tasks 5.1–5.8 in `yggdrasil-service` tasks.md cover the same `mesh_vpn.py` work.
These two OpenSpec changes should be merged into a single cleave execution to avoid conflicts.
The tasks below are the canonical authoritative list for `mesh_vpn.py`.

---

## Group 1: `PeerInfo` and handshake wire format (`src/styrened/services/mesh_vpn.py`)

- [x] 1.1 Add `ygg_endpoint: str | None = None` to `PeerInfo` dataclass
- [x] 1.2 Extend `build_handshake_request()` — add `"ygg_endpoint"` to JSON payload. Use `""` when None (consistent with existing `"endpoint"` field).
- [x] 1.3 Extend `build_handshake_response()` — same as 1.2
- [x] 1.4 Extend `parse_handshake_request()` — extract `payload.get("ygg_endpoint") or None`. Backward-compatible: missing key → None.
- [x] 1.5 Extend `parse_handshake_response()` — same as 1.4
- [x] 1.6 Write unit tests: round-trip encode/decode with ygg_endpoint present, round-trip without (old sender), empty string normalised to None on parse

## Group 2: Endpoint detection (`src/styrened/services/mesh_vpn.py`)

- [x] 2.1 Implement `_detect_yggdrasil_endpoint(port: int) -> str | None`:
  - If `self._ygg` (YggdrasilAdapter) is present and running: use `self._ygg.get_local_address()`
  - Else: probe admin socket paths in order (`~/.styrene/yggdrasil/yggdrasil.sock`, `/var/run/yggdrasil/yggdrasil.sock`, `/run/yggdrasil.sock`) via `_admin_call("getSelf")`
  - Return `f"[{address}]:{port}"` or None. Use IPv6 bracket notation.
- [x] 2.2 Implement `_detect_local_endpoint_v4(port: int) -> str | None` — rename existing `_detect_local_endpoint` for clarity (IPv4 UDP socket trick). Keep behaviour identical.
- [x] 2.3 Write unit tests: ygg adapter path used when available, socket probe fallback when adapter absent, None returned when both fail, IPv6 bracket format correct

## Group 3: Endpoint selection (`src/styrened/services/mesh_vpn.py`)

- [x] 3.1 Implement `_select_peer_endpoint(peer: PeerInfo) -> str | None`:
  - If `peer.ygg_endpoint` is set AND local Yggdrasil is running (`self._ygg and self._ygg.is_running` or local address detected): return `peer.ygg_endpoint`
  - Else: return `peer.endpoint or None`
- [x] 3.2 Replace all direct `peer.endpoint` references in `_add_wireguard_peer()` with `_select_peer_endpoint(peer)`
- [x] 3.3 Write unit tests: ygg preferred when both sides have it, clearnet fallback when remote has no ygg_endpoint, clearnet fallback when local Ygg not running, None endpoint handled (roaming WG mode)

## Group 4: Handshake initiation and response (`src/styrened/services/mesh_vpn.py`)

- [x] 4.1 In `initiate_handshake()`:
  - Detect local ygg endpoint: `ygg_ep = await self._detect_yggdrasil_endpoint(self.config.port)`
  - If `peer_discovery == LAZY` and target `MeshDevice.capabilities` has `CAPABILITY_YGGDRASIL`: fetch `/meta` from target via DirectLink, extract `ygg_address`, call `self._ygg.add_peer()`. Then re-detect ygg_ep (now available).
  - Pass `ygg_endpoint=ygg_ep` to `build_handshake_request()`
- [x] 4.2 In `handle_handshake_response()`: after parsing, call `self._ygg.add_peer(peer.ygg_address)` if remote's ygg_address is in /meta (fetched during handshake). Use `_select_peer_endpoint(peer)` for WG config.
- [x] 4.3 In `handle_handshake_request()`: include local ygg_endpoint in response payload.
- [x] 4.4 Write unit tests: lazy fetch fires when LAZY+CAPABILITY_YGGDRASIL, no fetch when EAGER (reticulum.py handles that), local ygg_ep included in both request and response payloads, add_peer called after successful handshake

## Group 5: `MeshVPNService` initialisation (`src/styrened/daemon.py`)

- [x] 5.1 Pass `YggdrasilAdapter` instance to `MeshVPNService.__init__()` as optional `ygg: YggdrasilAdapter | None = None`
- [x] 5.2 Store as `self._ygg` in `MeshVPNService`. All Ygg-aware methods guard with `if self._ygg and self._ygg.is_running`
- [x] 5.3 Write unit tests: `MeshVPNService` with `ygg=None` behaves identically to pre-Ygg behaviour (no regressions)
