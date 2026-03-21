# styrene-rs-unix-socket-ipc — Design

## Spec-Derived Architecture

### server

- **IPC server accepts connections on Unix socket** (added) — 4 scenarios
- **Server graceful shutdown** (added) — 1 scenarios
- **Subscription event push** (added) — 2 scenarios

### wire-protocol

- **Frame encode produces Python-compatible bytes** (added) — 2 scenarios
- **Frame decode handles valid and malformed input** (added) — 4 scenarios
- **MessageType enum values match Python IPCMessageType** (added) — 1 scenarios

## File Changes

<!-- Add file changes as you design the implementation -->
