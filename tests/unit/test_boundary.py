"""Unit tests for src/styrened/boundary.py."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import pytest

from styrened.boundary import (
    BoundaryLogHandler,
    BoundaryRecord,
    InterfaceBoundary,
    _DEQUE_MAXLEN,
    make_boundary_handler,
)


# ---------------------------------------------------------------------------
# InterfaceBoundary enum
# ---------------------------------------------------------------------------


def test_enum_has_exactly_11_members():
    members = list(InterfaceBoundary)
    assert len(members) == 11


def test_enum_member_names():
    expected = {
        "RNS", "LXMF", "NOMADNET", "YGGDRASIL", "I2P",
        "WIREGUARD", "IPC", "RPC", "SERVICE_MANAGER", "ASYNC_WORKER", "INTERNAL",
    }
    assert {m.name for m in InterfaceBoundary} == expected


def test_enum_is_str_subclass():
    assert isinstance(InterfaceBoundary.RNS, str)


# ---------------------------------------------------------------------------
# BoundaryLogHandler — capture behaviour
# ---------------------------------------------------------------------------


def _make_logger(name: str = "test.boundary") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # Remove any pre-existing handlers to keep tests isolated, closing each
    # one first to release any underlying file handles.
    for h in list(logger.handlers):
        h.close()
    logger.handlers.clear()
    return logger


def _emit_boundary(logger: logging.Logger, boundary: InterfaceBoundary, msg: str = "boom") -> None:
    logger.error(
        msg,
        extra={
            "boundary": boundary,
            "severity": "transient",
            "retryable": True,
            "stack_name": "rns_core",
            "operation": "announce",
        },
    )


def test_handler_captures_tagged_records():
    handler = BoundaryLogHandler()
    logger = _make_logger("test.capture")
    logger.addHandler(handler)

    _emit_boundary(logger, InterfaceBoundary.RNS)

    assert len(handler.snapshot()) == 1
    handler.clear()
    logger.removeHandler(handler)


def test_handler_ignores_untagged_records():
    handler = BoundaryLogHandler()
    logger = _make_logger("test.ignore")
    logger.addHandler(handler)

    logger.error("plain error — no boundary extra")
    logger.warning("another plain warning")

    assert handler.snapshot() == []
    logger.removeHandler(handler)


def test_snapshot_record_fields():
    handler = BoundaryLogHandler()
    logger = _make_logger("test.fields")
    logger.addHandler(handler)

    _emit_boundary(logger, InterfaceBoundary.LXMF, "lxmf failure")
    snap = handler.snapshot()

    assert len(snap) == 1
    rec = snap[0]
    assert rec["boundary"] == InterfaceBoundary.LXMF.value
    assert rec["severity"] == "transient"
    assert rec["retryable"] is True
    assert rec["stack_name"] == "rns_core"
    assert rec["operation"] == "announce"
    assert "lxmf failure" in rec["message"]
    assert isinstance(rec["ts"], float)
    handler.clear()
    logger.removeHandler(handler)


def test_snapshot_returns_list_of_dicts():
    handler = BoundaryLogHandler()
    snap = handler.snapshot()
    assert isinstance(snap, list)


# ---------------------------------------------------------------------------
# Ring buffer / deque capacity
# ---------------------------------------------------------------------------


def test_deque_drops_oldest_at_capacity():
    handler = BoundaryLogHandler()
    logger = _make_logger("test.capacity")
    logger.addHandler(handler)

    # Fill the buffer exactly to capacity
    for i in range(_DEQUE_MAXLEN):
        logger.error(
            f"msg-{i}",
            extra={
                "boundary": InterfaceBoundary.INTERNAL,
                "severity": "transient",
                "retryable": False,
                "stack_name": "loop",
                "operation": f"op-{i}",
            },
        )

    assert len(handler.snapshot()) == _DEQUE_MAXLEN

    # One more should push out the oldest
    logger.error(
        "overflow",
        extra={
            "boundary": InterfaceBoundary.INTERNAL,
            "severity": "transient",
            "retryable": False,
            "stack_name": "loop",
            "operation": "op-overflow",
        },
    )

    snap = handler.snapshot()
    assert len(snap) == _DEQUE_MAXLEN  # still 200, not 201
    # The oldest (op-0) should be gone; the newest should be present
    operations = [r["operation"] for r in snap]
    assert "op-0" not in operations
    assert "op-overflow" in operations

    handler.clear()
    logger.removeHandler(handler)


def test_deque_maxlen_constant():
    assert _DEQUE_MAXLEN == 200


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


def test_clear_empties_buffer():
    handler = BoundaryLogHandler()
    logger = _make_logger("test.clear")
    logger.addHandler(handler)

    _emit_boundary(logger, InterfaceBoundary.RPC)
    assert len(handler.snapshot()) == 1

    handler.clear()
    assert handler.snapshot() == []
    logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Snapshot round-trip (BoundaryRecord → dict → values)
# ---------------------------------------------------------------------------


def test_boundary_record_to_dict_round_trip():
    now = time.time()
    rec = BoundaryRecord(
        ts=now,
        boundary=InterfaceBoundary.IPC.value,
        severity="degraded",
        retryable=False,
        stack_name="ipc_server",
        operation="handle_connect",
        message="connection refused",
    )
    d = rec.to_dict()
    assert d["ts"] == now
    assert d["boundary"] == "ipc"
    assert d["severity"] == "degraded"
    assert d["retryable"] is False
    assert d["stack_name"] == "ipc_server"
    assert d["operation"] == "handle_connect"
    assert d["message"] == "connection refused"


# ---------------------------------------------------------------------------
# NDJSON sink — off by default
# ---------------------------------------------------------------------------


def test_ndjson_sink_off_by_default():
    handler = make_boundary_handler(boundary_sink=False)
    assert handler._file_handler is None
    handler.close()


def test_ndjson_sink_created_when_enabled(tmp_path: Path):
    sink = tmp_path / "boundary.log"
    handler = BoundaryLogHandler(sink_path=sink)
    assert handler._file_handler is not None
    handler.close()


def test_ndjson_sink_writes_json_lines(tmp_path: Path):
    import json

    sink = tmp_path / "boundary.log"
    handler = BoundaryLogHandler(sink_path=sink)
    logger = _make_logger("test.ndjson")
    logger.addHandler(handler)

    _emit_boundary(logger, InterfaceBoundary.WIREGUARD, "wg tunnel down")
    handler.close()
    logger.removeHandler(handler)

    lines = [l for l in sink.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["boundary"] == InterfaceBoundary.WIREGUARD.value
    assert "wg tunnel down" in data["message"]


# ---------------------------------------------------------------------------
# LoggingConfig in models/config.py
# ---------------------------------------------------------------------------


def test_logging_config_boundary_sink_defaults_false():
    from styrened.models.config import LoggingConfig

    cfg = LoggingConfig()
    assert cfg.boundary_sink is False


def test_core_config_has_logging_field():
    from styrened.models.config import CoreConfig

    cfg = CoreConfig()
    assert hasattr(cfg, "logging")
    assert cfg.logging.boundary_sink is False
