# Unix socket IPC server — Daemon trait over framed transport — Design Spec (extracted)

> Auto-extracted from docs/styrene-rs-unix-socket-ipc.md at decide-time.

## Decisions

### Wire-compatible with Python IPC protocol (decided)

The Rust server must speak the exact Python IPC wire format: [u32 BE length][u8 type][16-byte request_id][msgpack payload]. This enables the existing Python TUI to connect to styrened-rs as a drop-in replacement. Message type bytes (0x01-0xC6) match IPCMessageType enum values. Payloads are msgpack dicts. The rmp-serde crate handles Rust↔msgpack serialization.

### Phased handler implementation: core queries first, commands incremental (decided)

Start with PING/PONG, QUERY_STATUS, QUERY_IDENTITY, QUERY_DEVICES, SUB_DEVICES, and EVENT_DEVICE — enough for the Python TUI to connect, see daemon status, and discover nodes. Remaining ~60 message types are added incrementally as DaemonFacade methods are implemented. Unknown message types return ERROR response.

### New crate styrene-ipc-server in crates/libs/ (decided)

The IPC server is a reusable component — styrened-rs, styrene-hub, and future Rust binaries will all embed it. It depends on styrene-ipc (types+traits) and tokio. It does NOT depend on styrened-rs internals. The server accepts Arc<dyn Daemon> and handles framing, dispatch, and subscriptions. Handler dispatch uses a match on message type byte, calling the appropriate Daemon trait method.
