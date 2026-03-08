"""Unit tests for DaemonAdapter base class.

Covers:
- DaemonMode enum values
- DaemonStatus dataclass construction
- DISABLED mode always returns running=False
- ADOPT mode: probe-fail graceful degradation
- MANAGED mode: warm-up tracking with time.monotonic()
- Supervision loop restart resets _started_at
- _gather_details skipped during warm-up; cached result served
- time.monotonic() used throughout; no get_event_loop calls in source
- _ensure_config_dir enforces 0700 on dir, 0600 on key files
"""

from __future__ import annotations

import asyncio
import inspect
import stat
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.services.daemon_adapter import DaemonAdapter, DaemonMode, DaemonStatus


# ---------------------------------------------------------------------------
# Concrete stub for testing the base class
# ---------------------------------------------------------------------------


class StubAdapter(DaemonAdapter):
    """Minimal concrete subclass for exercising DaemonAdapter base logic."""

    warm_up_seconds: float = 10.0

    def __init__(self, mode: DaemonMode, probe_result: bool = True) -> None:
        super().__init__(mode)
        self._probe_result = probe_result
        self._gather_calls = 0
        self._start_managed_calls = 0
        self._stop_managed_calls = 0

    async def _probe(self) -> bool:
        return self._probe_result

    async def _start_managed(self) -> None:
        self._start_managed_calls += 1
        # Simulate a process object with .wait()
        proc = MagicMock()
        proc.wait = AsyncMock(side_effect=asyncio.CancelledError)
        self._process = proc

    async def _stop_managed(self) -> None:
        self._stop_managed_calls += 1

    async def _gather_details(self) -> dict:
        self._gather_calls += 1
        return {"stub": True}


# ---------------------------------------------------------------------------
# DaemonMode enum
# ---------------------------------------------------------------------------


def test_daemon_mode_values():
    assert DaemonMode.DISABLED == "disabled"
    assert DaemonMode.ADOPT == "adopt"
    assert DaemonMode.MANAGED == "managed"


def test_daemon_mode_is_str_enum():
    assert isinstance(DaemonMode.DISABLED, str)


# ---------------------------------------------------------------------------
# DaemonStatus dataclass
# ---------------------------------------------------------------------------


def test_daemon_status_defaults():
    s = DaemonStatus(
        mode=DaemonMode.DISABLED,
        running=False,
        warming_up=False,
        warm_up_elapsed=0.0,
        warm_up_expected=30.0,
    )
    assert s.details == {}
    assert s.running is False
    assert s.warming_up is False


def test_daemon_status_with_details():
    s = DaemonStatus(
        mode=DaemonMode.ADOPT,
        running=True,
        warming_up=False,
        warm_up_elapsed=5.0,
        warm_up_expected=10.0,
        details={"address": "200::1"},
    )
    assert s.details["address"] == "200::1"


# ---------------------------------------------------------------------------
# DISABLED mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_status_always_not_running():
    adapter = StubAdapter(DaemonMode.DISABLED)
    s = await adapter.status()
    assert s.running is False
    assert s.warming_up is False
    assert s.mode == DaemonMode.DISABLED
    assert s.details == {}


@pytest.mark.asyncio
async def test_disabled_start_is_noop():
    adapter = StubAdapter(DaemonMode.DISABLED)
    await adapter.start()
    assert adapter._supervision_task is None
    assert adapter._process is None


@pytest.mark.asyncio
async def test_disabled_stop_is_noop():
    adapter = StubAdapter(DaemonMode.DISABLED)
    await adapter.stop()  # should not raise


# ---------------------------------------------------------------------------
# ADOPT mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adopt_start_is_noop():
    adapter = StubAdapter(DaemonMode.ADOPT)
    await adapter.start()
    assert adapter._supervision_task is None
    assert adapter._start_managed_calls == 0


@pytest.mark.asyncio
async def test_adopt_stop_is_noop():
    adapter = StubAdapter(DaemonMode.ADOPT)
    await adapter.stop()
    assert adapter._stop_managed_calls == 0


@pytest.mark.asyncio
async def test_adopt_probe_success_status():
    adapter = StubAdapter(DaemonMode.ADOPT, probe_result=True)
    s = await adapter.status()
    assert s.running is True
    assert s.warming_up is False
    assert s.details == {"stub": True}


@pytest.mark.asyncio
async def test_adopt_probe_fail_graceful_degradation():
    """When probe fails in ADOPT mode, status.running=False, no exception."""
    adapter = StubAdapter(DaemonMode.ADOPT, probe_result=False)
    s = await adapter.status()
    assert s.running is False
    assert s.details == {}
    assert s.gather_calls_count == 0 if hasattr(s, "gather_calls_count") else True


