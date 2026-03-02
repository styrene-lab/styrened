# Mesh VPN: LXMF-Negotiated Tunnels over 802.11s

**Date**: 2026-03-01
**Status**: Architecture / Design
**Scope**: Using Reticulum as a cryptographic signaling plane to bootstrap WireGuard mesh VPNs over 802.11s WiFi mesh networks

## 1. Abstract

This document describes an architecture for establishing encrypted IP-layer mesh VPNs using LXMF messages as the signaling and key exchange channel, WireGuard as the tunnel protocol, and 802.11s as the high-bandwidth data plane. Reticulum provides the foundational primitives — cryptographic identity, peer discovery, mutual authentication, and encrypted messaging — that eliminate the need for traditional PKI, IKE daemons, or manual key distribution. The result is a mesh VPN that bootstraps itself from RNS identity alone, promotes traffic through multiple transport tiers as connectivity allows, and degrades gracefully when links fail.

## 2. Problem Statement

### Why not just use Reticulum for everything?

Reticulum excels at identity, discovery, and reliable messaging across constrained and heterogeneous links. It does not excel at bulk IP traffic. The RNS link layer was designed for command-and-control messaging, file transfer, and terminal sessions — not as a general-purpose IP transport. Tunneling IP packets through RNS links wastes the bandwidth of co-located high-speed transports (WiFi, Ethernet) that could carry the same traffic at orders of magnitude higher throughput.

### Why not just use WireGuard directly?

WireGuard requires pre-distributed public keys and endpoint addresses. In a dynamic mesh where nodes appear, disappear, and change addresses, this means either:

- **Static configuration**: Manually editing WireGuard configs on every node when the mesh changes. Unworkable beyond 3-4 nodes.
- **External orchestration**: Running Tailscale/Headscale, Nebula, or similar coordinators. Adds infrastructure dependencies and central points of failure.
- **mDNS/DHCP discovery**: Limited to a single broadcast domain. Doesn't cross mesh hops.

None of these work for a fleet of edge devices that may be connected via LoRa, serial, packet radio, or any combination of Reticulum transports — and may not have persistent IP connectivity at all.

### What we actually need

A system where:

1. A node joins the mesh and announces its RNS identity (it already does this).
2. Peers discover the node via RNS path discovery (they already do this).
3. Peers negotiate a WireGuard tunnel via authenticated LXMF messages (new).
4. Bulk IP traffic flows over the highest-bandwidth available transport (new).
5. If the high-bandwidth transport fails, signaling continues over whatever RNS transport remains (already works).

## 3. Architecture

### 3.1 Separation of Planes

```
┌──────────────────────────────────────────────────────┐
│  Application Traffic                                 │
│  (SSH, HTTP, git, monitoring, fleet management)      │
├──────────────────────────────────────────────────────┤
│  WireGuard Tunnel (wg-styrene interface)             │
│  Overlay: 10.73.0.0/24                               │
├──────────────────────────────────────────────────────┤
│  802.11s Mesh (Layer 2)                              │  DATA PLANE
│  HWMP path selection, auto-peering                   │
│  Underlay: 192.168.73.0/24 (link-local or DHCP)     │
╞══════════════════════════════════════════════════════╡
│  Styrene Wire Protocol (tunnel negotiation msgs)     │
│  LXMF (reliable delivery, store-and-forward)         │  CONTROL PLANE
│  RNS (identity, path discovery, link encryption)     │
│  Any RNS transport (LoRa, serial, TCP, 802.11s)     │
└──────────────────────────────────────────────────────┘
```

The control plane and data plane are **physically separable**. The control plane can run over LoRa while the data plane runs over WiFi. Or both can share the same 802.11s mesh (RNS as a TCP or UDP interface on the mesh IP, WireGuard as a UDP tunnel on the same mesh IP). The architecture does not require physical separation — it requires logical separation so that losing the data plane does not lose signaling.

### 3.2 Identity and Trust Model

