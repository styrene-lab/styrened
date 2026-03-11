"""Unit tests for check_boundary_log() in styrened.services.doctor.

Tests validate:
- >5 records for a boundary tag → WARN finding with count + last-seen + fix_hint
- ≤5 transient-only records → OK (INFO) finding
- daemon not running (no socket) → no findings, no error raised
- CMD_BOUNDARY_SNAPSHOT missing from IPCMessageType → skip gracefully
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.services.doctor import (
    CheckCategory,
    Severity,
    _BOUNDARY_WARN_THRESHOLD,
    check_boundary_log,
)


# ---------------------------------------------------------------------------
# Record/snapshot factories
# ---------------------------------------------------------------------------


def _record(
    boundary: str = "RNS",
    severity: str = "transient",
    ts: str = "2026-03-10T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "boundary": boundary,
        "severity": severity,
        "ts": ts,
        "retryable": True,
        "stack_name": boundary.lower(),
        "operation": "test_op",
        "message": "test message",
    }


def _snapshot(
    boundary: str = "RNS",
    count: int = 1,
    severity: str = "transient",
) -> list[dict[str, Any]]:
    return [
        _record(boundary=boundary, severity=severity, ts=f"2026-03-10T00:00:{i:02d}+00:00")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# IPC client builder
# ---------------------------------------------------------------------------


def _make_client(snapshot: list[dict[str, Any]]) -> AsyncMock:
    """Build a ControlClient mock that returns *snapshot* from _request()."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client._request = AsyncMock(return_value=snapshot)
    return client


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _fake_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make control_socket() return an existing file path."""
    sock = tmp_path / "styrened.sock"
    sock.touch()
    monkeypatch.setattr("styrened.services.doctor.paths.control_socket", lambda: sock)
    return sock


def _no_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make control_socket() return a nonexistent path."""
    monkeypatch.setattr(
        "styrened.services.doctor.paths.control_socket",
        lambda: tmp_path / "nonexistent.sock",
    )


def _patch_ipc(monkeypatch: pytest.MonkeyPatch, client: AsyncMock) -> None:
    """Patch ControlClient and get_default_socket_path inside the doctor module.

    Also ensures IPCMessageType has CMD_BOUNDARY_SNAPSHOT so the function
    doesn't bail out early (the real attribute is added by the ipc-command
    sibling task and may not exist in the current build).
    """
    # doctor.py does: from styrened.ipc import ControlClient, ...
    # Patching the styrened.ipc namespace means the local import picks up the mock.
    monkeypatch.setattr("styrened.ipc.ControlClient", lambda **_: client)
    monkeypatch.setattr("styrened.ipc.get_default_socket_path", lambda: "/tmp/test.sock")

    # Ensure CMD_BOUNDARY_SNAPSHOT is present on IPCMessageType.
    # The real attribute is added by the ipc-command sibling task.  When tests
    # run in isolation (before that task merges) we patch at the module level
    # using a plain object so getattr() in check_boundary_log() returns a value.
    from styrened.ipc import IPCMessageType
    if not hasattr(IPCMessageType, "CMD_BOUNDARY_SNAPSHOT"):
        import types
        stub = types.SimpleNamespace(**{m.name: m for m in IPCMessageType})
        stub.CMD_BOUNDARY_SNAPSHOT = 0x70  # type: ignore[attr-defined]
        monkeypatch.setattr("styrened.ipc.IPCMessageType", stub)


# ---------------------------------------------------------------------------
# Tests: daemon not running
# ---------------------------------------------------------------------------


class TestDaemonNotRunning:
    @pytest.mark.asyncio
    async def test_no_socket_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_socket(tmp_path, monkeypatch)
        findings = await check_boundary_log()
        assert findings == []

    @pytest.mark.asyncio
    async def test_no_socket_no_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_socket(tmp_path, monkeypatch)
        # Must not raise
        await check_boundary_log()


# ---------------------------------------------------------------------------
# Tests: CMD_BOUNDARY_SNAPSHOT absent
# ---------------------------------------------------------------------------


