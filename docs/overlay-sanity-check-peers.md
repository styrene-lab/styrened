---
id: overlay-sanity-check-peers
title: Overlay Sanity-Check Peer Infrastructure
status: exploring
parent: test-path-overlay-transports
tags: [testing, k8s, yggdrasil, i2p, sidecar, sanity-check]
open_questions: []
---

# Overlay Sanity-Check Peer Infrastructure

## Overview

Explore a lightweight internal test fixture that gives styrened a known-good overlay peer to sanity-check adapter health and basic end-to-end connectivity. Compare dedicated K8s sidecars, standalone overlay peer pods, and mixed 'adapter canary' services for Yggdrasil and I2P.

## Research

### Problem framing: adapter health today proves only local process readiness

Current adapter states are useful but shallow: Yggdrasil READY means the admin socket responds and I2P READY means the local proxy/control surface responds. Neither proves that the overlay can actually reach a peer, route traffic, or carry an RNS session. For operator confidence and CI sanity checks, we need a known-good remote endpoint that exercises at least one real peer path over each overlay. The desired outcome is a low-noise internal canary: when it is healthy, we know the overlay plus styrened integration path is healthy enough for basic use; when it is unhealthy, we can tell whether the failure is local-process, overlay-network, or end-to-end peer reachability.

### Three candidate architectures for internal overlay sanity peers

**Option A — sidecars only, per-test ephemeral peers**
- Each K8s test pod gets a yggdrasil or i2pd sidecar plus a paired remote pod in the same ephemeral namespace.
- Best for CI realism and isolation.
- Weak for day-to-day operator sanity checks because the peer exists only during test runs.
- Operationally cheap because it reuses the K8s test harness already envisioned by test-path-overlay-transports.

**Option B — dedicated long-lived canary overlay pods inside the cluster**
- Run one or two always-on pods per overlay (e.g. `styrene-ygg-canary`, `styrene-i2p-canary`) with stable configs and a tiny health/readiness API.
- Local/dev styrened instances can point adapters or test traffic at these peers to answer 'does this overlay work against a known-good remote endpoint?'.
- Strongest value for quick operator sanity checks and for pre-flight diagnostics.
- Requires cluster-exposed bootstrap points and careful scoping so the canaries are not mistaken for general-purpose public infrastructure.

**Option C — dedicated overlay-only daemons plus a minimal styrened peer behind them**
- Split the canary into two pieces: the overlay daemon container and a tiny styrened peer container that exposes exactly the RNS/LXMF surfaces we want to test.
- Gives clean attribution: overlay unhealthy vs styrened unhealthy.
- Slightly more moving parts, but the decomposition aligns with the adapter model and with K8s sidecar composition. This is the most diagnosable shape if we want the same pattern for both CI and internal operator checks.

Initial read: Option C is the best long-term architecture; Option A remains the CI execution mode; Option B becomes the operational deployment form of the Option C components.

### Overlay-specific realities: Yggdrasil is easy canary material, I2P is not symmetrical

**Yggdrasil** is ideal for a canary peer. It boots quickly, peers deterministically via static config, and a managed local adapter can become READY within ~30s. A cluster-hosted Ygg canary can expose a stable peering endpoint and host a minimal styrened peer reachable over Ygg IPv6. This makes it suitable for both CI and interactive sanity checks.

**I2P** is trickier. An I2P router being locally healthy does not mean tunnels are built or that a remote eepsite/SAM peer is ready. Cold-start times are measured in minutes, and a private two-router island may not reflect real-world behavior unless we intentionally design it as an internal-only test fabric. Therefore the I2P sanity check should be framed as a slower 'eventually healthy' readiness probe, probably nightly or on-demand, rather than a fast startup canary. For local operator UX, I2P likely needs a richer state model: local-router-ready vs remote-peer-reachable.

### Canary portfolio should include a non-RNS radio bridge lane

