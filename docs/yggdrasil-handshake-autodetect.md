---
id: yggdrasil-handshake-autodetect
title: Yggdrasil auto-detection in VPN handshake
status: decided
parent: overlay-network-integration
open_questions:
  - Does styrened need a YggdrasilInterfaceHelper that auto-generates RNS TCP config from detected Yggdrasil peers, or is a doc + doctor check sufficient?
  - Should a failed Ygg endpoint attempt fall back to clearnet automatically, or surface the failure to the operator?
branches: ["feature/yggdrasil-handshake-autodetect"]
openspec_change: yggdrasil-handshake-autodetect
---

# Yggdrasil auto-detection in VPN handshake

## Overview

> Parent: [Overlay Network Integration: Yggdrasil + I2P](overlay-network-integration.md)
> Spawned from: "Does styrened need a YggdrasilInterfaceHelper that auto-generates RNS TCP config from detected Yggdrasil peers, or is a doc + doctor check sufficient?"

*To be explored.*

## Research

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
  "subnet_prefix": "10.x.x.",
  "endpoint": "1.2.3.4:51820",   # optional, "" if unknown
  "gateway": false
}
```

Extension is backward-compatible: add `"ygg_endpoint"` as an optional field. Receivers on older versions see unknown field and ignore it. New receivers extract it with `.get("ygg_endpoint") or None`.

**Proposed PeerInfo extension:**
```python
@dataclass  
class PeerInfo:
    public_key: str
    mesh_ip: str
    endpoint: str | None = None       # clearnet IP:port
    ygg_endpoint: str | None = None   # Yggdrasil IPv6:port  ← NEW
    gateway: bool = False
    identity_hash: str = ""
```

**Wire format extension:**
```json
{
  "version": 1,
  "wg_pubkey": "<base64>",
  "mesh_ip": "10.x.x.x",
  "subnet_prefix": "10.x.x.",
  "endpoint": "1.2.3.4:51820",
  "ygg_endpoint": "[200:dead:beef::1]:51820",
  "gateway": false
}
```

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
async def _query_yggdrasil_admin(socket_path: str) -> str | None:
    """Query yggdrasil admin socket for local IPv6 address."""
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"request":"getSelf"}\n')
        await writer.drain()
        data = await reader.readline()
        result = json.loads(data)
        return result.get("address")
    except (FileNotFoundError, ConnectionRefusedError, json.JSONDecodeError):
        return None
    finally:
        writer.close()
```

Admin socket path varies: `/var/run/yggdrasil/yggdrasil.sock`, `/run/yggdrasil.sock`, or user-configured. The Yggdrasil config file specifies `AdminListen`. Check common paths, then parse `/etc/yggdrasil/yggdrasil.conf` for the configured path.

**Method 2: Network interface scan (fallback)**
Yggdrasil addresses are in `200::/7`. Scan all network interfaces for an IPv6 address in this range:

```python
import ipaddress, socket

YGG_PREFIX = ipaddress.IPv6Network("200::/7")

def _find_yggdrasil_address() -> str | None:
    for iface, addrs in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
        addr = ipaddress.IPv6Address(addrs[0])
        if addr in YGG_PREFIX:
            return str(addr)
    return None
```

More portable (no admin socket needed, works when yggdrasil is externally managed), but can't distinguish a real Ygg address from coincidental 200::/7 assignment (extremely unlikely in practice).

**Method 3: `yggdrasilctl` subprocess (last resort)**
Shell out to `yggdrasilctl getSelf` and parse output. Worst approach — slow, brittle, not available in containers without the binary.

**Preferred strategy: Method 1 → Method 2 → None**

**Admin socket locations to probe (in order):**
```python
YGG_SOCKET_PATHS = [
    "/var/run/yggdrasil/yggdrasil.sock",   # systemd/NixOS standard
    "/run/yggdrasil.sock",                  # some distros
    "/tmp/yggdrasil.sock",                  # dev/local installs
]
```

If `YggdrasilService` is managing the daemon itself (see sibling node), it knows the socket path exactly — no probing needed.

**Result feeds directly into `_detect_yggdrasil_endpoint()`:**
```python
async def _detect_yggdrasil_endpoint(self, port: int) -> str | None:
    """Detect local Yggdrasil IPv6 address for use as WG endpoint."""
    # Try admin socket first (most reliable)
    for sock_path in YGG_SOCKET_PATHS:
        addr = await _query_yggdrasil_admin(sock_path)
        if addr:
            return f"[{addr}]:{port}"
    # Fall back to interface scan
    addr = _find_yggdrasil_address()
    return f"[{addr}]:{port}" if addr else None
```

### Endpoint selection logic and WireGuard peer configuration

When both sides exchange endpoints, `_add_wireguard_peer()` in MeshVPNService currently uses `peer.endpoint` directly. With Ygg support, endpoint selection becomes a priority ordering:

**Endpoint preference order:**
1. `ygg_endpoint` — if set on the remote peer AND we have a local Ygg address (i.e., we're on the same Ygg network). Preferred because no NAT, stable, encrypted at Ygg layer.
2. `endpoint` — clearnet IP:port. Falls back to this if Ygg not available on either side.
3. No endpoint — both behind NAT without Ygg. WireGuard roaming mode (learns endpoint on first incoming packet, so the side that *can* reach must initiate).

```python
def _select_peer_endpoint(self, peer: PeerInfo) -> str | None:
    """Select the best endpoint for a peer, preferring Yggdrasil."""
    if peer.ygg_endpoint and self._local_ygg_address:
        # Both have Yggdrasil — use it
        logger.debug(f"Using Yggdrasil endpoint for {peer.identity_hash[:16]}")
        return peer.ygg_endpoint
    return peer.endpoint or None  # may be None (NAT fallback)
```

`self._local_ygg_address` is populated during `_start()` via `_detect_yggdrasil_endpoint()`. If Ygg isn't running, it's `None` and we never try Ygg endpoints.

**WireGuard AllowedIPs interaction**: The endpoint choice doesn't affect AllowedIPs — the mesh IP assignment is the same regardless. WG routes packets to the mesh IP, reaches the peer via whichever endpoint was configured. Transparent to bat0/VXLAN layer.

**Connectivity probing (nice-to-have, not required for v1)**:
Could attempt a WG handshake via Ygg endpoint, and fall back to clearnet if no response in N seconds. This adds complexity. For v1, trust the detection — if both sides have Ygg, use it.

**Handling endpoint changes**: Ygg addresses are stable (derived from keypair) so this isn't an issue. Clearnet IPs change frequently. This is another reason to prefer Ygg — `peer.ygg_endpoint` never goes stale as long as the keypair doesn't change.

### RNS as Yggdrasil peer bootstrapper — the virtuous cycle

The most novel integration point, and worth capturing explicitly.

**The problem Yggdrasil has**: Like any overlay network, Yggdrasil needs at least one known peer to join the mesh. Without a peer, you're isolated. Public peer lists exist but require manual configuration. This is the "first peer problem."

**How styrened could solve this**:
RNS already discovers nodes via announces over all available transports (LoRa, WiFi, TCP, serial). When two styrene nodes find each other via RNS — even over a 250bps LoRa link — they have a bidirectional channel.

The handshake already exchanges Ygg addresses. The next step: each node adds the other as a Yggdrasil TCP peer. Now Yggdrasil has a peer, and the full Yggdrasil mesh becomes reachable.

```
Node A (has Ygg, knows Node B only via LoRa RNS)
  → /vpn/handshake includes ygg_endpoint: "[200:A::1]:1234"
  
Node B (has Ygg but no Ygg peers yet)
  → receives ygg_endpoint for Node A
  → adds "tcp://[200:A::1]:1234" to Yggdrasil peers config/runtime
  → Yggdrasil connects — now Node B has a peer
  → Node B is now connected to the global Ygg mesh via Node A
  
Both nodes now have Ygg connectivity:
  → Future WG handshakes use Ygg endpoints (no NAT issues)
  → RNS announces travel faster over direct Ygg TCP than LoRa
```

**Implementation in YggdrasilService (see sibling node)**:
```python
async def add_peer(self, ygg_address: str, port: int = 9001) -> bool:
    """Add a Yggdrasil peer discovered via RNS handshake."""
    # POST to admin socket: addPeer
    peer_uri = f"tcp://[{ygg_address}]:{port}"
    return await self._admin_call("addPeer", {"uri": peer_uri})
```

**This creates a virtuous cycle**:
- RNS (even LoRa) bootstraps Yggdrasil peer discovery
- Yggdrasil provides high-speed internet backbone for RNS TCP interfaces
- Nodes behind CGNAT get global internet connectivity via Ygg
- WireGuard tunnels (and bat0 extension) become CGNAT-proof

**The Ygg peer announcement**: When a styrene node has Yggdrasil running, it should include its Ygg address in its RNS announce app_data. This way, every node that hears the announce can potentially add the Ygg peer — not just nodes doing a VPN handshake. This is the lowest-friction bootstrapping possible.

Currently app_data carries: capabilities bitmap. Could add a Ygg address field in a backward-compatible way.

### OpenSpec reconciliation note

The handshake autodetect work shipped as part of the Yggdrasil integration: `PeerInfo.ygg_endpoint`, wire-format extension, local endpoint detection, endpoint preference, lazy /meta bootstrap, and daemon wiring are implemented. The remaining bookkeeping issue is OpenSpec lifecycle cleanup rather than missing styrened code.

## Decisions

### Decision: Ygg endpoint detection: admin socket first, interface scan fallback

**Status:** decided
**Rationale:** The admin socket gives the canonical self-address from Yggdrasil's own routing state. Interface scan is a fallback for when the admin socket isn't accessible (external Ygg not yet running, permissions, etc). Never shell out to yggdrasilctl — too brittle in containers. The socket path is known if YggdrasilService manages the daemon; probe common paths otherwise.

### Decision: Ygg endpoint wins over clearnet in WG peer selection

**Status:** decided
**Rationale:** Yggdrasil addresses are stable (keypair-derived), NAT-proof, and already encrypted. Clearnet IPs change, are CGNAT-blocked, and require port forwarding. When both sides have a Ygg address, always prefer it. No connectivity probing for v1 — trust the detection signal.

## Open Questions

- Does styrened need a YggdrasilInterfaceHelper that auto-generates RNS TCP config from detected Yggdrasil peers, or is a doc + doctor check sufficient?
- Should a failed Ygg endpoint attempt fall back to clearnet automatically, or surface the failure to the operator?