Traditional VPN trust chains:

```
Certificate Authority → signs → Server Certificate → validates → Client
   (central, fragile)              (per-node)            (complex)
```

Styrene tunnel trust chain:

```
RNS Identity (Curve25519 key pair, already exists)
  └─ authenticates LXMF message sender (RNS does this)
       └─ LXMF TunnelOffer carries WireGuard public key
            └─ WireGuard key trusted because sender is authenticated
                 └─ Tunnel traffic authenticated by WireGuard key
```

No certificate authority. No PKI infrastructure. No key distribution ceremony. The RNS identity that a node already possesses for messaging, fleet management, and terminal sessions is the same identity that authenticates its VPN tunnel negotiation. A node's WireGuard public key is trusted because it arrived in an LXMF message from a cryptographically verified RNS identity.

### 3.3 Trust Scoping

Not every RNS peer should be allowed to establish a tunnel. Trust is scoped:

- **Fleet membership**: Only nodes registered in the fleet (via hub registry) can negotiate tunnels. The `REGISTRY_QUERY`/`REGISTRY_RESPONSE` messages (0x80-0x81) already provide fleet membership verification.
- **Explicit allow-list**: Node configuration specifies which RNS destination hashes are permitted tunnel peers. Default: fleet members only.
- **Capability advertisement**: Nodes advertise tunnel capability in their RNS announce data. Peers that don't advertise the capability are not sent tunnel offers.

## 4. Wire Protocol Extension

### 4.1 New Message Types

Tunnel negotiation uses the Styrene wire protocol (StyreneEnvelope over LXMF FIELD_CUSTOM_DATA). New message types allocated in the reserved 0xD8-0xDF range:

```
# Tunnel Negotiation (0xD8-0xDF)
TUNNEL_OFFER     = 0xD8  # "I want a tunnel, here are my parameters"
TUNNEL_ACCEPT    = 0xD9  # "Accepted, here are mine"
TUNNEL_REJECT    = 0xDA  # "Rejected" (+ reason code)
TUNNEL_TEARDOWN  = 0xDB  # "Tearing down tunnel"
TUNNEL_REKEY     = 0xDC  # "Rotating WireGuard key, here's the new one"
TUNNEL_KEEPALIVE = 0xDD  # "Tunnel health check" (supplements WireGuard's)
TUNNEL_TOPOLOGY  = 0xDE  # "Here are my active tunnel peers" (optional)
```

### 4.2 Message Payloads

All payloads are msgpack-encoded (consistent with existing Styrene wire format).

#### TUNNEL_OFFER (0xD8)

```python
{
    "wg_pubkey": bytes(32),       # Curve25519 public key
    "mesh_addr": str,             # 802.11s mesh IP (e.g., "192.168.73.5")
    "mesh_port": int,             # WireGuard listen port (default 51820)
    "tunnel_addr": str,           # Proposed overlay IP (e.g., "10.73.0.5/24")
    "allowed_ips": [str],         # Requested allowed-ips for this peer
    "capabilities": [str],        # ["ipv4", "ipv6", "dns", "route-all"]
    "keepalive": int,             # Persistent keepalive interval (seconds)
    "mtu": int,                   # Proposed MTU (default 1420)
    "nonce": bytes(16),           # Replay protection
    "timestamp": int,             # Unix timestamp
    "sae_passphrase": bytes,      # Optional: 802.11s SAE passphrase (encrypted)
}
```

#### TUNNEL_ACCEPT (0xD9)

```python
{
    "wg_pubkey": bytes(32),       # Responder's WG public key
    "mesh_addr": str,             # Responder's 802.11s mesh IP
    "mesh_port": int,             # Responder's WG listen port
    "tunnel_addr": str,           # Assigned overlay IP (may differ from proposed)
    "allowed_ips": [str],         # Allowed-ips for the offerer
    "keepalive": int,             # Agreed keepalive interval
    "mtu": int,                   # Agreed MTU
    "nonce": bytes(16),           # Response nonce
    "timestamp": int,
}
```

