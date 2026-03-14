---
id: meshtastic-hardware-canary-lab-shape
title: Meshtastic Hardware Canary Lab Shape
status: exploring
parent: meshtastic-canary-shape
tags: [meshtastic, canary, hardware, lab, nightly, pre-release]
open_questions: []
---

# Meshtastic Hardware Canary Lab Shape

## Overview

Define the authoritative hardware-backed Meshtastic canary used for nightly or pre-release validation: hosting model, radio attachment strategy, expected confidence signals, and operational boundaries for a lab-only canary.

## Research

### Hardware lab canary should optimize for trustworthiness over convenience

The hardware-backed canary exists to answer the question the simulator cannot: does the real styrened Meshtastic bridge still work against an actual attached radio and a real RF or serial-attached Meshtastic environment? Because its purpose is authoritative confidence rather than speed, it can accept operational inconveniences such as fixed lab placement, explicit maintenance windows, and slower cadence. The important design constraint is that it must remain stable enough to distinguish bridge regressions from routine lab churn.

### Preferred hosting model: small stable lab node beats shared cluster USB passthrough

The hardware-backed canary should run on a dedicated small lab host or single-purpose edge node with a directly attached Meshtastic radio, not on a general shared Kubernetes worker via opportunistic USB passthrough. A fixed host gives more stable serial device naming, fewer scheduler-induced variables, simpler reboot recovery, and clearer operator ownership. The test value comes from environmental stability and repeatability, not orchestration sophistication.

### Two-node minimum topology for authoritative validation

A single attached Meshtastic radio only proves that styrened can open the local interface. The authoritative hardware canary should therefore validate against at least one second Meshtastic node so that neighbor discovery and message movement are real rather than synthetic. The simplest topology is one host-attached gateway radio plus one stable peer radio in the same lab environment, with RF conditions kept intentionally boring rather than optimized for range experimentation.

## Decisions

### Decision: Hardware canary runs on a dedicated lab host with a directly attached radio

**Status:** decided
**Rationale:** A dedicated lab host minimizes moving parts and makes failures easier to interpret. Shared cluster USB passthrough or highly dynamic scheduling would add noise unrelated to the Meshtastic bridge itself. Because this canary is intended to be authoritative rather than cheap, operational simplicity and stable attachment are more important than maximizing infrastructure reuse.

### Decision: Authoritative hardware validation requires a real peer radio, not just loopback attachment

**Status:** decided
**Rationale:** The hardware canary must prove more than local device enumeration. A second Meshtastic node is required so the system can confirm neighbor visibility and real message movement across the radio boundary. This keeps the hardware lane meaningfully stronger than the simulator lane.

### Decision: Hardware canary cadence is nightly and pre-release, not per-PR

**Status:** decided
**Rationale:** Real hardware introduces attachment, power, and environmental variability that are acceptable for periodic confidence checks but too expensive and noisy for routine PR gating. Running this canary nightly and before releases provides strong signal without making routine development hostage to lab conditions.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- Use a dedicated lab host or edge node with a directly attached Meshtastic radio; avoid depending on shared-cluster USB passthrough for the authoritative lane.
- Hardware canary must include at least one stable peer radio so it proves neighbor discovery and real message movement, not only local attachment.
- Keep the RF environment intentionally stable and boring; this is a bridge confidence check, not a range or resilience experiment.
- Treat this lane as nightly/pre-release validation rather than routine PR gating.
