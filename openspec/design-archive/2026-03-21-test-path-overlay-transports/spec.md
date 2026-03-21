# Test Path: Overlay Transports (I2P, Yggdrasil) — Design Spec (extracted)

> Auto-extracted from docs/test-path-overlay-transports.md at decide-time.

## Decisions

### Five transport test tiers: TCP → Auto → Overlay → WireGuard → Hardware (decided)

Each tier adds external dependencies and CI complexity. TCP localhost is the zero-dependency default. AutoInterface adds multicast but no sidecars. Overlays (I2P/Yggdrasil) need sidecar daemons. WireGuard needs NET_ADMIN + kernel module. Hardware needs physical devices. Each tier uses the same fixture identity keys — only the transport overlay config changes. Tests at higher tiers can be gated by pytest markers and skipped when dependencies are unavailable.

### WireGuard tests are layered above RNS transport tests, not parallel to them (decided)

MeshVPN is not an RNS interface — it's an IP tunnel bootstrapped over an existing RNS.Link via DirectLinkService. WireGuard tests verify key exchange, interface creation, and IPv6 connectivity. They always need a working RNS transport underneath (TCP or overlay). This makes them orthogonal to the transport tier — a WireGuard test can run over TCP localhost or over Yggdrasil. Don't conflate IP-layer testing with RNS-layer testing.

### Hardware radio tests deferred to styrene-edge — not in styrened CI (decided)

RNode/Serial/KISS/AX.25 require physical hardware or emulation (socat virtual serial). styrene-edge provisions and manages these devices. PipeInterface could serve as a serial-like stand-in for protocol validation, but the real value is hardware-in-the-loop testing on edge devices. Keep in styrene-edge's test suite, not styrened's.

### CLI for protocol verification, TUI pilot only for transport-specific UI (Comms screen, discovered_via) (decided)

The TUI rendering is transport-agnostic — buttons, tabs, navigation are identical over TCP or Yggdrasil. Full TUI pilot over every transport is redundant with the TCP pilot tests. What changes per-transport: (1) discovered_via field shows the transport interface name, (2) Comms screen sections reveal when I2P/Ygg are active, (3) I2P latency makes loading/timeout states visible. So: run the full operator path test suite once over TCP (Tier 1). For overlay tiers, use CLI (styrened devices, styrened send) to prove protocol-level connectivity, plus a small targeted TUI pilot test for Comms screen state and discovered_via rendering. This avoids doubling test runtime for no coverage gain.

### Upstream images with config injection — no custom builds (decided)

i2pd: use purplei2p/i2pd (official upstream on Docker Hub). Supports config via volume mount or environment variables. Mount a pre-generated i2pd.conf and tunnels.conf into the container. Yggdrasil: no official image exists — use community image (gitlab.com/oci-containers/yggdrasil-go or build a minimal one from the yggdrasil-go binary in a scratch/alpine base). Config via yggdrasil.conf volume mount with pre-generated keys and static peer list. Both sidecars share the test pod's network namespace (localhost), so SAM bridge (i2pd) and TCP listener (yggdrasil IPv6) are reachable from the styrened container at 127.0.0.1. No custom image builds needed — just config files in tests/k8s/sidecars/.

### K8s pod sidecars sharing network namespace, managed by test harness (decided)

Each test pod runs: styrened container + transport sidecar(s) in the same network namespace. Sidecar lifecycle managed by the K8s harness (extend pod spec templates in tests/k8s/). For Yggdrasil: two pods each with a yggdrasil sidecar, peered to each other via ClusterIP service (Ygg peers list). Mesh forms in < 5s. styrened configures TCPClientInterface pointing to the remote pod's Yggdrasil IPv6 address. For I2P: two pods each with an i2pd sidecar. Private I2P network via floodfill reseed between the two routers. Tunnel establishment takes 2-5min — session-scoped fixture with generous startup wait. styrened configures I2PInterface pointing to localhost SAM bridge (port 7656). WireGuard: no sidecar needed — wireguard-tools installed in test image, NET_ADMIN capability added to pod security context.

## Research Summary

### Transport dependency landscape

**I2P**:
- RNS has native `I2PInterface` — connects to a running I2P router's SAM bridge (default port 7656)
- i2pd (C++ daemon) is lightweight, available as Alpine/Debian package, and runs headless — ideal for containers
- Two styrened peers talking over I2P need: i2pd router A ↔ i2pd router B (tunnel mesh), styrened A configures I2PInterface pointing to router A's SAM, styrened B to router B's SAM
- I2P tunnel establishment takes 2-5 minutes for initial setup (building tunnels, finding peers) …

### CI tier placement

These don't belong in the fast TUI pilot tier. They belong in their own transport-specific CI tier:

