---
id: overlay-network-integration
title: "Overlay Network Integration: Yggdrasil + I2P"
status: resolved
related: [styrene-contacts-page]
tags: [yggdrasil, i2p, transport, mesh, overlay]
open_questions: []
---

# Overlay Network Integration: Yggdrasil + I2P

## Overview

Explore whether and how Yggdrasil Network and I2P can integrate with styrened. Both are overlay networks but with different characteristics — Yggdrasil is a self-routing IPv6 mesh, I2P is an anonymizing garlic-routing layer. Reticulum's pluggable interface model is the key integration surface.

## Research

### Yggdrasil: What it is and integration surface

Yggdrasil is a self-arranging end-to-end encrypted IPv6 overlay network. Every node gets a stable IPv6 address derived from its Ed25519 public key — cryptographically bound identity, similar in spirit to Reticulum's hash addressing but at the IP layer.

**Key properties**:
- OS-level TUN interface (tun0) — it looks like a regular IPv6 network interface to the OS
- Peers connect via TCP or QUIC over clearnet/existing transports
- Addresses are long-lived and deterministic from the keypair
- Works globally: your Yggdrasil node can reach any other Yggdrasil node worldwide via the mesh routing tree

**Integration with RNS**:
Reticulum supports TCPServerInterface and TCPClientInterface. Since Yggdrasil provides a real IPv6 address reachable via TCP, you can run RNS *over* Yggdrasil with zero protocol changes. The Yggdrasil address becomes just another TCP endpoint in the RNS config:

```yaml
interfaces:
  yggdrasil_peer:
    type: TCPClientInterface
    target_host: "200:dead:beef::1"   # Yggdrasil IPv6 addr
    target_port: 4242
```

This is already supported. The question is whether styrened should:
1. Add first-class Yggdrasil interface detection/configuration (auto-detect tun0, surface in doctor/setup)
2. Maintain a well-known Yggdrasil address for the public hub
3. Add a YggdrasilInterface helper in styrened that wraps TCP config generation

**Compatibility verdict**: ✅ Fully compatible today. Yggdrasil is "free" — RNS already runs over it. Value-add is UX: auto-detect, public hub Ygg address, `styrened doctor --check-yggdrasil`.

### I2P: What it is and integration surface

I2P (Invisible Internet Project) is a garlic-routing anonymizing overlay. Unlike Tor (which proxies clearnet), I2P is a self-contained darknet with its own addressing (.i2p domains, base32 addresses). Traffic is bundled in "garlic" encrypted messages and routed through volunteer nodes.

**Key properties**:
- Not a standard IP network — you don't get a usable IP interface like Yggdrasil
- Access via a local I2P router daemon (Java I2P or i2pd in C++)
- Programmatic access via SAM (Simple Application Messaging) protocol on localhost:7656 — a socket API for creating I2P tunnels
- HTTP proxy on localhost:4444 for .i2p eepsite browsing
- High latency (multi-hop garlic routing, 2-5+ seconds typical)
- Designed for anonymity at the cost of performance

**Integration dimensions**:

1. **I2P as RNS transport** — Technically possible via SAM API (streaming sessions), but:
   - High latency (2-5s) makes RNS announce/response cycles painful
   - Requires i2pd/Java I2P running separately
   - Would need a custom RNS interface implementation (not a TCPInterface)
   - Anonymity may conflict with Reticulum's design philosophy (RNS uses cryptographic identity, not anonymity)
   - **Verdict**: 🟡 Possible but painful. RNS over I2P would work for slow messaging, not interactive features.

2. **I2P eepsite browsing in the NomadNet page browser** — More interesting:
   - styrened already has a NomadNet page browser with caching
   - .i2p URLs could be fetched via the I2P HTTP proxy (localhost:4444)
   - This is just HTTP proxying — detect .i2p domains, route via I2P proxy
   - **Verdict**: ✅ Feasible as an optional extension. Requires i2pd running, toggle in config.

