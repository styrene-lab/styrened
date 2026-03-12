# Operator Interface Testing Paths — Design

## Architecture Decisions

### Decision: Hybrid test peer lifecycle: in-process for fast, K8s for multi-peer

**Status:** decided
**Rationale:** TUI pilot tests need to be fast (< 30s) and portable (no container runtime required). In-process daemon subprocesses with temp config dirs and fixed identity keys on localhost TCP achieve this. Multi-peer RBAC scenarios reuse the existing K8sTestHarness which already handles pod lifecycle, namespace cleanup, and multi-node orchestration. This avoids coupling fast TUI smoke tests to K8s infrastructure.

### Decision: Poll-with-timeout + aggressive intervals for timing non-determinism

**Status:** decided
**Rationale:** Hard-coded sleeps are fragile and slow. In-process peers on localhost with announce_interval=1 and auto_reply_cooldown=1 compress real-world 30s+ delays to < 2s. Assertions use poll-with-timeout pattern (already proven in K8s harness). Tests tagged with pytest.mark.timeout for enforcement. No hard sleeps anywhere.

### Decision: RBAC testing in three phases: single-peer → two-peer → stranger

**Status:** decided
**Rationale:** Phase 1 (single ADMIN-tier peer) validates all operations work when permitted — this is the current Test Peer Alpha path. Phase 2 (PEER + OPERATOR tiers) tests capability gating at the TUI level. Phase 3 (STRANGER) tests minimal-trust discovery. Each phase requires fixed identity keys in test fixtures so role assignments are deterministic. Phase 2+ deferred until TUI conditionally hides operations based on peer capabilities.

### Decision: Pre-generated fixture keys with host admin pre-seeded into peer RBAC

**Status:** decided
**Rationale:** Committed identity keys give deterministic hashes for assertions and role assignments. Pre-loading the host operator as ADMIN in each peer's config eliminates permission setup timing issues — tests start with full access from the first announce.

### Decision: Full daemon + full TUI fidelity — no stripped-down test mode

**Status:** decided
**Rationale:** This test tier exists to catch bugs that only manifest when the full stack is wired together (daemon, IPC, TUI rendering, protocol handling). A stripped-down mode would defeat the purpose. The existing mock-based unit tests and CLI e2e tests already cover the fast/cheap tiers. This is the top of the pyramid — slow, high-fidelity, human-simulation level.

### Decision: Transport-parameterized fixtures: identity is fixed, transport is a config overlay

**Status:** decided
**Rationale:** Identity keys are transport-independent — the same alpha/bravo/host fixtures work regardless of whether peers connect via TCP, I2P, or Yggdrasil. Transport config is an overlay applied to the base fixture at test time: TCP for fast local tests, I2P/Yggdrasil for transport-specific CI tiers. This avoids duplicating fixtures per transport and keeps the fixture directory structure stable as new transports are added.

## Research Context

### Test Peer Alpha — known assertion values

From the screenshot and container logs, these are the deterministic values for Test Peer Alpha that any automated test can assert against:

| Field | Value |
|---|---|
| Name | 🤖 Test Peer Alpha |
| Type | STYRENE NODE |
| Identity | 343db07eae61371988d4d51a546d2c62 |
| LXMF | 4cebd7cbaba50624c4d05d9eedd13b1d |
| Hops | 1 hop |
| Via | Test Peer Alpha → ff165b60 |
| Auto-reply message | "Roger that — Test Peer Alpha received your transmission. Standing by." |
| Auto-reply cooldown | 10s |
| RPC | enabled, command execution enabled |
| Container | podman, ghcr.io/styrene-lab/styrened:latest (linux/amd64 under emulation) |
| Port | 5252 (TCP server, port-forwarded to host) |

Note: Identity hash is generated fresh each container creation. For fully reproducible tests, we'd need to bake a fixed identity key into the container config.

### Existing test infrastructure survey

Three existing test layers relevant to operator interface testing:

1. **tests/tui/e2e/** — CLI-driven e2e tests against real network. Config-file driven (e2e_config.yaml, gitignored). Fixtures for hub/node configs, timeout settings. Tests: hub_connectivity, node_discovery, rpc_roundtrip. Requires live peers. Currently hardcoded to brutus hub + q502 node.

2. **tests/harness/k8s/** (K8sTestHarness) — Helm-based pod lifecycle in ephemeral namespaces. Creates styrened pods with known configs, waits for announces, runs assertions. Used by tests/k8s/scenarios/ (smoke/integration/comprehensive tiers). Handles cleanup of orphaned namespaces.

3. **tests/tui/{widgets,models,screens,services}/** — Unit tests for TUI components using mocks. No live daemon. Tests widget rendering, model logic, screen composition.

**Gap**: No test layer that drives the actual TUI (via Textual pilot) against a live peer with known values. The e2e tests use CLI commands, not the TUI. The TUI unit tests use mocks, not live peers.

### Q1: Test peer lifecycle in CI

**Options considered:**

**A. Podman sidecar in Argo Workflow** — Each workflow step gets a sidecar container running styrened. Argo supports sidecars natively. Pros: mirrors local dev (podman run). Cons: Argo sidecar lifecycle is tied to the step, not easily shared across steps; podman-in-podman adds complexity.

**B. K8s pod fixture (extend K8sTestHarness)** — Spin up test peer pods in the same ephemeral namespace the K8s harness already manages. Pros: existing infrastructure, cleanup already handled, peers can talk via cluster DNS. Cons: heavier than needed for TUI-level tests, couples TUI tests to K8s.

**C. In-process daemon (no container)** — Start a styrened daemon in a subprocess within the test process. Configure it with a temp directory, known identity, TCP server port. Pros: fastest, no container runtime needed, works in any CI, deterministic identity. Cons: requires careful process lifecycle, port allocation.

**D. Hybrid: in-process for unit/smoke, K8s for integration** — Use option C for fast TUI pilot tests (< 30s), option B for multi-peer RBAC scenarios that need real network topology.

**Recommendation: D (hybrid).** The TUI pilot tests should be fast and portable — they don't need containers. Spawn a styrened subprocess with a temp config dir and fixed identity key, connect via localhost TCP. For RBAC multi-peer scenarios, reuse the K8s harness which already handles multi-pod orchestration.

### Q2: Non-deterministic timing in automated assertions

**Problem**: Announce propagation (up to announce_interval seconds), message delivery (RNS path discovery + LXMF routing), and RPC responses all have variable latency. Hard-coded sleeps are fragile; no-wait assertions miss real timing.

**Strategies:**

1. **Poll-with-timeout pattern** — `await_condition(lambda: widget.text == expected, timeout=15)`. Already used in K8s harness (`wait_for_announces`). For TUI pilot: poll widget state in a loop with `app.process_events()` between iterations.

2. **Event-driven waits** — Watch for specific Textual messages/events rather than polling widget text. E.g., wait for `DeviceStatusWidget.StatusLoaded` message rather than checking if the loading spinner disappeared.

3. **Shrink the timing window** — For in-process peers, set `announce_interval: 1` and `auto_reply_cooldown: 1`. Localhost TCP has negligible latency. The 30s+ delays of real mesh networks compress to < 2s.

4. **Separate timing tiers**:
   - **Fast assertions** (< 2s): widget composition, button existence, navigation, panel rendering — no network.
   - **Medium assertions** (2-10s): announce discovery, RPC status, auto-reply round-trip over localhost.
   - **Slow assertions** (10-60s): only for real mesh scenarios in K8s tier.

**Recommendation**: Combine strategies 1+3. In-process peers with aggressive intervals + poll-with-timeout. Tag tests with `@pytest.mark.timeout(10)` for medium, never hard-sleep.

### Q3: Gradual RBAC testing introduction

**Current RBAC model**: Roles (STRANGER/PEER/OPERATOR/ADMIN) with cumulative capabilities. Configured via `rbac:` section in core-config.yaml. 60+ unit tests cover policy logic. Gap: no integration test verifying that a PEER-tier peer actually gets denied ADMIN-tier operations through the TUI.

**Phased approach:**

**Phase 1 (now)**: Single peer, ADMIN-equivalent (full access). Validates that all operations work when permitted. This is what Test Peer Alpha does today.

**Phase 2**: Two peers — one PEER-tier, one OPERATOR-tier. Test that:
- PEER can chat but cannot exec commands
- OPERATOR can exec but cannot reboot
- TUI correctly shows "permission denied" or hides unavailable operations

**Phase 3**: STRANGER-tier peer. Test that:
- Auto-discovery works but operations are restricted
- TUI grays out / hides tabs for unauthorized operations
- Capability negotiation over DirectLink /meta endpoint

**Implementation**: Each peer is an in-process daemon subprocess with its own config dir. The *host* daemon's RBAC config assigns different roles to each peer's identity hash. Since identity hashes are baked into the fixture (fixed key files), role assignments are deterministic.

**Key fixture design:**
```
tests/fixtures/test_peers/
├── alpha/           # ADMIN-tier peer
│   ├── identity     # Fixed RNS identity key
│   └── config.yaml  # display_name, auto_reply, etc.
├── bravo/           # PEER-tier peer
│   ├── identity
│   └── config.yaml
└── host_rbac.yaml   # Role assignments by identity hash
```

**Recommendation**: Phase 1 first (complete the single-peer test paths). Phase 2 when the RBAC enforcement at the TUI layer is more mature (currently RBAC is only enforced daemon-side, TUI doesn't conditionally hide operations based on peer role).

### Q1 resolved: Pre-generated fixture keys with admin pre-seeded

Generate a handful of RNS identity keys offline and commit them to `tests/fixtures/test_peers/`. Each peer fixture directory gets:
- A fixed identity key file (deterministic identity_hash forever)
- A core-config.yaml with display_name, icon, auto_reply, etc.
- The **host operator's** public key pre-loaded into the peer's RBAC config as ADMIN

This means the test host always has full admin access to every test peer from the start — no capability negotiation delay, no race between announce and permission setup. The peer identity hashes are known constants that can be used directly in assertions and RBAC role assignments on the host side too.

Fixture structure:
```
tests/fixtures/test_peers/
├── alpha/
│   ├── identity          # pre-generated, committed
│   ├── core-config.yaml  # auto_reply, display_name, rbac grants host as ADMIN
│   └── README.md         # identity_hash, lxmf_hash for quick reference
├── bravo/
│   ├── identity
│   ├── core-config.yaml
│   └── README.md
└── host/
    ├── identity          # the "operator under test" identity
    └── core-config.yaml  # rbac: assigns roles to alpha/bravo by hash
```

### Q2 resolved: Full daemon, full TUI — human-simulation fidelity

The entire point of this test tier is to be the most robust testing we have — simulating what an actual operator does through the TUI. No stripped-down test mode, no mock shortcuts. Full daemon subprocess, full TUI via Textual pilot.

This means:
- Test peer runs a real `styrened daemon` (full service stack: RNS, LXMF, RPC, auto-reply, page server)
- Host runs a real `StyreneApp` via Textual pilot (full TUI with all screens, widgets, IPC bridge)
- Assertions verify what the operator would see: widget text, screen transitions, toast notifications, panel content
- Network operations go through the real protocol stack over localhost TCP

This is explicitly NOT a unit test layer. It's the top of the test pyramid — slow, integration-heavy, high-fidelity. The existing mock-based TUI tests and CLI e2e tests cover the fast/cheap tiers. This tier catches the bugs that only manifest when everything is wired together (like RemoteStatusInfo.hostname — the model, widget, daemon response, and RPC all had to interact to trigger it).

### Transport-agnostic fixture design for I2P/Yggdrasil extensibility

**Current state**: I2P and Yggdrasil are already declared in `InterfaceBoundary` enum and the Comms screen has hidden sections that reveal when those transports are active. But `InterfaceConfig` only models TCP (peers, server) and AutoInterface (local UDP). No I2PInterface or YggdrasilInterface config stanzas yet.

**What changes when they arrive**:
- `InterfaceConfig` gains `i2p: I2PInterfaceConfig` and `yggdrasil: YggdrasilInterfaceConfig` fields
- `generate_rns_config()` writes additional RNS interface stanzas
- The Comms screen unhides and becomes functional
- Peers may be reachable only via I2P (.i2p addresses) or Yggdrasil (200:/8 IPv6) instead of TCP
- Discovery path changes: announces arrive via I2P/Yggdrasil interfaces, `discovered_via` field reports the transport

**Testing implications**:
1. **Fixture identity is transport-independent** — the pre-generated identity keys don't care how the peer is reached. Same identity_hash whether connected via TCP, I2P, or Yggdrasil.
2. **Transport is a fixture parameter, not a fixture structure** — a test peer's config.yaml specifies which interfaces to enable. The same alpha/bravo/host fixture dirs can be parameterized with different transport configs.
3. **Some transports need external dependencies** — I2P requires a running I2P router (i2pd or Java I2P), Yggdrasil requires a running yggdrasil daemon. These can't be trivially in-process.
4. **Localhost TCP remains the fast-path default** — I2P/Yggdrasil tests are inherently slower (tunnel establishment, endpoint discovery) and need their own CI tier.

**Current RNS support**: RNS already has I2PInterface and TCPOverI2PInterface, plus can run over Yggdrasil via its standard TCPInterface (Yggdrasil provides IPv6 connectivity that RNS TCP uses directly). So the RNS layer handles the transport — styrened just needs to configure the right interfaces.

## File Changes

- `tests/fixtures/test_peers/alpha/identity` (new) — Pre-generated RNS identity key for test peer alpha (committed, deterministic hash)
- `tests/fixtures/test_peers/alpha/core-config.yaml` (new) — Base config for alpha — identity, display_name, auto_reply, RBAC grants. Transport-agnostic.
- `tests/fixtures/test_peers/host/identity` (new) — Pre-generated RNS identity key for the operator under test
- `tests/fixtures/test_peers/host/core-config.yaml` (new) — Base config for host — RBAC role assignments by peer hash. Transport-agnostic.
- `tests/fixtures/transports/tcp_localhost.yaml` (new) — Transport overlay: TCP on localhost with dynamic port allocation
- `tests/fixtures/transports/yggdrasil.yaml` (new) — Transport overlay: Yggdrasil IPv6 peer addresses (populated by CI fixture)
- `tests/fixtures/transports/i2p.yaml` (new) — Transport overlay: I2P SAM bridge addresses (populated by CI fixture)
- `tests/conftest_operator.py` (new) — Session-scoped fixtures: start daemon subprocesses with merged base+transport configs, wait for announces, yield to tests, teardown

## Constraints

- Identity fixtures must be committed to git — they contain only test keys, never real operator keys
- Transport overlays are merged on top of base peer configs at test startup — deep merge, transport wins
- I2P tests must be marked @pytest.mark.i2p and skipped when i2pd is unavailable
- Yggdrasil tests must be marked @pytest.mark.yggdrasil and skipped when yggdrasil is unavailable
- TCP localhost tests have no external dependencies and are the default tier
