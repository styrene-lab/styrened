# Styrene Identity System — Tasks

## 1. ABS Tier — Hardened Styrene Topology

- [x] 1.1 Implement: ABS scope is deferred — standard Styrene gets hybrid-by-default, ABS enforces PQ-mandatory

## 2. Styrene Trust Model — Web of Trust, Attestations, and Sybil Resistance

- [x] 2.1 Implement: WLC propagation with γ=0.5 depth attenuation and combined atomic operators
- [x] 2.2 Implement: Continuous Appleseed score (not binary tiers), discretized at RBAC boundary only
- [x] 2.3 Implement: Endorsements are encrypted-in-transit, operator-controlled publication, DP aggregate
- [x] 2.4 Implement: EigenTrust Layer 3 pre-trusted vector seeded from OPERATOR+ RBAC roster
- [x] 2.5 Implement: CTAP2 canonical CBOR for all signed manifest and endorsement structures
- [x] 2.6 Implement: f32 for all daemon and Pi-class targets; u16 fixed-point for bare-metal MCU only
- [x] 2.7 Implement: TrustEngineConfig — configurable weights with named profiles; SybilRank labeled candidate not scheduled
- [x] 2.8 Implement: Content signature UX: three states — verified-by-trusted (green badge), signed-unknown (grey warning), unsigned (silent absence unless ABS mode or regression)
- [x] 2.9 Implement: Hub trust display: three signals — software attestation, local uptime observation, operator WoT endorsement count
- [x] 2.10 Implement: PGP integration Phase 1: WKD + hkps://keys.openpgp.org only; Keybase-style cross-proofs deferred to Phase 2
- [x] 2.11 Implement: ABS tier enforcement is operator-configurable local policy (content_policy: hardened) — not network-level consensus enforcement
