# interface-boundary-logging — Tasks

<!-- specs: boundary -->

## Group 1 — Core types and handler

- [x] 1.1 Create `src/styrened/boundary.py` — `InterfaceBoundary(str, Enum)` with 11 members and `BoundaryRecord` dataclass
- [x] 1.2 `BoundaryLogHandler(logging.Handler)` — `deque(maxlen=200)`, `emit()`, `snapshot()`, `clear()`
- [x] 1.3 Optional NDJSON `RotatingFileHandler` sink; `boundary_sink: bool = False` added to config model
- [x] 1.4 Unit tests in `tests/unit/test_boundary.py`

## Group 2 — Daemon integration

- [x] 2.1 Install `BoundaryLogHandler` in `daemon.py` `main()`, stored as `self._boundary_handler`
- [x] 2.2 Extend `_install_thread_excepthook()` to emit boundary records for taggable exceptions
- [x] 2.3 Extend ratchet-persist `sys.unraisablehook` suppression to also emit a boundary record
- [x] 2.4 Unit tests in `tests/unit/test_daemon_lifecycle.py`

## Group 3 — IPC command

- [x] 3.1 `CMD_BOUNDARY_SNAPSHOT = 0x70` in `ipc/protocol.py`; request/response message classes in `ipc/messages.py`
- [x] 3.2 `handle_cmd_boundary_snapshot()` in `ipc/handlers.py`, wired into dispatch table
- [x] 3.3 `IPCBridge.boundary_snapshot()` method
- [x] 3.4 Unit tests for empty and populated buffer responses

## Group 4 — Doctor integration

- [x] 4.1 `check_boundary_log()` in `services/doctor.py` — IPC snapshot, WARN/>5 records, INFO/≤5 transient
- [x] 4.2 Wired into doctor run sequence after RNS/LXMF checks
- [x] 4.3 Unit tests in `tests/unit/test_doctor_boundary.py`
