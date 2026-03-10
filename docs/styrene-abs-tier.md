---
id: styrene-abs-tier
title: ABS Tier — Hardened Styrene Topology
status: seed
parent: styrene-identity
tags: [abs, hardened, post-quantum, trust-enforcement, high-assurance, future]
open_questions: []
---

# ABS Tier — Hardened Styrene Topology

## Overview

ABS (after the polymer — harder, more rigid than standard Styrene) is a future hardened topology variant where post-quantum cryptography is mandatory, trust thresholds are enforced at the network level rather than operator-configurable, and minimum attestation requirements exist before a peer is permitted to participate. Standard Styrene installs default to the hybrid classical+PQ approach with operator-discretion trust. ABS is the upgrade path for high-assurance deployments: military, journalism networks, activist communications, critical infrastructure. The two tiers are designed to be interoperable at the RNS routing layer while enforcing stricter identity and trust rules at the Styrene application layer. ABS nodes can connect to and route through standard Styrene nodes, but will refuse to expose content or capabilities to peers who do not meet ABS identity requirements.

## Decisions

### Decision: ABS scope is deferred — standard Styrene gets hybrid-by-default, ABS enforces PQ-mandatory

**Status:** decided
**Rationale:** Standard Styrene: hybrid Ed25519+ML-DSA-65, PQ components available but not enforced on peers. Operator discretion on trust thresholds. This prevents PQ key sizes from crippling performance on constrained links today. ABS: ML-DSA-65 mandatory for identity, minimum endorsement thresholds enforced network-side, no plaintext content to unatttested peers. The division means we don't impose future-thinking as a current limitation on standard deployments. ABS is an upgrade path, not a retrofit. The two tiers share the StyreneID primitive and the same RNS routing layer — ABS just enforces stricter application-layer policies on top of the same infrastructure.

## Open Questions

*No open questions.*
