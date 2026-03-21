# Python Daemon Sunset — TUI-only styrened + Rust daemon backend — Design Spec (extracted)

> Auto-extracted from docs/python-daemon-sunset.md at decide-time.

## Decisions

### Freeze Python daemon development immediately — all new daemon work in Rust only (decided)

25/39 Daemon methods working in Rust. 87 cross-language wire tests prove interoperability. The remaining 14 methods are P3 features (terminal, tunnel) or need minor wire additions (remote_inbox). Maintaining two daemon implementations doubles effort with zero user value. The Python daemon has served its purpose as the reference implementation — the Rust daemon is the production target.

### styrened package becomes TUI + CLI + IPC bridge — no daemon code (decided)

The IPC boundary is the natural architectural cut. The TUI (Textual, 83 behaviors) stays Python — rewriting it in Rust gains nothing and loses the Textual ecosystem. The daemon (services, transport, storage, protocol dispatch) is already ported. The CLI (devices, status, send, exec) is thin IPC client code that works against either daemon. After transition, styrened is ~40% smaller by LOC and ships as pip install styrened[tui] with a dependency on the styrened-rs binary.

### Rust binary distributed as GitHub release + cargo install; styrened spawns it as subprocess (decided)

PyO3/maturin bundling is blocked by Python 3.14 compatibility. GitHub release binaries (cross-compiled via Nix/Argo) cover the primary targets (linux-amd64, linux-arm64, darwin-amd64, darwin-arm64). `cargo install styrened-rs` for developers. `styrened daemon` spawns the Rust binary as a subprocess (exec, not fork) — searches PATH for `reticulumd`, falls back to `~/.cargo/bin/reticulumd`, then fails with a doctor-style diagnostic. The TUI doesn't care which daemon runs — it connects to the socket. This avoids the complexity of embedding a Rust binary in a Python wheel.

## Research Summary

### Current state: what's replaced and what stays

**Replaced by Rust (remove from styrened):**
- `daemon.py` — StyreneDaemon class, orchestration → AppContext + bootstrap.rs
- `services/` — all 8 services → 12 Rust services in styrened-rs
- `rpc/` — RPC server + client → FleetService + RpcResponseHandler
- `protocols/` — registry + handlers → ProtocolService + ProtocolHandler trait
- `services/lifecycle.py` — init/shutdown → bootstrap.rs phased constructor
- `services/reticulum.py` — mesh init → TokioTransportAdapter
- `services/lxmf_service.py…

### Transition plan: 3 phases

**Phase 1: Dual-daemon development freeze (NOW)**
Stop adding features to the Python daemon. All new daemon work goes to Rust. The Python daemon exists only for the TUI to connect to during development. The Rust daemon is the target.

What changes immediately:
- `styrened daemon` keeps working (Python) — no regression
- `styrened` TUI keeps working — connects to whichever daemon is on the socket
- New IPC message types added only in Rust
- Python test suite for daemon internals frozen — no new t…