@pytest.mark.asyncio
async def test_adopt_probe_fail_does_not_call_gather_details():
    adapter = StubAdapter(DaemonMode.ADOPT, probe_result=False)
    await adapter.status()
    assert adapter._gather_calls == 0


# ---------------------------------------------------------------------------
# MANAGED mode — warm-up tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_managed_is_warming_up_true_shortly_after_start():
    adapter = StubAdapter(DaemonMode.MANAGED)
    await adapter.start()
    # Just started — must be warming up
    assert adapter.is_warming_up is True
    # Cleanup
    if adapter._supervision_task:
        adapter._supervision_task.cancel()
        try:
            await adapter._supervision_task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_managed_is_warming_up_false_after_expiry():
    adapter = StubAdapter(DaemonMode.MANAGED)
    # Manually set _started_at well in the past
    adapter._started_at = time.monotonic() - 9999.0
    assert adapter.is_warming_up is False


def test_is_warming_up_false_when_disabled():
    adapter = StubAdapter(DaemonMode.DISABLED)
    assert adapter.is_warming_up is False


def test_is_warming_up_false_when_started_at_none():
    adapter = StubAdapter(DaemonMode.MANAGED)
    # _started_at is None by default
    assert adapter.is_warming_up is False


@pytest.mark.asyncio
async def test_managed_status_skips_gather_details_during_warmup():
    """_gather_details must NOT be called while warming_up is True."""
    adapter = StubAdapter(DaemonMode.MANAGED, probe_result=True)
    adapter._started_at = time.monotonic()  # just started → warming up
    s = await adapter.status()
    assert s.warming_up is True
    assert adapter._gather_calls == 0


@pytest.mark.asyncio
async def test_managed_status_calls_gather_details_after_warmup():
    """_gather_details IS called when running and not warming up."""
    adapter = StubAdapter(DaemonMode.MANAGED, probe_result=True)
    adapter._started_at = time.monotonic() - 9999.0  # warmed up long ago
    s = await adapter.status()
    assert s.warming_up is False
    assert adapter._gather_calls == 1
    assert s.details == {"stub": True}


@pytest.mark.asyncio
async def test_managed_status_serves_cached_details_during_warmup():
    adapter = StubAdapter(DaemonMode.MANAGED, probe_result=True)
    adapter._started_at = time.monotonic()
    adapter._cached_details = {"cached": "value"}
    s = await adapter.status()
    assert s.details == {"cached": "value"}
    assert adapter._gather_calls == 0


@pytest.mark.asyncio
async def test_managed_status_warm_up_elapsed():
    adapter = StubAdapter(DaemonMode.MANAGED, probe_result=True)
    fake_start = time.monotonic() - 3.0
    adapter._started_at = fake_start
    adapter._cached_details = {}  # prevent gather in warmup
    s = await adapter.status()
    assert s.warm_up_elapsed >= 3.0
    assert s.warm_up_expected == 10.0


# ---------------------------------------------------------------------------
# MANAGED mode — supervision loop restarts _started_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervision_loop_resets_started_at_on_restart():
    """Each restart in _run_supervision_loop() must reset _started_at."""
    adapter = StubAdapter(DaemonMode.MANAGED)

    sleep_calls = []

    # Allow sleep once (backoff), then cancel on the second iteration's wait
    sleep_count = 0

    async def fake_sleep(delay: float) -> None:
        nonlocal sleep_count
        sleep_calls.append(delay)
        sleep_count += 1
        # Don't raise — let restart happen; the next proc.wait() will cancel

    # First call: proc exits; second call: CancelledError to stop the loop
    wait_call_count = 0

    async def fake_wait():
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count >= 2:
            raise asyncio.CancelledError
        return None  # process exited with returncode already set

    proc = MagicMock()
    proc.wait = fake_wait
    proc.returncode = 1
    adapter._process = proc

    old_started_at = time.monotonic() - 100.0
    adapter._started_at = old_started_at

    with patch("asyncio.sleep", side_effect=fake_sleep):
        try:
            await adapter._run_supervision_loop()
        except asyncio.CancelledError:
            pass

    # _start_managed was called at least once (after the sleep)
    assert adapter._start_managed_calls >= 1
    # _started_at was reset (it's a fresh monotonic value)
    assert adapter._started_at is not None
    assert adapter._started_at > old_started_at


