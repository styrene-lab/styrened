"""Unit tests for doctor.py Yggdrasil and I2P check functions.

Covers all DaemonMode × running combinations for both adapters.
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.daemon_mode import DaemonMode
from styrened.services.daemon_adapter import DaemonStatus
from styrened.services.doctor import CheckCategory, Finding, Severity, check_i2p, check_yggdrasil


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ygg_config(mode: DaemonMode = DaemonMode.DISABLED) -> MagicMock:
    cfg = MagicMock()
    cfg.mode = mode
    cfg.binary_path = "yggdrasil"
    cfg.admin_socket = ""
    return cfg


def _i2p_config(mode: DaemonMode = DaemonMode.DISABLED) -> MagicMock:
    cfg = MagicMock()
    cfg.mode = mode
    cfg.http_proxy_host = "127.0.0.1"
    cfg.http_proxy_port = 4444
    cfg.managed_http_proxy_port = 4445
    cfg.managed_i2pcontrol_port = 7651
    cfg.b32_address = ""
    return cfg


def _core_config(ygg_mode: DaemonMode = DaemonMode.DISABLED, i2p_mode: DaemonMode = DaemonMode.DISABLED) -> MagicMock:
    core = MagicMock()
    core.yggdrasil = _ygg_config(ygg_mode)
    core.i2p = _i2p_config(i2p_mode)
    return core


def _ygg_status(running: bool = False, details: dict | None = None) -> DaemonStatus:
    return DaemonStatus(
        mode=DaemonMode.ADOPT,
        running=running,
        warming_up=False,
        warm_up_elapsed=0.0,
        warm_up_expected=30.0,
        details=details or {},
    )


def _i2p_status(
    running: bool = False,
    warming_up: bool = False,
    elapsed: float = 0.0,
    details: dict | None = None,
    mode: DaemonMode = DaemonMode.ADOPT,
) -> DaemonStatus:
    return DaemonStatus(
        mode=mode,
        running=running,
        warming_up=warming_up,
        warm_up_elapsed=elapsed,
        warm_up_expected=480.0,
        details=details or {},
    )


# ---------------------------------------------------------------------------
# Yggdrasil checks
# ---------------------------------------------------------------------------


class TestCheckYggdrasilDisabled:
    """mode=DISABLED — silently skip."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.DISABLED)
        findings = await check_yggdrasil(config=config)
        assert findings == []