3. **Public hub as I2P eepsite** — Run the styrened web API as a hidden service:
   - Expose hub's HTTP API on an I2P tunnel
   - Useful for censorship resistance
   - **Verdict**: 🟡 Possible but niche. Complexity for limited audience.

### Fit with Reticulum's design philosophy

Reticulum is explicitly designed as a transport-agnostic resilient mesh that works even on LoRa at 250bps. Its design goals are:
- Cryptographic identity (not anonymity)
- Works on any transport including serial/radio
- Convergence layer that unifies heterogeneous transports

**Yggdrasil alignment**: High. Both are mesh networks with crypto-bound addressing. Yggdrasil extends RNS's reach over internet infrastructure where LoRa/serial can't reach. Running RNS over Yggdrasil gives you a global encrypted mesh backbone — the two protocols complement each other naturally. Yggdrasil handles IP routing, RNS handles application-layer mesh semantics.

**I2P alignment**: Lower. I2P prioritizes anonymity over performance, whereas RNS prioritizes identity and reliability. That said, the NomadNet page browser is a distinct feature from the mesh networking stack — I2P integration there is an additive feature that doesn't interfere with RNS's design.

**Summary matrix**:
| Feature | Value | Complexity | Reticulum fit | Verdict |
|---------|-------|-----------|---------------|---------|
| Yggdrasil auto-detect + doctor | Medium | Low | ✅ | Pursue |
| Public hub Yggdrasil address | High | Very Low | ✅ | Pursue |
| I2P eepsite proxy in page browser | Medium | Low | ✅ (additive) | Pursue |
| RNS over I2P SAM | Low | High | 🟡 | Defer |
| Hub as I2P hidden service | Low | Medium | 🟡 | Defer |

### Yggdrasil fit with existing BATMAN-ADV + WireGuard + VXLAN stack



## Decisions

### Decision: I2P integration belongs in the page browser, not a separate hub tunnel service

**Status:** decided
**Rationale:** The concrete near-term value is eepsite browsing through the existing page browser and PageCacheService transport dispatch. A separate hub API hidden-service tunnel is niche and remains deferred; it should not shape the core I2P integration path.

### Decision: Public hub publishes its Yggdrasil address in announces, /meta, and hub documentation

**Status:** decided
**Rationale:** The hub's Ygg address is deterministic from its keypair — stable, no DNS needed. Publishing it in (1) RNS announce app_data, (2) /meta DirectLink response, and (3) operator documentation gives any Yggdrasil-connected peer a NAT-free TCP endpoint to reach the hub as an RNS peer. This is the minimum viable Ygg integration for the public hub — very low complexity, high value as it turns the hub into a Ygg bootstrap point for the whole mesh. Consistent with the virtuous cycle described in yggdrasil-handshake-autodetect: RNS bootstraps Ygg, Ygg accelerates RNS.

## Open Questions

*No open questions.*

## Current three-tier architecture (from memory)

```
bat0 (BATMAN-ADV L2 fabric)
 ├── hard-if: wlan0 / 802.11s (local WiFi mesh, NixOS fleet)
 ├── hard-if: vxlan-<peer> × N (per-peer VXLAN, L2/UDP, VNI=7379)
 │    └── underlay: wg-styrene (WireGuard L3, keys from RNS DirectLink)
 └── hard-if: tap-<peer> (planned LoRa/RNS.Link L2 tunnel, deferred)
```

IPv6 enclave subnets ride on bat0 — BATMAN-ADV routes Ethernet frames across all three tiers, bat0 looks like a single LAN to the OS, and IPv6 NDP/RA works naturally on top.

## Where WireGuard gets its peer endpoints today

The MeshVPNService uses `DirectLinkService /vpn/handshake` to exchange WG public keys and endpoints via RNS. But RNS must already have connectivity to the peer — which means clearnet, LoRa, or another existing path. For internet-connected peers, the endpoint is a clearnet IP:port.