#### TUNNEL_REJECT (0xDA)

```python
{
    "reason": str,                # Human-readable reason
    "code": int,                  # 1=untrusted, 2=capacity, 3=disabled,
                                  # 4=address-conflict, 5=incompatible
}
```

#### TUNNEL_TEARDOWN (0xDB)

```python
{
    "reason": str,                # "user-requested", "link-lost", "reboot", "error"
    "graceful": bool,             # True = planned, False = best-effort notification
}
```

#### TUNNEL_REKEY (0xDC)

```python
{
    "new_wg_pubkey": bytes(32),   # New WireGuard public key
    "effective_at": int,          # Unix timestamp when new key becomes active
    "old_key_valid_until": int,   # Grace period for in-flight packets
}
```

#### TUNNEL_KEEPALIVE (0xDD)

```python
{
    "tunnel_up_since": int,       # Unix timestamp of tunnel establishment
    "bytes_tx": int,              # Bytes transmitted through tunnel
    "bytes_rx": int,              # Bytes received through tunnel
    "last_handshake": int,        # Last WireGuard handshake timestamp
    "rtt_ms": int,                # Measured RTT through tunnel (optional)
}
```

#### TUNNEL_TOPOLOGY (0xDE)

```python
{
    "peers": [
        {
            "rns_hash": str,      # RNS destination hash of tunnel peer
            "tunnel_addr": str,   # Peer's overlay IP
            "up_since": int,      # Tunnel establishment time
        }
    ]
}
```

### 4.3 Replay Protection

Every TUNNEL_OFFER and TUNNEL_ACCEPT includes a 16-byte random nonce and a timestamp. Receivers:

1. Reject messages with timestamps more than 60 seconds old (clock skew tolerance).
2. Cache seen nonces for 120 seconds; reject duplicates.
3. Reject messages from RNS identities not in the allow-list before parsing payload (zero processing cost for spam).

LXMF's store-and-forward nature means messages may arrive with delay. The timestamp tolerance window should be configurable and may need to be wider for mesh-only deployments where LXMF propagation adds latency.

## 5. Negotiation Flow

### 5.1 Happy Path

```
Node A                              Node B
  │                                   │
  │  RNS Announce (with tunnel cap)   │
  ├──────────────────────────────────►│
  │                                   │
  │  802.11s mesh peer detected       │
  │  (A and B on same 802.11s mesh)   │
  │◄──────────────── L2 ────────────►│
  │                                   │
  │  LXMF: TUNNEL_OFFER              │
  │  wg_pubkey=A_pub                  │
  │  mesh_addr=192.168.73.5           │
  │  tunnel_addr=10.73.0.5/24        │
  ├──────────────────────────────────►│
  │                                   │
  │      B validates:                 │
  │      - A in fleet registry? ✓     │
  │      - A in allow-list? ✓         │
  │      - nonce fresh? ✓             │
  │      - address available? ✓       │
  │                                   │
  │  LXMF: TUNNEL_ACCEPT             │
  │  wg_pubkey=B_pub                  │
  │  mesh_addr=192.168.73.10          │
  │  tunnel_addr=10.73.0.10/24       │
  │◄──────────────────────────────────┤
  │                                   │
  │  Both configure WireGuard:        │
  │                                   │
  │  ip link add wg-styrene type wireguard
  │  wg set wg-styrene private-key ...
  │  wg set wg-styrene peer <B_pub> \
  │    allowed-ips 10.73.0.10/32 \
  │    endpoint 192.168.73.10:51820
  │  ip addr add 10.73.0.5/24 dev wg-styrene
  │  ip link set wg-styrene up
  │                                   │
  │  WireGuard handshake over 802.11s │
  │◄══════════════ UDP ══════════════►│
  │                                   │
  │  IP traffic flows through tunnel  │
  │◄══════════════ ESP ══════════════►│
```

### 5.2 Conflict Resolution

