# Unix socket IPC server — Daemon trait over framed transport

## Intent

The styrene-ipc crate defines the Daemon trait contract. The missing piece is the Unix socket transport layer that exposes it. Daemon listens on ~/.styrene/styrened.sock (desktop) or {appGroupContainer}/styrened.sock (iOS NE). All clients — Ratatui TUI, Dioxus app, Python TUI (via existing IPC bridge) — connect as clients. Framing: CBOR-encoded request/response matching the existing Python IPC protocol. Must be compatible with the Python IPCBridge in styrened so the Python TUI can connect to styrened-rs as a drop-in daemon replacement.

See [design doc](../../../docs/styrene-rs-unix-socket-ipc.md).
