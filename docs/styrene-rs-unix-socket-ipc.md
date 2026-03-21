---
id: styrene-rs-unix-socket-ipc
title: Unix socket IPC server — Daemon trait over framed transport
status: implemented
parent: styrene-rs-architecture
dependencies: [styrene-rs-s5-app-context]
open_questions: []
branches: ["feature/styrene-rs-unix-socket-ipc"]
openspec_change: styrene-rs-unix-socket-ipc
issue_type: feature
priority: 1
---

# Unix socket IPC server — Daemon trait over framed transport

## Overview

The styrene-ipc crate defines the Daemon trait contract. The missing piece is the Unix socket transport layer that exposes it. Daemon listens on ~/.styrene/styrened.sock (desktop) or {appGroupContainer}/styrened.sock (iOS NE). All clients — Ratatui TUI, Dioxus app, Python TUI (via existing IPC bridge) — connect as clients. Framing: CBOR-encoded request/response matching the existing Python IPC protocol. Must be compatible with the Python IPCBridge in styrened so the Python TUI can connect to styrened-rs as a drop-in daemon replacement.

## Decisions

### Decision: Wire-compatible with Python IPC protocol

**Status:** decided
**Rationale:** The Rust server must speak the exact Python IPC wire format: [u32 BE length][u8 type][16-byte request_id][msgpack payload]. This enables the existing Python TUI to connect to styrened-rs as a drop-in replacement. Message type bytes (0x01-0xC6) match IPCMessageType enum values. Payloads are msgpack dicts. The rmp-serde crate handles Rust↔msgpack serialization.

### Decision: Phased handler implementation: core queries first, commands incremental

**Status:** decided
**Rationale:** Start with PING/PONG, QUERY_STATUS, QUERY_IDENTITY, QUERY_DEVICES, SUB_DEVICES, and EVENT_DEVICE — enough for the Python TUI to connect, see daemon status, and discover nodes. Remaining ~60 message types are added incrementally as DaemonFacade methods are implemented. Unknown message types return ERROR response.

### Decision: New crate styrene-ipc-server in crates/libs/

**Status:** decided
**Rationale:** The IPC server is a reusable component — styrened-rs, styrene-hub, and future Rust binaries will all embed it. It depends on styrene-ipc (types+traits) and tokio. It does NOT depend on styrened-rs internals. The server accepts Arc<dyn Daemon> and handles framing, dispatch, and subscriptions. Handler dispatch uses a match on message type byte, calling the appropriate Daemon trait method.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `crates/libs/styrene-ipc-server/Cargo.toml` (new) — New crate: tokio, rmp-serde, styrene-ipc deps
- `crates/libs/styrene-ipc-server/src/lib.rs` (new) — Public API: IpcServer, IpcServerConfig
- `crates/libs/styrene-ipc-server/src/wire.rs` (new) — Wire protocol: frame encode/decode, MessageType enum matching Python IPCMessageType values
- `crates/libs/styrene-ipc-server/src/server.rs` (new) — UnixListener accept loop, per-connection task spawn, graceful shutdown
- `crates/libs/styrene-ipc-server/src/connection.rs` (new) — Per-client connection: frame read loop, dispatch, subscription state
- `crates/libs/styrene-ipc-server/src/dispatch.rs` (new) — Message type → Daemon method mapping, payload deserialization, response construction
- `crates/libs/styrene-ipc-server/src/subscriptions.rs` (new) — Subscription management: per-client event channels, fanout from DaemonEvents
- `crates/libs/styrene-ipc-server/tests/wire_roundtrip.rs` (new) — Wire protocol roundtrip tests: encode→decode, malformed frames, max payload
- `crates/libs/styrene-ipc-server/tests/server_integration.rs` (new) — Integration tests: connect, ping/pong, query_status, subscribe/event push
- `crates/apps/styrened-rs/src/bin/reticulumd/bootstrap.rs` (modified) — Wire IpcServer into daemon startup with DaemonFacade
- `Cargo.toml` (modified) — Add styrene-ipc-server to workspace members

### Constraints

- Wire format must be byte-identical to Python IPC protocol (msgpack payloads, not CBOR)
- MessageType enum values must match Python IPCMessageType exactly
- Server must handle concurrent clients without blocking
- Unknown message types return ERROR response, not crash
- Socket path: ~/.styrene/styrened.sock (respect STYRENED_SOCKET env var)
- Graceful shutdown: drain in-flight requests, close connections, remove socket file
