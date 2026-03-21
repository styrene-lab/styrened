---
id: python-daemon-sunset
title: Python Daemon Sunset — TUI-only styrened + Rust daemon backend
status: implementing
tags: [strategic, architecture, migration, packaging]
open_questions: []
issue_type: epic
priority: 1
---

# Python Daemon Sunset — TUI-only styrened + Rust daemon backend

## Overview

Transition styrened from daemon+TUI monolith to TUI-only package that connects to styrened-rs over IPC. The Python daemon, services, RPC, and protocol layers become dead code once the Rust daemon handles all active IPC message types. The TUI, IPC bridge, models, and CLI stay Python.

## Research

### Current state: what's replaced and what stays

**Replaced by Rust (remove from styrened):**
- `daemon.py` — StyreneDaemon class, orchestration → AppContext + bootstrap.rs
- `services/` — all 8 services → 12 Rust services in styrened-rs
- `rpc/` — RPC server + client → FleetService + RpcResponseHandler
- `protocols/` — registry + handlers → ProtocolService + ProtocolHandler trait
- `services/lifecycle.py` — init/shutdown → bootstrap.rs phased constructor
- `services/reticulum.py` — mesh init → TokioTransportAdapter
- `services/lxmf_service.py` — LXMF router → inbound worker + MessagingService
- `services/node_store.py` — device storage → DiscoveryService + MessagesStore announces table

**Stays Python (TUI + IPC bridge):**
- `tui/` — all screens, widgets, services, themes, forge (83 behaviors)
- `ipc/protocol.py` — wire format encode/decode (shared with Rust via golden vectors)
- `ipc/server.py` — Python IPC server (only needed if Python daemon runs)
- `ipc/bridge.py` — TUI IPC bridge (connects to daemon socket, stays)
- `models/` — data models used by TUI (MeshDevice, CoreConfig, etc.)
- `cli.py` — CLI subcommands (devices, status, send, exec) — thin IPC clients

**Gray area:**
- `ipc/handlers.py` — Python daemon request handlers. Remove with daemon.
- `ipc/server.py` — Python IPC server. Remove with daemon.
- `models/config.py` — CoreConfig. TUI needs this for settings screen. Keep.
- `models/styrene_wire.py` — StyreneEnvelope. Used by RPC client. Remove with RPC.
- `services/auto_reply.py` — Used by daemon. Remove.
- `services/config.py` — YAML config loading. TUI needs this for settings. Keep.
- `services/doctor.py` — Installation diagnostics. Rewrite to check for Rust binary instead of Python deps. Keep but modify.

### Transition plan: 3 phases

**Phase 1: Dual-daemon development freeze (NOW)**
Stop adding features to the Python daemon. All new daemon work goes to Rust. The Python daemon exists only for the TUI to connect to during development. The Rust daemon is the target.

What changes immediately:
- `styrened daemon` keeps working (Python) — no regression
- `styrened` TUI keeps working — connects to whichever daemon is on the socket
- New IPC message types added only in Rust
- Python test suite for daemon internals frozen — no new tests for Python services
- Wire compat tests (87) are the contract boundary

**Phase 2: TUI → Rust daemon validation (NEXT)**
Systematically validate every TUI screen against the Rust daemon:
- Start styrened-rs, then run `styrened` (TUI only, connects to Rust socket)
- Walk through: dashboard, exploration, chat, inbox, contacts, settings, forge
- File bugs for any IPC response mismatches
- This is the pre-release QA gate (design node exists)

What changes:
- TUI startup auto-detects which daemon is running (check socket, identify via ping response)
- TUI shows daemon type in status bar (Python/Rust)
- Any missing IPC responses get implemented in Rust

**Phase 3: Python daemon removal (THEN)**
Once Phase 2 validates all TUI flows against Rust:
- Remove `daemon.py`, `services/`, `rpc/`, `protocols/`, `ipc/server.py`, `ipc/handlers.py`
- `styrened daemon` command spawns the Rust binary instead of Python daemon
- `styrened` (TUI) connects to the Rust daemon socket
- Package slims dramatically — TUI + models + IPC bridge + CLI
- Python test suite shrinks to TUI tests + wire compat + CLI tests
- Doctor checks for Rust binary presence

## Decisions

### Decision: Freeze Python daemon development immediately — all new daemon work in Rust only

**Status:** decided
**Rationale:** 25/39 Daemon methods working in Rust. 87 cross-language wire tests prove interoperability. The remaining 14 methods are P3 features (terminal, tunnel) or need minor wire additions (remote_inbox). Maintaining two daemon implementations doubles effort with zero user value. The Python daemon has served its purpose as the reference implementation — the Rust daemon is the production target.

### Decision: styrened package becomes TUI + CLI + IPC bridge — no daemon code

**Status:** decided
**Rationale:** The IPC boundary is the natural architectural cut. The TUI (Textual, 83 behaviors) stays Python — rewriting it in Rust gains nothing and loses the Textual ecosystem. The daemon (services, transport, storage, protocol dispatch) is already ported. The CLI (devices, status, send, exec) is thin IPC client code that works against either daemon. After transition, styrened is ~40% smaller by LOC and ships as pip install styrened[tui] with a dependency on the styrened-rs binary.

### Decision: Rust binary distributed as GitHub release + cargo install; styrened spawns it as subprocess

**Status:** decided
**Rationale:** PyO3/maturin bundling is blocked by Python 3.14 compatibility. GitHub release binaries (cross-compiled via Nix/Argo) cover the primary targets (linux-amd64, linux-arm64, darwin-amd64, darwin-arm64). `cargo install styrened-rs` for developers. `styrened daemon` spawns the Rust binary as a subprocess (exec, not fork) — searches PATH for `reticulumd`, falls back to `~/.cargo/bin/reticulumd`, then fails with a doctor-style diagnostic. The TUI doesn't care which daemon runs — it connects to the socket. This avoids the complexity of embedding a Rust binary in a Python wheel.

## Open Questions

*No open questions.*