**Address conflict**: Two nodes propose the same overlay IP. The node with the lexicographically lower RNS destination hash wins. The other node picks the next available address and re-offers. The `TUNNEL_REJECT` with code 4 (address-conflict) includes the conflicting peer's hash so the rejected node can coordinate.

**Simultaneous offer**: Both nodes send TUNNEL_OFFER at the same time. The node with the lower RNS destination hash becomes the "offerer" and the other becomes the "responder". The responder treats the incoming offer as its accept trigger — it stops waiting for an accept to its own offer and responds with TUNNEL_ACCEPT.

**Stale offers**: If a TUNNEL_ACCEPT is not received within 30 seconds (configurable), the offerer retries up to 3 times with exponential backoff (30s, 60s, 120s). After exhausting retries, the tunnel attempt is logged and the peer marked as unreachable-for-tunnel (retried on next announce).

## 6. Overlay IP Address Assignment

### 6.1 Strategies

Three strategies, selectable per deployment:

#### Deterministic from RNS identity (default)

```python
def derive_tunnel_addr(rns_hash: bytes, subnet: str = "10.73.0.0/24") -> str:
    """Derive a deterministic overlay IP from RNS identity hash.

    Uses HKDF to derive a host portion from the identity hash,
    avoiding .0 (network) and .255 (broadcast) for /24.
    """
    import hashlib
    import ipaddress

    network = ipaddress.IPv4Network(subnet)
    # HKDF-SHA256 with fixed info string for determinism
    derived = hashlib.blake2b(
        rns_hash, key=b"styrene-tunnel-addr-v1", digest_size=4
    ).digest()
    host_bits = network.max_prefixlen - network.prefixlen
    host_num = int.from_bytes(derived[:4], "big") % (2**host_bits - 2) + 1
    return str(network.network_address + host_num)
```

No coordination needed. Collision probability: ~0.4% for 10 nodes in a /24 (birthday problem). Collisions resolved per §5.2.

#### Hub-assigned (managed fleets)

The fleet hub maintains an IP allocation table (stored in SQLite alongside fleet registry). Nodes request an address from the hub before sending TUNNEL_OFFER. The hub responds via existing `FLEET_STATUS_RESPONSE` with a `tunnel_addr` field.

#### Manual (static config)

Node configuration file specifies a fixed overlay IP. Suitable for permanent infrastructure nodes (hubs, gateways).

### 6.2 Subnet Selection

Default overlay subnet: `10.73.0.0/24` ("73" = ASCII 's' for styrene, /24 supports 253 peers).

Larger fleets can use `10.73.0.0/16` (65,534 peers) at the cost of larger routing tables.

The subnet is configured per fleet. All nodes in a fleet must agree on the subnet. This is distributed via the hub's fleet configuration (existing CONFIG_UPDATE mechanism).

## 7. 802.11s Mesh Configuration

### 7.1 Linux 802.11s Setup

802.11s (IEEE 802.11s-2011, now part of 802.11-2020) provides Layer 2 mesh networking with HWMP (Hybrid Wireless Mesh Protocol) for path selection. Supported by most modern WiFi chipsets on Linux via mac80211.

```bash
# Prerequisites
# - WiFi chipset with mesh point (IBSS/mesh) support
# - iw, ip, wpa_supplicant (for SAE)

# Create mesh interface
iw phy phy0 interface add mesh0 type mesh
iw dev mesh0 set channel 6              # Or any agreed channel
iw dev mesh0 mesh join styrene-mesh     # Mesh ID

# Optional: SAE encryption (passphrase distributed via LXMF)
# wpa_supplicant -i mesh0 -c /etc/styrene/mesh-sae.conf

# Assign link-local IP for WireGuard endpoint resolution
ip addr add 192.168.73.$(derived_host)/24 dev mesh0
ip link set mesh0 up
```

### 7.2 SAE Passphrase Distribution

