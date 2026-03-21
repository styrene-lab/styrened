# Yggdrasil auto-detection in VPN handshake — Design Spec (extracted)

> Auto-extracted from docs/yggdrasil-handshake-autodetect.md at decide-time.

## Decisions

### Ygg endpoint detection: admin socket first, interface scan fallback (decided)

The admin socket gives the canonical self-address from Yggdrasil's own routing state. Interface scan is a fallback for when the admin socket isn't accessible (external Ygg not yet running, permissions, etc). Never shell out to yggdrasilctl — too brittle in containers. The socket path is known if YggdrasilService manages the daemon; probe common paths otherwise.

### Ygg endpoint wins over clearnet in WG peer selection (decided)

Yggdrasil addresses are stable (keypair-derived), NAT-proof, and already encrypted. Clearnet IPs change, are CGNAT-blocked, and require port forwarding. When both sides have a Ygg address, always prefer it. No connectivity probing for v1 — trust the detection signal.

### No YggdrasilInterfaceHelper service — RNS TCP config generation belongs in doctor --setup as opt-in output only (decided)

The VPN/WG endpoint path is already handled by admin socket detection (shipped). A separate helper auto-writing RNS TCP interface config is too invasive as a default — it would modify the running Reticulum config without operator review. styrened doctor --check-yggdrasil detects the Ygg address and prints the config snippet the operator should add; doctor --setup offers to write it interactively. No background auto-writing. This is the same pattern as the existing doctor setup wizard for other interface types.

### Failed Ygg endpoint: silent WG roaming fallback in v1; doctor diagnostic for persistent failures; no TUI alert unless >2 announce cycles unreachable (decided)

WireGuard natively roams to clearnet if Ygg endpoint is unreachable — no custom fallback code needed. Connection attempt failures are logged at DEBUG only (not surfaced during normal operation). styrened doctor detects the specific pattern "ygg_endpoint present but WG handshake never completed via Ygg address" and surfaces it as a diagnostic. TUI alert is only shown if Ygg is configured and the peer has been unreachable for >2 consecutive announce cycles, indicating a persistent problem worth operator attention (not transient Ygg routing hiccup).

## Research Summary

### Current handshake structure and extension points

The existing handshake protocol is clean and already has a version field, which makes extension safe.

```python
@dataclass
class PeerInfo:
    public_key: str       # WireGuard public key (base64)
    mesh_ip: str          # Assigned mesh IP
    endpoint: str | None  # IP:port for WireGuard (None if CGNAT)
    gateway: bool = False
    identity_hash: str = ""

# Wire format (JSON over LXMF StyreneProtocol):
{
  "version": 1,
  "wg_pubkey": "<base64>",
  "mesh_ip": "10.x.x.x",
  "subnet_prefix":…

### Detection strategy: how to find the local Yggdrasil address

Three detection methods, ordered from most to least reliable:

**Method 1: Admin socket query (preferred)**
Yggdrasil exposes a Unix socket admin API (default `/var/run/yggdrasil/yggdrasil.sock`). `yggdrasilctl getSelf` returns:
```json
{
  "address": "200:dead:beef::1",
  "subnet": "300::/64",
  "public_key": "<hex>",
  ...
}
```
Can call this directly in Python without shelling out — it's a simple JSON-RPC over Unix socket. Reliable, exact, and returns the canonical self-address.

```python
as…

### Endpoint selection logic and WireGuard peer configuration

When both sides exchange endpoints, `_add_wireguard_peer()` in MeshVPNService currently uses `peer.endpoint` directly. With Ygg support, endpoint selection becomes a priority ordering:

**Endpoint preference order:**
1. `ygg_endpoint` — if set on the remote peer AND we have a local Ygg address (i.e., we're on the same Ygg network). Preferred because no NAT, stable, encrypted at Ygg layer.
2. `endpoint` — clearnet IP:port. Falls back to this if Ygg not available on either side.
3. No endpoint — b…

### RNS as Yggdrasil peer bootstrapper — the virtuous cycle

The most novel integration point, and worth capturing explicitly.

**The problem Yggdrasil has**: Like any overlay network, Yggdrasil needs at least one known peer to join the mesh. Without a peer, you're isolated. Public peer lists exist but require manual configuration. This is the "first peer problem."

**How styrened could solve this**:
RNS already discovers nodes via announces over all available transports (LoRa, WiFi, TCP, serial). When two styrene nodes find each other via RNS — even over…

### OpenSpec reconciliation note

The handshake autodetect work shipped as part of the Yggdrasil integration: `PeerInfo.ygg_endpoint`, wire-format extension, local endpoint detection, endpoint preference, lazy /meta bootstrap, and daemon wiring are implemented. The remaining bookkeeping issue is OpenSpec lifecycle cleanup rather than missing styrened code.
