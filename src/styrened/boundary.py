"""Interface boundary logging for styrened daemon.

Provides structured capture of errors that cross third-party stack boundaries
(RNS, LXMF, NomadNet, IPC, async workers, etc.) so they can be inspected via
the IPC snapshot command and surfaced by `styrened doctor`.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class InterfaceBoundary(str, Enum):
    """Logical boundary tags identifying which third-party stack an error crossed."""

    RNS = "rns"
    LXMF = "lxmf"
    NOMADNET = "nomadnet"
    YGGDRASIL = "yggdrasil"
    I2P = "i2p"
    WIREGUARD = "wireguard"
    IPC = "ipc"
    RPC = "rpc"
    SERVICE_MANAGER = "service_manager"
    ASYNC_WORKER = "async_worker"
    INTERNAL = "internal"


@dataclass
class BoundaryRecord:
    """A single captured boundary-crossing log event."""

    ts: float
    boundary: str  # InterfaceBoundary.value
    severity: str  # "transient" | "degraded" | "fatal"
    retryable: bool
    stack_name: str
    operation: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Ring-buffer capacity
_DEQUE_MAXLEN = 200


class BoundaryLogHandler(logging.Handler):
    """Logging handler that captures boundary-tagged records into a ring buffer.

    Only records that include a ``boundary`` key in their ``extra`` dict (i.e.
    ``record.__dict__`` contains ``boundary``) are captured.  All other records
    are ignored so normal logging throughput is unaffected.

    An optional NDJSON rotating-file sink can be activated at construction time
    by passing ``sink_path``.  The sink is *off* by default; it is only created
    when the ``boundary_sink`` config flag is enabled.
    """

    def __init__(self, sink_path: Path | None = None) -> None:
        super().__init__()
        self._records: deque[BoundaryRecord] = deque(maxlen=_DEQUE_MAXLEN)
        self._file_handler: logging.handlers.RotatingFileHandler | None = None

        if sink_path is not None:
            sink_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handler = logging.handlers.RotatingFileHandler(
                str(sink_path),
                maxBytes=1 * 1024 * 1024,  # 1 MB
                backupCount=3,
                encoding="utf-8",
            )
            self._file_handler.setFormatter(logging.Formatter("%(message)s"))

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Capture boundary-tagged records; silently ignore everything else."""
        boundary_value = getattr(record, "boundary", None)
        if boundary_value is None:
            return

        # Normalise to string value in case caller passed the enum member
        if isinstance(boundary_value, InterfaceBoundary):
            boundary_str = boundary_value.value
        else:
            boundary_str = str(boundary_value)

        br = BoundaryRecord(
            ts=record.created,
            boundary=boundary_str,
            severity=str(getattr(record, "severity", "transient")),
            retryable=bool(getattr(record, "retryable", False)),
            stack_name=str(getattr(record, "stack_name", record.name)),
            operation=str(getattr(record, "operation", "")),
            message=self.format(record) if self.formatter else record.getMessage(),
        )
        self._records.append(br)

        if self._file_handler is not None:
            # Write NDJSON line
            ndjson_record = logging.makeLogRecord(
                {"msg": json.dumps(br.to_dict()), "levelno": record.levelno}
            )
            self._file_handler.emit(ndjson_record)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of the ring buffer as a list of dicts (newest last)."""
        return [r.to_dict() for r in self._records]

    def clear(self) -> None:
        """Empty the ring buffer.  Intended for use in tests."""
        self._records.clear()

    def close(self) -> None:
        super().close()
        if self._file_handler is not None:
            self._file_handler.close()


def make_boundary_handler(boundary_sink: bool = False) -> BoundaryLogHandler:
    """Factory: construct a ``BoundaryLogHandler`` with optional file sink.

    Args:
        boundary_sink: When *True*, also write NDJSON to
            ``~/.local/share/styrene/boundary.log`` (size-rotated).

    Returns:
        A configured ``BoundaryLogHandler`` ready to be installed on the
        ``styrened`` logger.
    """
    sink_path: Path | None = None
    if boundary_sink:
        sink_path = Path.home() / ".local" / "share" / "styrene" / "boundary.log"
    return BoundaryLogHandler(sink_path=sink_path)
