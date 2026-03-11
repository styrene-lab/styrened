"""Unit tests for CMD_BOUNDARY_SNAPSHOT IPC command."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from styrened.ipc.messages import (
    CmdBoundarySnapshotRequest,
    create_request,
    ErrorResponse,
    ResultResponse,
)
from styrened.ipc.handlers import IPCHandlers
from styrened.ipc.protocol import IPCMessageType


# ---------------------------------------------------------------------------
# Protocol registration
# ---------------------------------------------------------------------------

def test_cmd_boundary_snapshot_enum_value():
    assert IPCMessageType.CMD_BOUNDARY_SNAPSHOT == 0x70


def test_cmd_boundary_snapshot_in_protocol():
    assert hasattr(IPCMessageType, "CMD_BOUNDARY_SNAPSHOT")


# ---------------------------------------------------------------------------
# Message classes
# ---------------------------------------------------------------------------

def test_boundary_snapshot_request_to_payload():
    req = CmdBoundarySnapshotRequest()
    assert req.to_payload() == {}
    assert req.MSG_TYPE == IPCMessageType.CMD_BOUNDARY_SNAPSHOT


def test_boundary_snapshot_request_from_payload_via_create_request():
    req = create_request(IPCMessageType.CMD_BOUNDARY_SNAPSHOT, {})
    assert isinstance(req, CmdBoundarySnapshotRequest)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "ts": 1741641600.0,
        "boundary": "RNS",
        "severity": "transient",
        "retryable": True,
        "stack_name": "rns",
        "operation": "ratchet_persist",
        "message": "FileNotFoundError: /ratchets/abc.out",
    },
    {
        "ts": 1741641601.0,
        "boundary": "LXMF",
        "severity": "degraded",
        "retryable": False,
        "stack_name": "lxmf",
        "operation": "deliver",
        "message": "Delivery timeout",
    },
    {
        "ts": 1741641602.0,
        "boundary": "ASYNC_WORKER",
        "severity": "fatal",
        "retryable": False,
        "stack_name": "asyncio",
        "operation": "task_run",
        "message": "Unhandled exception in background task",
    },
]


def _make_daemon(records: list[dict[str, Any]] | None = None) -> MagicMock:
    daemon = MagicMock()
    if records is None:
        daemon._boundary_handler = None
    else:
        bh = MagicMock()
        bh.snapshot.return_value = records
        daemon._boundary_handler = bh
    return daemon


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_boundary_snapshot_no_daemon_returns_error():
    handlers = IPCHandlers(None)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ErrorResponse)


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_no_handler_returns_empty():
    daemon = _make_daemon(records=None)
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ResultResponse)
    assert resp.data["records"] == []


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_missing_attr_returns_empty():
    """If _boundary_handler attribute doesn't exist at all, return empty list."""
    daemon = MagicMock(spec=["_rpc_client"])  # no _boundary_handler in spec
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ResultResponse)
    assert resp.data["records"] == []


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_empty_buffer():
    daemon = _make_daemon(records=[])
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ResultResponse)
    assert resp.data["records"] == []


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_returns_three_records():
    daemon = _make_daemon(records=SAMPLE_RECORDS)
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ResultResponse)
    assert len(resp.data["records"]) == 3


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_record_keys():
    required = {"ts", "boundary", "severity", "retryable", "stack_name", "operation", "message"}
    daemon = _make_daemon(records=SAMPLE_RECORDS)
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    for record in resp.data["records"]:
        assert required.issubset(record.keys())


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_record_values():
    daemon = _make_daemon(records=SAMPLE_RECORDS)
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    records = resp.data["records"]
    assert records[0]["boundary"] == "RNS"
    assert records[1]["severity"] == "degraded"
    assert records[2]["retryable"] is False


@pytest.mark.asyncio
async def test_handle_boundary_snapshot_exception_returns_error():
    daemon = MagicMock()
    bh = MagicMock()
    bh.snapshot.side_effect = RuntimeError("buffer corrupted")
    daemon._boundary_handler = bh
    handlers = IPCHandlers(daemon)
    resp = await handlers.handle_cmd_boundary_snapshot(CmdBoundarySnapshotRequest())
    assert isinstance(resp, ErrorResponse)