class TestMissingCommand:
    @pytest.mark.asyncio
    async def test_missing_cmd_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)

        # Patch IPCMessageType inside the doctor import path so getattr returns None
        class _NoCmd:
            pass

        monkeypatch.setattr("styrened.ipc.IPCMessageType", _NoCmd)

        findings = await check_boundary_log()
        assert findings == []


# ---------------------------------------------------------------------------
# Tests: >5 records → WARN
# ---------------------------------------------------------------------------


class TestWarnFinding:
    @pytest.mark.asyncio
    async def test_six_records_produce_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        client = _make_client(_snapshot("RNS", count=_BOUNDARY_WARN_THRESHOLD + 1))
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()

        warn = [f for f in findings if f.severity == Severity.WARN]
        assert len(warn) == 1, f"Expected 1 WARN, got: {findings}"
        assert warn[0].category == CheckCategory.BOUNDARY_LOG
        assert "RNS" in warn[0].message
        assert str(_BOUNDARY_WARN_THRESHOLD + 1) in warn[0].message
        assert warn[0].fix_hint is not None

    @pytest.mark.asyncio
    async def test_warn_includes_last_seen_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        snap = _snapshot("LXMF", count=6)
        latest_ts = "2026-03-10T21:59:59+00:00"
        snap[-1]["ts"] = latest_ts

        client = _make_client(snap)
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        warn = [f for f in findings if f.severity == Severity.WARN]
        assert len(warn) == 1
        assert latest_ts in warn[0].message

    @pytest.mark.asyncio
    async def test_exactly_five_records_not_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        client = _make_client(_snapshot("RNS", count=_BOUNDARY_WARN_THRESHOLD))
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        warn = [f for f in findings if f.severity == Severity.WARN]
        assert warn == [], "Exactly threshold records must NOT produce WARN"


# ---------------------------------------------------------------------------
# Tests: ≤5 transient-only records → OK
# ---------------------------------------------------------------------------


class TestInfoFinding:
    @pytest.mark.asyncio
    async def test_three_transient_records_produce_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        client = _make_client(_snapshot("RNS", count=3, severity="transient"))
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        ok = [f for f in findings if f.severity == Severity.OK]
        assert len(ok) == 1
        assert ok[0].category == CheckCategory.BOUNDARY_LOG
        assert "RNS" in ok[0].message

    @pytest.mark.asyncio
    async def test_single_transient_record_no_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        client = _make_client(_snapshot("IPC", count=1, severity="transient"))
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        assert all(f.severity != Severity.WARN for f in findings)

    @pytest.mark.asyncio
    async def test_empty_snapshot_returns_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        client = _make_client([])
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        assert findings == []


# ---------------------------------------------------------------------------
# Tests: multiple boundary tags grouped independently
# ---------------------------------------------------------------------------


class TestMultipleTags:
    @pytest.mark.asyncio
    async def test_two_tags_independent_severity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)
        # RNS: 7 records → WARN; LXMF: 2 transient → OK
        snap = _snapshot("RNS", count=7) + _snapshot("LXMF", count=2, severity="transient")
        client = _make_client(snap)
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        warn = [f for f in findings if f.severity == Severity.WARN]
        ok = [f for f in findings if f.severity == Severity.OK]

        assert len(warn) == 1
        assert "RNS" in warn[0].message
        assert len(ok) == 1
        assert "LXMF" in ok[0].message


# ---------------------------------------------------------------------------
# Tests: IPC connection failure → graceful skip
# ---------------------------------------------------------------------------


class TestConnectionFailure:
    @pytest.mark.asyncio
    async def test_ipc_error_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_socket(tmp_path, monkeypatch)

        from styrened.ipc import IPCConnectionError

        client = AsyncMock()
        client.connect = AsyncMock(side_effect=IPCConnectionError("refused"))
        client.disconnect = AsyncMock()
        _patch_ipc(monkeypatch, client)

        findings = await check_boundary_log()
        assert findings == []