802.11s mesh peering is **unencrypted by default**. SAE (Simultaneous Authentication of Equals, WPA3) adds authenticated encryption at Layer 2 but requires a shared passphrase.

The TUNNEL_OFFER message includes an optional `sae_passphrase` field. Since LXMF messages are end-to-end encrypted by RNS, this passphrase is protected in transit. Rotation follows the same pattern as TUNNEL_REKEY — a new passphrase distributed via LXMF, effective at a coordinated timestamp.

For fleets: the hub distributes the SAE passphrase via CONFIG_UPDATE to all fleet members. Single source of truth.

### 7.3 Channel Selection

The 802.11s mesh channel is a fleet-wide configuration parameter. Default: channel 6 (2.4 GHz, widest compatibility). 5 GHz channels offer more bandwidth but shorter range.

Channel selection can be included in the hub's fleet configuration. Dynamic channel selection (DFS) is possible but adds complexity — deferred to a future iteration.

### 7.4 Hardware Considerations

| Device | WiFi Chipset | 802.11s Support | Notes |
|--------|-------------|-----------------|-------|
| Pi 4B | Broadcom BCM43455 | ✓ (mac80211) | Primary edge device |
| Pi Zero 2W | Broadcom BCM43436s | ✓ (mac80211) | Limited throughput |
| USB adapter (RTL8812AU) | Realtek | Varies by driver | Preferred for dual-band |
| ESP32 | Espressif WiFi | ESP-MESH only | Not 802.11s compatible |

Note: ESP32 uses Espressif's proprietary ESP-MESH, not 802.11s. ESP32 nodes participate in the Reticulum mesh via LoRa/serial but cannot join the 802.11s data plane. They receive tunnel services through a gateway node that bridges both networks.

## 8. Transport Tier Model

### 8.1 Tier Definitions

```
Tier 3: FULL
  Transport: WireGuard over 802.11s (or Ethernet/IP backhaul)
  Capability: Full IP connectivity, bulk transfer, streaming
  Bandwidth: 10-100+ Mbps
  Latency: 1-10ms

Tier 2: RNS_WIFI
  Transport: RNS Link over 802.11s (TCP/UDP interface)
  Capability: LXMF messaging, file transfer, terminal sessions
  Bandwidth: 1-50 Mbps (RNS overhead)
  Latency: 10-100ms

Tier 1: RNS_LORA
  Transport: RNS over LoRa
  Capability: LXMF messaging only (size-constrained)
  Bandwidth: 0.3-21.9 kbps
  Latency: 100ms-minutes (store-and-forward)

Tier 0: OFFLINE
  Transport: None
  Capability: Queued messages (delivered when connectivity returns)
```

### 8.2 Tier Transitions

```
                    ┌─────────┐
       802.11s +    │         │  802.11s or WG
       WG handshake │  FULL   │  failure
       succeeds     │ (Tier 3)│────────────┐
          ┌────────►│         │            │
          │         └─────────┘            ▼
          │                          ┌──────────┐
          │         802.11s peer     │ RNS_WIFI │
          │         detected         │ (Tier 2) │
          │         ┌───────────────►│          │────────────┐
          │         │                └──────────┘  802.11s   │
          │         │                      ▲       lost      │
          │         │                      │                 ▼
     ┌──────────┐   │                      │          ┌──────────┐
     │ Promote  │───┘              Reconnect│          │ RNS_LORA │
     │  Logic   │                          └──────────│ (Tier 1) │
     └──────────┘                                     │          │──┐
          ▲                                           └──────────┘  │ LoRa
          │                                                ▲        │ lost
          │                                                │        ▼
          │                                           Reconnect ┌────────┐
          │                                                └────│OFFLINE │
          └─────────────────────────────────────────────────────│(Tier 0)│
                         Any transport restored                 └────────┘
```

### 8.3 Promotion Logic

Promotion is **opportunistic and automatic**:

