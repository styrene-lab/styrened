---
id: meshtastic-canary-shape
title: Meshtastic Canary Shape
status: exploring
parent: overlay-sanity-check-peers
related: [meshtastic-bridge]
tags: [testing, meshtastic, canary, radio, bridge]
open_questions: []
---

# Meshtastic Canary Shape

## Overview

Explore how Meshtastic fits into the canary strategy alongside overlay peers. Because Meshtastic is a radio-local bridge with a hard trust boundary, determine whether the canary should use attached hardware, a simulator/emulator, or a gateway-style test fixture, and what signal it should provide to operators.

## Research

### Meshtastic canary is not the same class of problem as Yggdrasil/I2P

Meshtastic does belong in the broader canary story, but not as an overlay peer in the same sense as Yggdrasil or I2P. The existing Meshtastic Bridge Service decision is explicitly radio-only and rejects MQTT as the primary interface. That means a cluster-native 'Meshtastic canary pod' is not protocol-real unless it is backed by either (a) attached radio hardware, or (b) a simulator/emulator that behaves enough like a local Meshtastic node over the Python client transport. In other words: Ygg/I2P canaries validate network overlays; a Meshtastic canary validates bridge health and radio-neighbor visibility across a hardware or simulation boundary.

### Candidate Meshtastic canary forms

**Option M1 — hardware-attached canary gateway**
- A long-lived pod or small edge node has a real Meshtastic radio connected over USB serial.
- Best fidelity: proves the real bridge path the product actually supports.
- Weakness: hardware lifecycle, USB passthrough, and radio environmental variability make it harder to reproduce in CI.

**Option M2 — Meshtastic simulator/emulator-backed canary**
- Use a deterministic simulator or protocol stub that exposes the same local interface the meshtastic Python package expects.
- Best for CI and repeatable health checks.
- Risk: can drift from real firmware behavior and gives weaker confidence than hardware.

**Option M3 — split canary tiers**
- Fast canary: simulator-backed bridge sanity check in CI and maybe in-cluster.
- Slow/authoritative canary: one hardware-backed canary in the lab for nightly or pre-release checks.
- This mirrors the Ygg fast-vs-I2P-slow distinction, but here the split is simulation-vs-radio instead of overlay latency.

## Decisions

### Decision: Split-tier Meshtastic canary: simulator first, hardware later

**Status:** decided
**Rationale:** The first Meshtastic canary should be simulator-backed so it is deterministic, cheap, and suitable for routine CI. A separate hardware-backed lab canary should be treated as the authoritative radio-path check for nightly or pre-release validation. This preserves the radio-only Meshtastic architecture without forcing normal CI to depend on USB passthrough, RF conditions, or scarce attached hardware.

### Decision: Minimum useful Meshtastic canary contract is tiered, not all-or-nothing

**Status:** decided
**Rationale:** The canary contract should reflect what each tier can prove. The simulator-backed CI canary should prove: (1) the Meshtastic bridge process starts, (2) a node list or neighbor snapshot is visible through the bridge surface, (3) inbound text can be observed by styrened, and (4) outbound plaintext relay is accepted by the bridge API and reflected by the simulator. The hardware-backed lab canary then strengthens this with real radio-path confirmation. Treating the contract as tiered avoids over-claiming what CI proves while still making the fast canary operationally useful.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- Simulator-backed Meshtastic canary is the default CI target; no attached radio hardware required for routine PR validation.
- Hardware-backed Meshtastic canary is reserved for nightly or pre-release validation and should be treated as authoritative for radio-path confidence.
- Meshtastic canary remains radio-boundary validation, not a general overlay peer canary; do not collapse its semantics into Yggdrasil/I2P reachability checks.
- Canary output must clearly distinguish simulated proof from hardware radio proof so operators do not over-interpret CI health.
- Follow-on design should split into two concrete children: one for the simulator-backed CI contract and one for the hardware-backed lab canary shape.
- Parent node defines portfolio structure and proof semantics; child nodes define concrete simulator and hardware execution models.
