# Test Path: Overlay Transports (I2P, Yggdrasil) — Design

## Architecture Decisions

### Decision: Five transport test tiers: TCP → Auto → Overlay → WireGuard → Hardware

**Status:** decided
**Rationale:** Each tier adds external dependencies and CI complexity. TCP localhost is the zero-dependency default. AutoInterface adds multicast but no sidecars. Overlays (I2P/Yggdrasil) need sidecar daemons. WireGuard needs NET_ADMIN + kernel module. Hardware needs physical devices. Each tier uses the same fixture identity keys — only the transport overlay config changes. Tests at higher tiers can be gated by pytest markers and skipped when dependencies are unavailable.

### Decision: WireGuard tests are layered above RNS transport tests, not parallel to them

**Status:** decided
**Rationale:** MeshVPN is not an RNS interface — it's an IP tunnel bootstrapped over an existing RNS.Link via DirectLinkService. WireGuard tests verify key exchange, interface creation, and IPv6 connectivity. They always need a working RNS transport underneath (TCP or overlay). This makes them orthogonal to the transport tier — a WireGuard test can run over TCP localhost or over Yggdrasil. Don't conflate IP-layer testing with RNS-layer testing.

### Decision: Hardware radio tests deferred to styrene-edge — not in styrened CI

**Status:** decided
**Rationale:** RNode/Serial/KISS/AX.25 require physical hardware or emulation (socat virtual serial). styrene-edge provisions and manages these devices. PipeInterface could serve as a serial-like stand-in for protocol validation, but the real value is hardware-in-the-loop testing on edge devices. Keep in styrene-edge's test suite, not styrened's.

### Decision: CLI for protocol verification, TUI pilot only for transport-specific UI (Comms screen, discovered_via)

**Status:** decided
**Rationale:** The TUI rendering is transport-agnostic — buttons, tabs, navigation are identical over TCP or Yggdrasil. Full TUI pilot over every transport is redundant with the TCP pilot tests. What changes per-transport: (1) discovered_via field shows the transport interface name, (2) Comms screen sections reveal when I2P/Ygg are active, (3) I2P latency makes loading/timeout states visible. So: run the full operator path test suite once over TCP (Tier 1). For overlay tiers, use CLI (styrened devices, styrened send) to prove protocol-level connectivity, plus a small targeted TUI pilot test for Comms screen state and discovered_via rendering. This avoids doubling test runtime for no coverage gain.

### Decision: Upstream images with config injection — no custom builds

**Status:** decided
**Rationale:** i2pd: use purplei2p/i2pd (official upstream on Docker Hub). Supports config via volume mount or environment variables. Mount a pre-generated i2pd.conf and tunnels.conf into the container. Yggdrasil: no official image exists — use community image (gitlab.com/oci-containers/yggdrasil-go or build a minimal one from the yggdrasil-go binary in a scratch/alpine base). Config via yggdrasil.conf volume mount with pre-generated keys and static peer list. Both sidecars share the test pod's network namespace (localhost), so SAM bridge (i2pd) and TCP listener (yggdrasil IPv6) are reachable from the styrened container at 127.0.0.1. No custom image builds needed — just config files in tests/k8s/sidecars/.

### Decision: K8s pod sidecars sharing network namespace, managed by test harness

**Status:** decided
**Rationale:** Each test pod runs: styrened container + transport sidecar(s) in the same network namespace. Sidecar lifecycle managed by the K8s harness (extend pod spec templates in tests/k8s/). For Yggdrasil: two pods each with a yggdrasil sidecar, peered to each other via ClusterIP service (Ygg peers list). Mesh forms in < 5s. styrened configures TCPClientInterface pointing to the remote pod's Yggdrasil IPv6 address. For I2P: two pods each with an i2pd sidecar. Private I2P network via floodfill reseed between the two routers. Tunnel establishment takes 2-5min — session-scoped fixture with generous startup wait. styrened configures I2PInterface pointing to localhost SAM bridge (port 7656). WireGuard: no sidecar needed — wireguard-tools installed in test image, NET_ADMIN capability added to pod security context.