1. **OFFLINE → RNS_LORA**: RNS path to peer discovered (announce received or path request succeeds). Always attempted.
2. **RNS_LORA → RNS_WIFI**: 802.11s mesh peer appears (detected via `iw mesh0 station dump` or mesh peer event). RNS TCP/UDP interface on the mesh IP becomes available.
3. **RNS_WIFI → FULL**: Both nodes have tunnel capability. TUNNEL_OFFER sent via LXMF. On TUNNEL_ACCEPT, WireGuard configured and handshake completes.

Demotion is **event-driven**:

1. **FULL → RNS_WIFI**: WireGuard last handshake exceeds threshold (default: 180 seconds). Tunnel torn down, TUNNEL_TEARDOWN sent via LXMF (best-effort).
2. **RNS_WIFI → RNS_LORA**: 802.11s peer disappears (station dump no longer lists peer). RNS falls back to next available transport.
3. **RNS_LORA → OFFLINE**: RNS path times out. Messages queued for future delivery.

### 8.4 Application Transparency

Applications bind to the `wg-styrene` interface or use the overlay IP (`10.73.0.x`). When the tunnel is up (Tier 3), traffic flows normally. When the tunnel goes down:

- **Option A (default)**: Routes withdrawn. Applications see connection failures. They retry when the tunnel comes back.
- **Option B (resilient mode)**: A local proxy (userspace or nftables DNAT) intercepts traffic destined for downed tunnel peers and routes it through LXMF as a degraded-bandwidth fallback. Only viable for low-bandwidth protocols (e.g., git-over-styrene, small RPC calls).

Option B is architecturally interesting but deferred. Option A is the MVP behavior.

## 9. Security Analysis

### 9.1 What's Protected

| Layer | Protection | Provided By |
|-------|-----------|-------------|
| Signaling (LXMF) | End-to-end encryption | RNS Link / LXMF encryption |
| Tunnel negotiation | Authenticated key exchange | RNS identity verification |
| WireGuard handshake | Authenticated encryption | WireGuard (Noise IK) |
| Tunnel traffic | Authenticated encryption | WireGuard (ChaCha20-Poly1305) |
| 802.11s L2 (optional) | Authenticated encryption | SAE (WPA3) |
| LoRa signaling | Encryption | RNS Link encryption |

### 9.2 Threat Model

**Passive observer on 802.11s**: Sees encrypted WireGuard UDP packets. Without SAE, also sees 802.11s management frames (MAC addresses, mesh peering). With SAE, L2 is also encrypted.

**Active attacker on 802.11s**: Cannot forge TUNNEL_OFFER messages (would need to compromise RNS identity private key). Cannot inject WireGuard traffic (would need WireGuard private key). Can disrupt 802.11s mesh peering (deauth attacks) — mitigated by Protected Management Frames (PMF/802.11w) when SAE is active.

**Compromised node**: A node with valid RNS identity and fleet membership can negotiate tunnels. Mitigation: fleet registry revocation (remove from allow-list, distribute updated list via CONFIG_UPDATE). WireGuard has no forward secrecy for the tunnel itself, but TUNNEL_REKEY rotates keys periodically.

**Correlation attack**: An observer seeing the same device on both 802.11s (MAC address) and LoRa (RNS announce timing) can correlate identities. Mitigation: MAC randomization on mesh0 interface (supported by mac80211). RNS announce timing jitter (configurable in styrened).

### 9.3 Key Rotation

WireGuard keys are rotated via TUNNEL_REKEY messages:

1. Initiator generates new WireGuard key pair.
2. Sends TUNNEL_REKEY with `new_wg_pubkey` and `effective_at` (timestamp 30 seconds in future).
3. Responder acknowledges by sending its own TUNNEL_REKEY (or TUNNEL_ACCEPT with new key).
4. At `effective_at`, both sides reconfigure WireGuard with new keys.
5. Old keys remain valid for `old_key_valid_until` grace period (default 60 seconds) to handle in-flight packets.

Default rotation interval: 24 hours. Configurable per fleet.

## 10. Implementation Plan

