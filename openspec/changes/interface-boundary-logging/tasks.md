# interface-boundary-logging — Tasks

<!-- specs: boundary -->

## Group 1 — Core types and handler

- [ ] 1.1 Create `src/styrened/boundary.py` — `InterfaceBoundary(str, Enum)` with 11 members (RNS, LXMF, NOMADNET, YGGDRASIL, I2P, WIREGUARD, IPC, RPC, SERVICE_MANAGER, ASYNC_WORKER, INTERNAL) and `BoundaryRecord` dataclass (ts, boundary, severity, retryable, stack_name, operation, message)
- [ ] 1.2 Create `BoundaryLogHandler(logging.Handler)` in `src/styrened/boundary.py` — `deque(maxlen=200)`, `emit()` captures only records with `boundary` in `__dict__`, `snapshot()` returns list of serialized dicts, `clear()` for tests
- [ ] 1.3 Add optional NDJSON file sink: `RotatingFileHandler` at `~/.local/share/styrene/boundary.log` (1 MB, 3 backups), activated when `config.logging.boundary_sink is True`; add `boundary_sink: bool = False` field to `LoggingConfig` (or equivalent config model)
- [ ] 1.4 Unit tests in `tests/unit/test_boundary.py` — enum completeness (exactly 11 members), handler captures tagged records, handler ignores untagged records, deque drops oldest at capacity, snapshot serialization round-trip, NDJSON sink off-by-default

## Group 2 — Daemon integration

- [ ] 2.1 Install `BoundaryLogHandler` in `daemon.py` `main()` alongside the existing `_install_thread_excepthook()` call; attach to `logging.getLogger("styrened")`; store reference on daemon instance as `self._boundary_handler`
- [ ] 2.2 Extend `_install_thread_excepthook()` in `daemon.py`: when a thread exception is boundary-taggable (classify by exception type + thread name heuristics), emit a boundary log record via `logger.error(..., extra={boundary, severity, retryable, stack_name, operation})` in addition to existing behaviour
- [ ] 2.3 Extend the existing ratchet-persist `sys.unraisablehook` suppression: after routing to DEBUG, also emit a boundary record with `boundary=RNS, severity=transient, retryable=True, operation="ratchet_persist"` — do not change existing suppression logic
- [ ] 2.4 Unit tests in `tests/unit/test_daemon_lifecycle.py` (extend existing `TestRatchetPersistHook`): verify ratchet-persist hook emits boundary record; verify non-matching unraisable does not emit boundary record

## Group 3 — IPC command

- [ ] 3.1 Add `CMD_BOUNDARY_SNAPSHOT = 0x70` to `ipc/protocol.py` `IPCMessageType`; add `CmdBoundarySnapshotRequest` / `CmdBoundarySnapshotResponse` message classes to `ipc/messages.py`
- [ ] 3.2 Add `handle_cmd_boundary_snapshot()` handler in `ipc/handlers.py` — reads `daemon._boundary_handler.snapshot()`, returns serialized array; returns `[]` if handler not initialised
- [ ] 3.3 Add `IPCBridge.boundary_snapshot()` method in `tui/services/ipc_bridge.py` (or `ipc/bridge.py`) — sends request, returns `list[dict]`
- [ ] 3.4 Unit tests: `CMD_BOUNDARY_SNAPSHOT` with empty buffer returns `[]`; with 3 records returns 3 dicts with expected keys

## Group 4 — Doctor integration

- [ ] 4.1 Add `check_boundary_log()` function in `services/doctor.py` — connects to daemon via IPC, calls `CMD_BOUNDARY_SNAPSHOT`, groups by `boundary`, emits WARN finding if any tag has >5 records, INFO finding for ≤5 transient-only records; skips gracefully if daemon not running
- [ ] 4.2 Wire `check_boundary_log()` into the doctor run sequence (after existing RNS/LXMF checks)
- [ ] 4.3 Unit tests: >5 records for a tag → WARN finding; ≤5 transient records → INFO; daemon not running → no error, check skipped
