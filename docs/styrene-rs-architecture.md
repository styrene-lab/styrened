---
id: styrene-rs-architecture
title: styrene-rs Daemon Architecture
status: resolved
tags: [rust, daemon, architecture, styrene-rs, tokio]
open_questions: []
---

# styrene-rs Daemon Architecture

## Overview

Root design node for the styrene-rs daemon architecture. Covers structural decisions (S1-S6 from PARITY_GAPS.md), new constraints from mobile/identity design, and the relationship between the existing crates. The goal is a clean, testable, edge-capable daemon with a well-defined IPC contract — not a 1:1 port of Python styrened.

## Research

### Current crate inventory (March 2026)

9 crates in libs/, 2 in apps/ (bindings/ empty):

**libs/**
- `styrene-rns` — RNS protocol core: identity, destinations, links, resources, ratchets, packets, TCP/UDP transport. ~13K LOC transport layer. 212 passing interop tests.
- `styrene-lxmf` — LXMF router, propagation, stamps, delivery pipeline. SDK domain types behind feature flag.
- `styrene-mesh` — Wire protocol envelope (must match styrene_wire.py byte-for-byte). Planned CBOR migration from MessagePack.
- `styrene-micron` — NomadNet micron format parser. 609 LOC parser, 853 LOC conformance tests.
- `styrene-tunnel` — PQC tunnel session layer. 967 LOC session module. ML-KEM + X25519 hybrid key exchange.
- `styrene-ipc` — IPC contract traits. Defines `Daemon` composite trait decomposed into `DaemonMessaging`, `DaemonIdentity`, `DaemonStatus`, `DaemonFleet`, `DaemonEvents`, `DaemonTunnel`. Plus `StubDaemon` (all methods return NotImplemented) and boundary types matching Python TUI consumption.
- `styrene-dx` — Developer experience utilities.
- `styrene-tui` — Ratatui TUI scaffolding (stub/empty).
- (future) `styrene-identity` — IdentitySigner trait + backends. Not yet created.

**apps/**
- `styrened-rs` — Daemon binary. `RpcDaemon` god-struct (40+ Mutex fields). `Rc<RpcDaemon>` + single-thread tokio. RPC server (TCP/TLS + HTTP). `include!()` macro stitching.

**Key finding**: `styrene-ipc` already defines the clean `Daemon` trait decomposition that PARITY_GAPS S5 called for. However, `RpcDaemon` does NOT yet implement this trait — it uses separate `OutboundBridge` and `AnnounceBridge` traits. The abstraction layers are not yet connected.

### New constraints from mobile and identity design (March 2026)

Design work completed this session imposes additional architectural requirements not present in PARITY_GAPS.md:

**1. IdentitySigner trait** (from styrene-identity design)
A new `styrene-identity` crate is needed. Must compile as a no-UI library usable from:
- styrened-rs daemon binary
- iOS PacketTunnelProvider extension process (separate binary target in app bundle)
- Dioxus mobile app main process
Backends: YubiKey (PIV via pcsc-rs), iOS Keychain (via Swift FFI or objc crate), Android Keystore, `keyring` crate (cross-platform SecretService/Keychain), encrypted file (default).
HKDF derivation of all protocol keys (RNS, Yggdrasil, WireGuard) from single root secret.

**2. PropagationClient NodeRole** (from mobile Tier 1 architecture)
The daemon needs a first-class thin-client mode where the device registers as an LXMF propagation client but does NOT route traffic or maintain announce tables for others. Not currently modeled anywhere. Needed before mobile Tier 1 can be built.

**3. Unix socket IPC server** (from mobile iOS NE + Dioxus architecture)
The daemon must expose a Unix socket IPC server implementing the `Daemon` trait from `styrene-ipc`. This socket lives in:
- `~/.styrene/styrened.sock` on desktop/server
- `{appGroupContainer}/styrened.sock` on iOS (app group shared container — same socket, different path)
The Dioxus app and Ratatui TUI both connect as clients to this socket. The `styrene-ipc` crate already defines the contract; the transport layer (Unix socket server with framed messages) needs to be built.

**4. CBOR migration** (from styrene-rs CLAUDE.md, deferred since Feb 2026)
`styrene-mesh` uses MessagePack (`rmp_serde`). Migration to CBOR (`ciborium`) required for:
- Deterministic encoding (required for content-hash event IDs)
- COSE (RFC 9052) authenticated signing for the identity manifest
- IETF governance / formal spec
Wire protocol change must be synchronized with Python `styrened` (`msgpack` → `cbor2`).

**5. Hub push gateway service** (from mobile Tier 1)
Not in styrene-rs — lives in `public-hub`. But daemon must support:
- PropagationClient registration API (device token + platform registration)
- Message-arrived notification hook (triggers push gateway when delivering to mobile client)
This requires the propagation store (PARITY_GAPS 1.3) to be built first.

### Actual crate state after S1 commit (March 2026) — more complete than PARITY_GAPS

Committed WIP revealed the following are further along than PARITY_GAPS documented:

**styrene-tunnel** (967 LOC session + orchestrator + crypto): Full PQC tunnel session layer — ML-KEM + X25519 hybrid KEM, AEAD, KDF, session state machine, WireGuard backend, StrongSwan VICI backend. This is the crypto layer needed for Tier 3 mobile tunnels.

**styrene-micron** (609 LOC parser + 853 LOC conformance tests): NomadNet micron format parser with full conformance test suite against the nomad_net_guide fixture.

**styrene-native** (PyO3 bindings scaffold): The incremental migration bindings crate is scaffolded. `styrene_native` module exposes `PyStyreneMessage` and `PyStyreneMessageType` from `styrene-mesh`. Wire protocol first module exposed to Python — Phase 1 of PyO3 migration started.

**styrene-ipc** (`DaemonTunnel` trait): Added tunnel management operations to the IPC contract — `list_tunnels`, `tunnel_status`, `tunnel_rekey`, `tunnel_teardown`, `list_tunnel_sas`. Reflects the PQC tunnel session layer in the public API.

**styrene-mesh** (PQC wire types): `StyreneMessageType` extended with PQC session message types (0xD0-0xD7) behind `#[cfg(feature = "pqc")]`. `styrene-mesh/src/pqc.rs` (307 LOC) — PQC payload encoding for initiate/respond/confirm/rekey/data/close/capability messages.

**Interop test vectors**: JSON fixtures for announce, fernet, HDLC, identity, packet — plus Python generation script. The cross-language test infrastructure is in place.

**New crate count**: 11 crates in workspace (libs: styrene-rns, styrene-lxmf, styrene-mesh, styrene-micron, styrene-tunnel, styrene-ipc; apps: styrened-rs, styrene-tui, styrene-dx; bindings: styrene-native; plus future styrene-identity).

## Decisions

### Decision: Build order: S1 → S4+S3+CBOR+IFAC (parallel) → S2 → S5 → IPC server + identity crate + propagation client

**Status:** decided
**Rationale:** S1 (Rc→Arc) is the prerequisite gate — nothing concurrent works until it's done. S4 (module structure) and S3 (ByteStream trait) and CBOR migration and IFAC fix are independent of each other and can proceed in parallel after S1. S2 (MeshTransport trait) depends on S3 being clean but not S4. S5 (AppContext) requires S1+S2+S4. Unix socket IPC server and PropagationClient require S5. Identity crate is independent of S1-S5 (no daemon coupling) and can proceed in parallel from day one. Serial/KISS interface depends only on S3. This gives a clear critical path: S1 is the only true serial gate.

### Decision: styrene-ipc Daemon trait is the IPC contract — RpcDaemon must implement it

**Status:** decided
**Rationale:** styrene-ipc already defines the right abstraction (Daemon composite trait with six sub-traits). RpcDaemon does not yet implement it. The target state: RpcDaemon implements Daemon (and therefore all six sub-traits), the Unix socket IPC server takes Arc&lt;dyn Daemon&gt;, and StubDaemon enables incremental development where unimplemented methods return NotImplemented rather than panicking. This makes the IPC contract the authoritative specification — if a method exists in the Daemon trait, the daemon must implement it.

### Decision: PyO3 FFI hybrid migration path remains valid alongside styrened-rs binary

**Status:** decided
**Rationale:** The incremental-rust-migration.md strategy (PyO3 hybrid via styrene-native crate) is compatible with the full Rust daemon path. They are not mutually exclusive: the PyO3 bindings crate can expose the same service implementations to Python that the AppContext uses in the pure Rust daemon. Dual-path testing (Python vs Rust implementation of each module) provides confidence before cutting over. The PyO3 path enables Python users to benefit from Rust performance before the full daemon port is ready.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- styrene-identity crate must compile with no_std where possible — needed for RP2040/ESP32 constrained devices (FileSigner backend excluded on no_std)
- styrened-rs RNS transport must remain a no-UI library — PacketTunnelProvider extension imports it as a library, not as a binary
- Unix socket IPC must be wire-compatible with Python IPCBridge in styrened so Python TUI can connect to styrened-rs daemon
- CBOR migration is a breaking wire change — requires coordinated version bump in both styrene-rs and styrened Python
- S1 (Rc→Arc) must land before any other structural change — it is the only true serial gate in the build order