### 10.1 Module Structure

```
src/styrened/
  services/
    tunnel.py              # TunnelManager - orchestrates negotiation + WG config
    mesh_wifi.py           # 802.11s interface management + peer monitoring
  models/
    styrene_wire.py        # + TUNNEL_* message type additions
    tunnel_state.py        # TunnelPeer, TunnelState, tier FSM
  protocols/
    styrene.py             # + TUNNEL_* message handlers
```

### 10.2 New Dependencies

| Dependency | Purpose | Notes |
|-----------|---------|-------|
| `pyroute2` | Netlink for WireGuard + interface config | Eliminates shelling to `wg`/`ip`. Pure Python. Already widely used. |
| None (stdlib) | `subprocess` for `iw` commands | 802.11s config via iw. No Python netlink binding for mesh config. |

### 10.3 Phase 1: Wire Protocol + Negotiation (No 802.11s)

**Goal**: Two styrened nodes on the same LAN negotiate and establish a WireGuard tunnel via LXMF.

1. Add TUNNEL_* message types to `StyreneMessageType` enum (0xD8-0xDE).
2. Add payload encode/decode helpers (`create_tunnel_offer`, `create_tunnel_accept`, etc.).
3. Implement `TunnelManager` service:
   - Listens for TUNNEL_OFFER/ACCEPT/REJECT via StyreneProtocol handler.
   - Maintains tunnel state per peer (FSM: idle → offered → established → rekeying → teardown).
   - Configures WireGuard via pyroute2 netlink.
   - Publishes tunnel capability in RNS announce data.
4. Add tunnel configuration to styrened config file:
   ```toml
   [tunnel]
   enabled = true
   overlay_subnet = "10.73.0.0/24"
   address_strategy = "deterministic"  # or "hub-assigned" or "static"
   static_address = ""                  # only if strategy = "static"
   listen_port = 51820
   keepalive = 25
   rekey_interval = 86400
   allowed_peers = []                   # empty = fleet members only
   ```
5. Unit tests for negotiation FSM, payload encoding, address derivation.
6. Integration test: two styrened instances on localhost negotiate a WireGuard tunnel.

### 10.4 Phase 2: 802.11s Integration

**Goal**: Automatic 802.11s mesh setup and tunnel promotion.

1. Implement `MeshWifiManager` service:
   - Creates mesh0 interface, joins mesh, assigns link-local IP.
   - Monitors mesh peer events (`iw event` or periodic `iw mesh0 station dump`).
   - Emits internal events when mesh peers appear/disappear.
2. Connect MeshWifiManager to TunnelManager:
   - Mesh peer detected → trigger TUNNEL_OFFER if peer is in fleet and doesn't have active tunnel.
   - Mesh peer lost → trigger tier demotion.
3. Implement tier FSM in TunnelManager.
4. SAE passphrase distribution via CONFIG_UPDATE.
5. Scenario tests on bare-metal Pi fleet (802.11s mesh between Pi 4B nodes).

### 10.5 Phase 3: Fleet-Wide Mesh VPN

**Goal**: Hub-coordinated overlay network with address assignment and topology awareness.

1. Hub-side IP allocation table (SQLite, served via FLEET_STATUS_RESPONSE).
2. TUNNEL_TOPOLOGY exchange for mesh-wide routing visibility.
3. Hub monitors tunnel health via aggregated TUNNEL_KEEPALIVE data.
4. TUI integration: tunnel status in fleet view, peer connectivity map.
5. Graceful degradation testing: kill WiFi, verify LoRa signaling continues, restore WiFi, verify tunnel re-establishes.

### 10.6 styrene-rs Parallel Implementation

The wire protocol message types (0xD8-0xDE) and payload schemas defined here apply equally to styrene-rs. The Rust implementation would use:

- `wireguard-uapi` crate for WireGuard configuration via netlink.
- `rtnetlink` crate for interface management.
- `nl80211` crate (or `iw` subprocess) for 802.11s mesh management.
- Same msgpack payload schemas, same negotiation FSM.

