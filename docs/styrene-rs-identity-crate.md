---
id: styrene-rs-identity-crate
title: styrene-identity crate — IdentitySigner trait + HKDF key hierarchy
status: decided
parent: styrene-rs-architecture
dependencies: [styrene-identity]
open_questions: []
---

# styrene-identity crate — IdentitySigner trait + HKDF key hierarchy

## Overview

New library crate implementing the IdentitySigner trait (four-tier model decided in styrene-identity design node) and the HKDF root-secret derivation hierarchy. Must compile as a no-UI library usable from daemon, iOS PacketTunnelProvider extension, and Dioxus app. Backends: FileSigner (default, argon2id+ChaCha20), keyring crate (Tier B/C platform/FOSS), YubiKeySigner (pcsc-rs, PIV slot). Root secret → HKDF → RNS enc+sign seeds, Yggdrasil Ed25519, WireGuard Curve25519, ML-DSA-65 key (encrypted). Hybrid Ed25519+ML-DSA-65 root; Ed25519 travels on-wire.

## Open Questions

*No open questions.*