Adding Meshtastic broadens the canary strategy beyond overlay adapters. This suggests three canary lanes rather than one homogeneous system: (1) fast overlay canaries (Yggdrasil), (2) slow/eventual overlay canaries (I2P), and (3) radio-bridge canaries (Meshtastic). The radio lane should not be forced into the same success semantics as overlays. Overlay canaries answer 'can I form an end-to-end peer path?'; Meshtastic canaries answer 'is the bridge healthy and can I observe a radio-side neighbor or simulator?'. Keeping these lanes separate prevents us from weakening the overlay model or over-claiming what a Meshtastic check proves.

### Adapter inventory check: what exists now vs what is provision-shaped vs what is out of scope

A quick inventory suggests we are not missing any *currently live* COP adapter-registry integrations beyond the ones already discussed. The daemon's AdapterRegistry currently registers only I2P and Yggdrasil adapters, and the runtime probe loop emits adapter_changed for those two. Meshtastic exists as a separate decided bridge concept rather than a registered overlay adapter. There are also adjacent transport/boundary concepts that should not be forced into the same canary bucket: WireGuard exists as MeshVPN/identity/boundary work, but it is a peer-to-peer VPN service rather than a discovery/bootstrap adapter like I2P/Ygg. Meanwhile the provisioning/RPC layer already names additional future adapter candidates — Lokinet and cjdns — which makes them the clearest 'missing adapter' placeholders if we want to expand beyond today's implemented surfaces. So the current landscape is: implemented adapter-registry surfaces = {Yggdrasil, I2P}; separate radio bridge lane = {Meshtastic}; future-but-not-yet-realized overlay candidates = {Lokinet, cjdns}; adjacent but different class = {WireGuard/MeshVPN}.

## Decisions

### Decision: Canary portfolio is split into overlay-fast, overlay-slow, and radio-bridge lanes

**Status:** decided
**Rationale:** The canary system should not pretend every transport proves the same thing. Yggdrasil belongs in a fast overlay lane because it boots quickly and can provide prompt end-to-end peer validation. I2P belongs in a slower eventual-health lane because tunnel establishment latency makes it unsuitable as a startup-fast signal. Meshtastic belongs in a separate radio-bridge lane because it validates bridge health and radio-neighbor visibility rather than overlay peer reachability. This keeps operator semantics honest and avoids collapsing incompatible transport classes into one health model.

### Decision: First fast overlay canary is Yggdrasil; I2P is deferred to slower nightly or on-demand validation

**Status:** decided
**Rationale:** Yggdrasil is the best first canary because it is deterministic, fast to bootstrap, and can expose a stable peer endpoint that proves the adapter→overlay→styrened path quickly enough to be useful in CI and operator diagnostics. I2P remains important, but its router/tunnel warm-up time makes it a poor fast-health signal. Treating I2P as a slower nightly or on-demand canary gives more truthful operator feedback and avoids false expectations during short-lived test runs.

### Decision: Long-lived overlay canaries should expose a minimal styrened peer surface, not bootstrap only

**Status:** decided
**Rationale:** A bootstrap-only canary would prove only daemon or peering reachability, not the end-to-end path styrened actually depends on. The long-lived canary should therefore pair the overlay daemon with a minimal styrened peer surface such as announce, chat echo, and /status. This gives clearer attribution and validates the full adapter→RNS→styrened path while keeping the canary intentionally narrow in scope.

### Decision: Current canary scope is Yggdrasil, I2P, and Meshtastic; Lokinet and cjdns remain future candidates

**Status:** decided
**Rationale:** The current code and design surface only make Yggdrasil and I2P real adapter-registry citizens, with Meshtastic already scoped as a separate bridge lane. Lokinet and cjdns appear today as provisioning/RPC placeholders rather than implemented daemon adapters, so they should be tracked as future candidates rather than first-wave canary commitments. WireGuard/MeshVPN is excluded from adapter-canary scope because it is a different service class with different semantics.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- Current first-wave canary scope is Yggdrasil (fast overlay), I2P (slow/eventual overlay), and Meshtastic (separate radio-bridge lane).
- Long-lived overlay canaries should be shaped as overlay daemon plus minimal styrened peer surface; bootstrap-only checks are insufficient for the target confidence level.
- Lokinet and cjdns are tracked only as future adapter-canary candidates until they become real daemon adapter implementations.
- WireGuard/MeshVPN is out of scope for adapter-canary work because it is a different service class with different operator semantics.
