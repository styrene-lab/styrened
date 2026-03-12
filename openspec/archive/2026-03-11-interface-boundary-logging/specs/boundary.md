# Interface Boundary Logging Spec

## InterfaceBoundary Enum

**Given** a daemon component catches an exception from a third-party stack (RNS, LXMF, NomadNet, launchd/systemd, async worker)  
**When** it logs the error  
**Then** the log record includes `extra={"boundary": InterfaceBoundary.X, "severity": "transient"|"degraded"|"fatal", "retryable": bool, "stack_name": str, "operation": str}`

**Given** the `InterfaceBoundary` enum is defined  
**When** inspecting its members  
**Then** it contains exactly: RNS, LXMF, NOMADNET, YGGDRASIL, I2P, WIREGUARD, IPC, RPC, SERVICE_MANAGER, ASYNC_WORKER, INTERNAL

## BoundaryLogHandler

**Given** the daemon starts  
**When** `BoundaryLogHandler` is installed  
**Then** it attaches to the `styrened` logger and captures only records that have a `boundary` attribute in their `extra` dict

**Given** the ring buffer is at capacity (200 records)  
**When** a new boundary record arrives  
**Then** the oldest record is dropped and the new record is appended (deque maxlen behavior)

**Given** `logging.boundary_sink: true` is set in core-config.yaml  
**When** a boundary record is emitted  
**Then** it is also written as a JSON line to `~/.local/share/styrene/boundary.log` (size-rotated, max 1 MB, 3 backups)

**Given** `logging.boundary_sink` is absent or false  
**When** a boundary record is emitted  
**Then** no file is written — ring buffer only

## Threading and Unraisable Hook Integration

**Given** a daemon thread raises an unhandled exception  
**When** `threading.excepthook` fires  
**Then** if the exception is boundary-taggable (known stack in thread name or exception type), a boundary record is emitted with appropriate `boundary` and `severity`

**Given** `sys.unraisablehook` fires (e.g. RNS ratchet persist race)  
**When** the exception matches the existing suppression filter (FileNotFoundError + /ratchets/ + .out)  
**Then** the existing DEBUG suppression is preserved and a boundary record is also emitted with `boundary=RNS, severity=transient, retryable=True, operation=ratchet_persist`

## IPC CMD_BOUNDARY_SNAPSHOT

**Given** a connected IPC client sends `CMD_BOUNDARY_SNAPSHOT`  
**When** the daemon handles it  
**Then** it returns a JSON array of up to 200 serialized boundary records (ts, boundary, severity, retryable, stack_name, operation, message)

**Given** the daemon has no boundary records yet  
**When** `CMD_BOUNDARY_SNAPSHOT` is received  
**Then** it returns an empty array `[]`

## Doctor Integration

**Given** `styrened doctor` runs while the daemon is running  
**When** doctor requests `CMD_BOUNDARY_SNAPSHOT`  
**Then** it groups records by boundary tag and surfaces findings: count, most recent timestamp, severity distribution

**Given** a boundary tag has >5 records in the snapshot  
**When** doctor formats findings  
**Then** it emits a WARN finding with the boundary name, count, last-seen timestamp, and a fix_hint

**Given** a boundary tag has only transient records and count ≤ 5  
**When** doctor formats findings  
**Then** it emits an INFO finding (not WARN)

**Given** the daemon is not running  
**When** `styrened doctor` runs  
**Then** boundary snapshot is skipped gracefully — existing point-in-time checks run as before