**Test tier hierarchy with transports:**
```
smoke (< 30s)     — in-process daemon, localhost TCP, TUI pilot
                    No transport dependencies beyond loopback

integration       — K8s harness, multi-peer, RBAC
                    TCP between pods in same namespace

yggdrasil (new)   — Two yggdrasil sidecars + two styrened pods
                    Verify: announce discovery over Yggdra…

### Full RNS transport inventory and testing assessment

RNS supports 13 interface types. Assessing each for styrened testing relevance:

### Tier 1: Already modeled in styrened config, need test paths

| Transport | RNS Interface | styrened Config | CI Feasibility | Notes |
|-----------|--------------|-----------------|----------------|-------|
| **TCP** | TCPClientInterface, TCPServerInterface | InterfaceConfig.peers, .server | ✅ Trivial (localhost) | Default test transport. Already working. |
| **AutoInterface** | AutoInterface | InterfaceConfig.auto | ✅ Localhost multicast | UDP multicast on loopback. Platform quirks (macOS utun errors). |
| **I2P** | I2PInterface | I2PConfig | ⚠️ Slow (2-5…

### Tier 2: Relevant for edge devices, need consideration

| Transport | RNS Interface | styrened Config | CI Feasibility | Notes |
|-----------|--------------|-----------------|----------------|-------|
| **RNode (LoRa)** | RNodeInterface | None yet | ❌ Needs hardware | USB LoRa radio. styrene-edge provisions these. ExplorationScreen shows RNodes. Can't CI without hardware or emulator. |
| **Serial** | SerialInterface | None yet | ⚠️ Virtual serial (socat) | RS-232/UART. Edge devices use this. Could CI with `socat` virtual serial pairs. |
| **KISS** | …

### Tier 3: Infrastructure-level, not styrened's concern

| Transport | RNS Interface | Notes |
|-----------|--------------|-------|
| **UDP** | UDPInterface | Used internally by RNS, not user-configured in styrened |
| **Local** | LocalInterface | RNS shared instance IPC, not a network transport |
| **Backbone** | BackboneInterface | RNS internal |
| **Weave** | WeaveInterface | RNS internal mesh fabric |
| **RNodeMulti** | RNodeMultiInterface | Multi-radio variant of RNode — same hardware constraint |

### WireGuard/MeshVPN testing — distinct from RNS transports

**WireGuard (MeshVPN) is NOT an RNS transport.** It's an IP tunnel bootstrapped over RNS:

1. Two peers establish an RNS.Link via DirectLinkService
2. They exchange WireGuard public keys over the `/vpn/handshake` link request path
3. Each side configures a local wg-styrene interface with the exchanged keys
4. IPv6 ULA addresses derived from identity hashes — deterministic, no DHCP
5. Gateway nodes optionally bridge wg-styrene into bat0 (BATMAN-ADV mesh)

**What to test:**
- Key exchange succeeds…

### Proposed transport test tiers

**Four transport testing tiers, layered on the existing test hierarchy:**

### 1. TCP Localhost (default — already planned)

- Part of the smoke tier, no extra dependencies
- `tests/fixtures/transports/tcp_localhost.yaml`
- Every TUI pilot test runs over this by default

### 2. AutoInterface (multicast discovery)

- Lightweight add-on to smoke tier
- Verifies local peer discovery without explicit peer config
- Caveat: platform-specific (macOS utun errors)
- `@pytest.mark.auto_interface`

### 3. Overlay Networks (I2P, Yggdrasil)

- Dedicated CI tier, nightly only for I2P
- Sidecar containers in K8s test pods
- Proves RNS-level connectivity over anonymous/encrypted overlays
- `@pytest.mark.yggdrasil`, `@pytest.mark.i2p`

### 4. IP Tunnel (WireGuard MeshVPN)

- Requires NET_ADMIN in K8s pods + wireguard-tools
- Tests bootstrapping over an *existing* RNS path (TCP or overlay)
- Layered on top of Tier 1 or 3
- `@pytest.mark.wireguard`

### 5. Hardware Radio (RNode/Serial/KISS) — deferred

- Needs physical hardware or socat virtual serial emulation
- Relevant for styrene-edge, not general CI
- PipeInterface could serve as a stand-in for serial-like transports
- `@pytest.mark.hardware` — always skipped in CI, run manually on edge devices

### What each tier proves:

| Tier | Announces | Chat/LXMF | RPC | DirectLink | MeshVPN | discovered_via |
|------|-----------|-----------|-----|------------|---------|----------------|
| TCP | ✅ | ✅ | ✅ | ✅ | N/A | TCP interface name |
| Auto | ✅ | ✅ | ✅ | ✅ | N/A | AutoInterface |
| Yggdrasil | ✅ | ✅ | ✅ | ✅ | N/A | Yggdrasil interface |
| I2P | ✅ | ✅ | ⚠️ slow | ⚠️ timeout | N/A | I2P interface |
| WireGuard | N/A | N/A | N/A | N/A | ✅ IPv6 ping | N/A |
| Hardware | ✅ | ✅ | ✅ | ⚠️ bandwidth | N/A | RNode/Serial name |