**The NAT problem**: Most residential nodes are behind CGNAT or dynamic IPs. Without a public IP or port forwarding, WireGuard can't establish a direct tunnel — and therefore VXLAN can't ride on it, and bat0 can't see that peer. This is a real deployment blocker for edge devices without static IPs.

## Where Yggdrasil fits: WG endpoint resolver

Yggdrasil gives every participating node a **globally stable, cryptographically-bound IPv6 address** (200::/7 range) that's reachable from any other Yggdrasil node without NAT traversal, port forwarding, or static IPs. This is Yggdrasil's killer property for our use case.

The integration point:

```
/vpn/handshake payload (today):
  wg_pubkey: <key>
  clearnet_endpoint: "1.2.3.4:51820"    # requires static IP / port forward

/vpn/handshake payload (with Yggdrasil):
  wg_pubkey: <key>
  clearnet_endpoint: "1.2.3.4:51820"    # optional, falls back
  ygg_endpoint: "200:dead:beef::1:51820" # always reachable if Ygg running
```

WireGuard is perfectly happy using an IPv6 address as a peer endpoint. The VXLAN-over-WG architecture is completely unchanged — Yggdrasil just provides a better underlay for WG to establish its tunnel over.

Result: bat0 LAN extension works for CGNAT nodes that have Yggdrasil running, with zero changes to the VXLAN/BATMAN layer.

## Address space: no conflict

- Yggdrasil addresses: `200::/7` (globally unique within Ygg network, not public internet)
- Enclave IPv6 subnets: presumably ULA `fd00::/8` or hub-assigned prefixes
- WireGuard mesh IPs: probably a private range like `10.x.x.x/24` or `fd{enclave}::/64`
- These are entirely separate namespaces — no routing table conflicts

## Could Yggdrasil replace WireGuard?

Technically: you could run VXLAN directly over Yggdrasil IPv6 (no WG needed, since Ygg already encrypts). Stack would be:

```
bat0
 └── vxlan-<peer> → Yggdrasil TUN (direct, no WG)
```

Pros: simpler, one less encryption layer, no WG key management
Cons:
- Loses the RNS-bootstrapped key exchange model (WG handshake is our trust signal)
- Yggdrasil requires ALL nodes to run Yggdrasil — breaks nodes on WiFi-only or LoRa-only paths
- VXLAN is unencrypted at the VXLAN layer; Ygg encrypts at the Ygg layer but that's point-to-point not end-to-end across the full VXLAN overlay
- We lose the three-tier convergence: bat0 would only work for Ygg-connected nodes

**Verdict: Don't replace WireGuard. Use Yggdrasil as an optional WG endpoint source.**

## Could Yggdrasil addresses BE the enclave IPv6 addresses?

If every node has a Ygg address, you could skip hub-assigned enclave subnets entirely and just use Ygg addresses for direct node-to-node communication. Appealing because it's self-sovereign — no hub needs to manage a DHCP/RA pool.

Problems:
- Enclave subnets serve a deliberate purpose: scoped trust. fd{hub-enclave-hash}::/48 makes routing policy reflect membership. Ygg addresses have no enclave scope.
- Nodes without Yggdrasil (LoRa-only, air-gapped) wouldn't have an address in this scheme.
- Hub-assigned subnets allow the hub to revoke or reassign (enclave management).

**Verdict: Keep hub-assigned enclave subnets as the application-layer IPv6 identity. Ygg addresses are infrastructure plumbing, not application addressing.**

## Summary: Yggdrasil as NAT-busting WG endpoint

The clean integration: when both sides have Yggdrasil running, the `/vpn/handshake` message includes the Ygg address as a preferred WG endpoint. MeshVPNService tries Ygg endpoint first, falls back to clearnet. Zero changes to BATMAN-ADV, VXLAN, or enclave subnet design. Maximum benefit for minimum disruption.