## Research Context

### Transport dependency landscape

**I2P**:
- RNS has native `I2PInterface` — connects to a running I2P router's SAM bridge (default port 7656)
- i2pd (C++ daemon) is lightweight, available as Alpine/Debian package, and runs headless — ideal for containers
- Two styrened peers talking over I2P need: i2pd router A ↔ i2pd router B (tunnel mesh), styrened A configures I2PInterface pointing to router A's SAM, styrened B to router B's SAM
- I2P tunnel establishment takes 2-5 minutes for initial setup (building tunnels, finding peers) — cold start is slow
- For CI: two i2pd containers with `--reseed.floodfill` pointed at each other can form a private I2P network (no public reseed needed)

**Yggdrasil**:
- Yggdrasil provides IPv6 overlay — RNS TCPInterface works over Yggdrasil IPv6 addresses directly (no special RNS interface needed)
- yggdrasil daemon is a single static binary, ~10MB, available for all platforms
- Two nodes form a mesh by listing each other as `Peers:` in yggdrasil.conf — no external infrastructure
- Yggdrasil mesh establishment is fast (< 5s for two peers on localhost or LAN)
- For CI: two yggdrasil containers peered to each other, styrened peers configured with Yggdrasil 200:/8 addresses as TCP peers

**Key difference**: I2P is slow to bootstrap (minutes) but provides strong anonymity. Yggdrasil is fast (seconds) and provides encrypted IPv6 routing. Testing strategies differ accordingly.

### CI tier placement

These don't belong in the fast TUI pilot tier. They belong in their own transport-specific CI tier:

**Test tier hierarchy with transports:**
```
smoke (< 30s)     — in-process daemon, localhost TCP, TUI pilot
                    No transport dependencies beyond loopback

integration       — K8s harness, multi-peer, RBAC
                    TCP between pods in same namespace

yggdrasil (new)   — Two yggdrasil sidecars + two styrened pods
                    Verify: announce discovery over Yggdrasil
                    Verify: chat/RPC/DirectLink over Yggdrasil IPv6
                    Verify: discovered_via reports Yggdrasil interface
                    Verify: TUI Comms screen shows Yggdrasil active
                    Timeout: < 2 min (fast mesh establishment)

i2p (new)         — Two i2pd sidecars + two styrened pods  
                    Verify: announce discovery over I2P
                    Verify: chat over I2P (RPC may timeout)
                    Verify: discovered_via reports I2P interface
                    Verify: TUI Comms screen shows I2P active
                    Timeout: < 10 min (slow tunnel establishment)
                    Run: nightly only (too slow for PR validation)

comprehensive     — Large topologies, mixed transports
                    Some peers on TCP, some on Yggdrasil
                    Verify: cross-transport routing works
```

**pytest markers**: `@pytest.mark.yggdrasil`, `@pytest.mark.i2p` — skip when external daemons unavailable.

**CI dependency management**: K8s pods with sidecar containers. Each test namespace gets:
- styrened pod + i2pd sidecar (sharing localhost network)
- styrened pod + yggdrasil sidecar (sharing localhost network)
- Sidecars pre-configured to peer with each other via ClusterIP services

### Full RNS transport inventory and testing assessment

RNS supports 13 interface types. Assessing each for styrened testing relevance:

### Tier 1: Already modeled in styrened config, need test paths