class TestCheckYggdrasilAdopt:
    """mode=ADOPT — probe only, no binary check."""

    @pytest.mark.asyncio
    async def test_adopt_not_running_warns(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.ADOPT)
        status = _ygg_status(running=False)
        with patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter:
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_yggdrasil(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.category == CheckCategory.YGGDRASIL
        assert f.severity == Severity.WARN
        assert "not detected" in f.message
        assert "socket" in f.message.lower() or "running" in f.message.lower()

    @pytest.mark.asyncio
    async def test_adopt_running_ok_with_details(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.ADOPT)
        status = _ygg_status(running=True, details={"address": "200::1", "peer_count": 3})
        with patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter:
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_yggdrasil(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.OK
        assert "200::1" in f.message
        assert "3" in f.message

    @pytest.mark.asyncio
    async def test_adopt_running_no_binary_check(self) -> None:
        """ADOPT mode should NOT check for binary — even if shutil.which returns None."""
        config = _core_config(ygg_mode=DaemonMode.ADOPT)
        status = _ygg_status(running=True, details={"address": "200::2", "peer_count": 1})
        # Patch shutil.which to return None to prove ADOPT doesn't gate on binary
        with (
            patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter,
            patch("shutil.which", return_value=None),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_yggdrasil(config=config)

        # Should still succeed — ADOPT doesn't check binary
        assert len(findings) == 1
        assert findings[0].severity == Severity.OK


class TestCheckYggdrasilManaged:
    """mode=MANAGED — binary check first, then status."""

    @pytest.mark.asyncio
    async def test_managed_binary_missing_errors(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.MANAGED)
        with (
            patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter,
            patch("shutil.which", return_value=None),
        ):
            findings = await check_yggdrasil(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.ERROR
        assert "yggdrasil" in f.message.lower()
        assert f.fix_hint is not None
        assert "setup" in f.fix_hint
        assert "yggdrasil" in f.fix_hint
        # Adapter should not be instantiated when binary is missing
        MockAdapter.assert_not_called()

    @pytest.mark.asyncio
    async def test_managed_binary_present_running_ok(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.MANAGED)
        status = _ygg_status(running=True, details={"address": "200::3", "peer_count": 5})
        with (
            patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter,
            patch("shutil.which", return_value="/usr/bin/yggdrasil"),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_yggdrasil(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.OK
        assert "200::3" in f.message
        assert "5" in f.message

    @pytest.mark.asyncio
    async def test_managed_binary_present_not_running_warns(self) -> None:
        config = _core_config(ygg_mode=DaemonMode.MANAGED)
        status = _ygg_status(running=False)
        with (
            patch("styrened.services.doctor.YggdrasilAdapter") as MockAdapter,
            patch("shutil.which", return_value="/usr/bin/yggdrasil"),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_yggdrasil(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.WARN


# ---------------------------------------------------------------------------
# I2P checks
# ---------------------------------------------------------------------------


class TestCheckI2PDisabled:
    """mode=DISABLED — silently skip."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.DISABLED)
        findings = await check_i2p(config=config)
        assert findings == []


class TestCheckI2PAdopt:
    """mode=ADOPT — probe only, no binary check."""

    @pytest.mark.asyncio
    async def test_adopt_not_running_warns_with_address(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.ADOPT)
        status = _i2p_status(running=False)
        with patch("styrened.services.doctor.I2PAdapter") as MockAdapter:
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.WARN
        assert "127.0.0.1:4444" in f.message

    @pytest.mark.asyncio
    async def test_adopt_running_ok(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.ADOPT)
        status = _i2p_status(running=True, details={"proxy_port": 4444})
        with patch("styrened.services.doctor.I2PAdapter") as MockAdapter:
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.OK
        assert "4444" in f.message


class TestCheckI2PManaged:
    """mode=MANAGED — binary check, warm-up awareness, ok."""

    @pytest.mark.asyncio
    async def test_managed_binary_missing_errors(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.MANAGED)
        with (
            patch("styrened.services.doctor.I2PAdapter") as MockAdapter,
            patch("shutil.which", return_value=None),
        ):
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.ERROR
        assert "i2pd" in f.message.lower()
        assert f.fix_hint is not None
        assert "setup" in f.fix_hint
        assert "i2p" in f.fix_hint
        MockAdapter.assert_not_called()

    @pytest.mark.asyncio
    async def test_managed_warming_up_info(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.MANAGED)
        # 60 seconds elapsed, 480 expected → 420 remaining → 7 mins
        status = _i2p_status(
            running=True,
            warming_up=True,
            elapsed=60.0,
            mode=DaemonMode.MANAGED,
        )
        with (
            patch("styrened.services.doctor.I2PAdapter") as MockAdapter,
            patch("shutil.which", return_value="/usr/bin/i2pd"),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.OK
        assert "warming up" in f.message.lower()
        assert "7" in f.message  # ceil((480-60)/60) = ceil(7) = 7

    @pytest.mark.asyncio
    async def test_managed_running_ok(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.MANAGED)
        status = _i2p_status(
            running=True,
            warming_up=False,
            details={"proxy_port": 4445},
            mode=DaemonMode.MANAGED,
        )
        with (
            patch("styrened.services.doctor.I2PAdapter") as MockAdapter,
            patch("shutil.which", return_value="/usr/bin/i2pd"),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.OK
        assert "4445" in f.message

    @pytest.mark.asyncio
    async def test_managed_not_running_warns(self) -> None:
        config = _core_config(i2p_mode=DaemonMode.MANAGED)
        status = _i2p_status(running=False, mode=DaemonMode.MANAGED)
        with (
            patch("styrened.services.doctor.I2PAdapter") as MockAdapter,
            patch("shutil.which", return_value="/usr/bin/i2pd"),
        ):
            MockAdapter.return_value.status = AsyncMock(return_value=status)
            findings = await check_i2p(config=config)

        assert len(findings) == 1
        f = findings[0]
        assert f.severity == Severity.WARN