Wire-level interop between styrened (Python) and styrened-rs (Rust) nodes is a design requirement — a Python node must be able to negotiate a tunnel with a Rust node and vice versa. This is validated by the existing wire protocol interop test pattern.

## 11. Relation to Existing Styrene Features

### 11.1 Terminal Sessions

Terminal sessions (`rnsh`-style) currently negotiate an RNS Link via LXMF control plane (TERMINAL_REQUEST → TERMINAL_ACCEPT → data over Link). The tunnel architecture follows the identical pattern: LXMF control plane negotiates, higher-bandwidth transport carries data.

When a tunnel is active (Tier 3), terminal sessions could optionally route over the WireGuard tunnel as plain SSH — no RNS Link overhead. This is a future optimization, not a requirement.

### 11.2 File Transfer

File transfers currently use LXMF (FILE_OFFER/ACCEPT/CHUNK). With an active tunnel, large file transfers could promote to SCP/rsync over the WireGuard overlay. Same pattern: LXMF negotiates, tunnel carries bulk data.

### 11.3 Fleet Management

Fleet RPC commands (EXEC, CONFIG_UPDATE, SELF_UPDATE) currently travel via LXMF. With tunnels active, these could optionally use the overlay IP for lower-latency RPC. The daemon's existing HTTP API (when enabled) would be reachable via the overlay IP.

### 11.4 git-over-styrene

The git-over-styrene architecture (documented separately) uses LXMF as control plane and RNS Links as data plane for git bundle transfer. With an active tunnel, git could use standard SSH or HTTPS transport over the WireGuard overlay — eliminating the need for the custom git-remote-rns transport entirely. The custom transport remains valuable for mesh-only (Tier 1) scenarios.

### 11.5 OSINT Platform Integration

The OSINT platform (documented in misc/osint/) uses Reticulum for mesh data ingest and pub/sub distribution. With mesh VPN tunnels, the platform could use standard IP protocols (HTTP, gRPC) for high-bandwidth data exchange with hubs while maintaining LXMF as the fallback signaling channel. The Iggy message streaming backbone could replicate across tunnel-connected nodes.

## 12. Open Questions

1. **WireGuard key derivation from RNS identity**: Should the WireGuard key pair be derived from the RNS identity key (one key to rule them all) or independently generated (defense in depth)? Derivation simplifies management but means RNS identity compromise = tunnel compromise. Independent generation means two key pairs to manage but limits blast radius.

2. **IPv6 overlay**: Should the overlay support IPv6 link-local addresses derived from RNS identity? This would eliminate address assignment entirely (`fe80::` + EUI-64 from RNS hash). IPv6 link-local doesn't need DHCP or coordination.

3. **Multi-mesh support**: Can a node participate in multiple 802.11s meshes simultaneously (e.g., one per fleet)? Requires multiple WiFi interfaces or virtual interfaces. Hardware-dependent.

4. **Bridge mode**: Should a tunnel-capable node with both LoRa and WiFi act as a transparent bridge, routing IP traffic from WiFi-only nodes to LoRa-only nodes? This creates a general-purpose mesh router, which is powerful but significantly more complex (routing tables, NAT, firewall rules).

5. **Windows/macOS support**: 802.11s is Linux-specific (mac80211). WireGuard is cross-platform. On non-Linux systems, should the architecture degrade to WireGuard-over-IP-only (skip 802.11s)? Or is this Linux-only by design?

6. **Interaction with existing RNS transports**: If RNS is already using a TCP interface on the 802.11s mesh IP, and WireGuard is also using the same mesh IP, do they interfere? They shouldn't (different ports), but the interaction needs testing.

7. **Power budget**: On battery-powered edge devices (Pi Zero 2W), continuous WiFi mesh operation significantly impacts power consumption. Should tunnel capability be conditional on power state (disable mesh WiFi on battery, enable on mains)?