| Transport | RNS Interface | styrened Config | CI Feasibility | Notes |
|-----------|--------------|-----------------|----------------|-------|
| **TCP** | TCPClientInterface, TCPServerInterface | InterfaceConfig.peers, .server | ✅ Trivial (localhost) | Default test transport. Already working. |
| **AutoInterface** | AutoInterface | InterfaceConfig.auto | ✅ Localhost multicast | UDP multicast on loopback. Platform quirks (macOS utun errors). |
| **I2P** | I2PInterface | I2PConfig | ⚠️ Slow (2-5min tunnel setup) | Needs i2pd sidecar. Already has config model + Comms screen section. |
| **Yggdrasil** | TCPInterface over Ygg IPv6 | YggdrasilConfig | ✅ Fast (< 5s mesh) | Needs yggdrasil sidecar. Already has config model + Comms screen + bootstrap_from_rns. |
| **WireGuard (MeshVPN)** | N/A (IP layer, not RNS interface) | MeshVPNConfig | ⚠️ Needs wg tooling | Not an RNS transport — it's an IP tunnel bootstrapped *over* RNS.Link via DirectLinkService. Tests verify tunnel establishment, not RNS message passing. |

### Tier 2: Relevant for edge devices, need consideration

| Transport | RNS Interface | styrened Config | CI Feasibility | Notes |
|-----------|--------------|-----------------|----------------|-------|
| **RNode (LoRa)** | RNodeInterface | None yet | ❌ Needs hardware | USB LoRa radio. styrene-edge provisions these. ExplorationScreen shows RNodes. Can't CI without hardware or emulator. |
| **Serial** | SerialInterface | None yet | ⚠️ Virtual serial (socat) | RS-232/UART. Edge devices use this. Could CI with `socat` virtual serial pairs. |
| **KISS** | KISSInterface | None yet | ⚠️ Virtual serial | TNC protocol over serial. Similar to Serial — socat feasible. |
| **AX.25 KISS** | AX25KISSInterface | None yet | ❌ Needs TNC or emulator | Amateur radio packet. No easy CI path. |
| **Pipe** | PipeInterface | None yet | ✅ Named pipes | stdin/stdout pipe between processes. Trivially CI-able. |

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
- Key exchange succeeds over DirectLink
- wg-styrene interface comes up with correct IPv6 address
- IPv6 ping between mesh VPN peers works
- Gateway mode bridges into bat0 (Linux only)
- Teardown cleans up WireGuard interface

**CI feasibility:**
- Linux: ✅ kernel WireGuard (`ip link add wg-styrene type wireguard`) — needs NET_ADMIN capability in K8s pod
- macOS: ⚠️ userspace wg-quick — works but needs wireguard-tools installed
- Containers: K8s pods with `securityContext.capabilities.add: [NET_ADMIN]` + wireguard-tools in test image

**Key distinction**: TCP/I2P/Yggdrasil tests verify *RNS-level* connectivity (announces, LXMF, RPC). WireGuard tests verify *IP-level* connectivity bootstrapped over an already-working RNS path. WireGuard tests always need a working RNS transport underneath — they're a layer above.

**BATMAN-ADV testing:**
- bat0 mesh interface requires Linux kernel module (`modprobe batman-adv`)
- Only testable in K8s pods with privileged containers or on bare metal
- Edge-device specific — relevant for styrene-edge, not for general styrened testing
- Defer to styrene-edge repo's own test suite

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

## File Changes

- `tests/fixtures/transports/auto_interface.yaml` (new) — Transport overlay: AutoInterface enabled with ignored_interfaces for CI stability
- `tests/fixtures/transports/wireguard.yaml` (new) — Transport overlay: MeshVPN enabled with test listen port (requires working RNS transport underneath)
- `tests/k8s/sidecars/i2pd.yaml` (new) — K8s sidecar container spec for i2pd in test pods
- `tests/k8s/sidecars/yggdrasil.yaml` (new) — K8s sidecar container spec for yggdrasil in test pods

## Constraints

- I2P tests nightly-only due to 2-5min tunnel establishment time
- WireGuard tests require NET_ADMIN capability in K8s pods
- BATMAN-ADV tests require privileged containers + kernel module — defer to styrene-edge
- All transport tiers reuse the same fixture identity keys from tests/fixtures/test_peers/
- PipeInterface can serve as hardware radio stand-in for protocol-level validation without physical devices