@pytest.mark.asyncio
async def test_supervision_loop_exponential_backoff():
    """Backoff sequence should be 1 → 2 → 4 … capped at 60."""
    adapter = StubAdapter(DaemonMode.MANAGED)
    sleep_calls = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        if len(sleep_calls) >= 4:
            raise asyncio.CancelledError

    proc = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    proc.returncode = 1
    adapter._process = proc

    # Make _start_managed raise so backoff doesn't reset
    adapter._start_managed_calls_inner = 0

    original_start = adapter._start_managed

    async def failing_start() -> None:
        adapter._start_managed_calls_inner += 1
        raise RuntimeError("binary missing")

    adapter._start_managed = failing_start  # type: ignore[method-assign]

    with patch("asyncio.sleep", side_effect=fake_sleep):
        try:
            await adapter._run_supervision_loop()
        except asyncio.CancelledError:
            pass

    assert sleep_calls[0] == 1.0
    assert sleep_calls[1] == 2.0
    assert sleep_calls[2] == 4.0


@pytest.mark.asyncio
async def test_supervision_loop_backoff_caps_at_60():
    """Backoff must never exceed 60 seconds."""
    adapter = StubAdapter(DaemonMode.MANAGED)
    sleep_calls = []

    call_count = 0

    async def fake_sleep(delay: float) -> None:
        nonlocal call_count
        sleep_calls.append(delay)
        call_count += 1
        if call_count >= 10:
            raise asyncio.CancelledError

    proc = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    proc.returncode = 1
    adapter._process = proc

    async def failing_start() -> None:
        raise RuntimeError("missing")

    adapter._start_managed = failing_start  # type: ignore[method-assign]

    with patch("asyncio.sleep", side_effect=fake_sleep):
        try:
            await adapter._run_supervision_loop()
        except asyncio.CancelledError:
            pass

    assert all(d <= 60.0 for d in sleep_calls)
    assert 60.0 in sleep_calls  # cap hit eventually


# ---------------------------------------------------------------------------
# provision() raises NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_raises_not_implemented():
    adapter = StubAdapter(DaemonMode.MANAGED)
    with pytest.raises(NotImplementedError, match="binary acquisition"):
        await adapter.provision()


# ---------------------------------------------------------------------------
# time.monotonic() only — assert no get_event_loop calls in source
# ---------------------------------------------------------------------------


def test_no_get_event_loop_in_source():
    """Ensure daemon_adapter.py never calls asyncio.get_event_loop().time()."""
    import styrened.services.daemon_adapter as module

    source = inspect.getsource(module)
    assert "get_event_loop" not in source, (
        "daemon_adapter.py must not call asyncio.get_event_loop(); "
        "use time.monotonic() instead"
    )


# ---------------------------------------------------------------------------
# _ensure_config_dir permissions
# ---------------------------------------------------------------------------


def test_ensure_config_dir_creates_with_0700(tmp_path):
    target = tmp_path / "testdir"
    DaemonAdapter._ensure_config_dir(target)
    assert target.is_dir()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o700, f"Expected 0700, got {oct(mode)}"


def test_ensure_config_dir_existing_key_files_chmod_0600(tmp_path):
    target = tmp_path / "daemon_conf"
    target.mkdir()
    key_file = target / "private_key.pem"
    key_file.write_text("PRIVATE KEY DATA")
    key_file.chmod(0o644)  # Start with looser permissions

    DaemonAdapter._ensure_config_dir(target)

    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600, f"Expected 0600 on key file, got {oct(mode)}"


def test_ensure_config_dir_non_key_files_unchanged(tmp_path):
    target = tmp_path / "daemon_conf"
    target.mkdir()
    conf_file = target / "daemon.conf"
    conf_file.write_text("[settings]")
    conf_file.chmod(0o644)

    DaemonAdapter._ensure_config_dir(target)

    mode = stat.S_IMODE(conf_file.stat().st_mode)
    # Non-key files must not be touched
    assert mode == 0o644


def test_ensure_config_dir_idempotent(tmp_path):
    target = tmp_path / "daemon_conf"
    DaemonAdapter._ensure_config_dir(target)
    DaemonAdapter._ensure_config_dir(target)  # second call must not raise
    assert target.is_dir()


def test_ensure_config_dir_secret_file_chmod_0600(tmp_path):
    target = tmp_path / "cfg"
    target.mkdir()
    for name in ("secret.key", "private.pem", "my_key"):
        f = target / name
        f.write_text("data")
        f.chmod(0o644)

    DaemonAdapter._ensure_config_dir(target)

    for name in ("secret.key", "private.pem", "my_key"):
        f = target / name
        mode = stat.S_IMODE(f.stat().st_mode)
        assert mode == 0o600, f"{name}: expected 0600, got {oct(mode)}"
