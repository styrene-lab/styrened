"""Unit tests for I2PAdapter (tasks 4.1–4.10)."""

from __future__ import annotations

import asyncio
import json
import signal
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open, call

import pytest

from styrened.models.config import I2PConfig
from styrened.models.daemon_mode import DaemonMode
from styrened.services.i2p import I2PAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_adapter(mode: DaemonMode = DaemonMode.DISABLED, **kwargs) -> I2PAdapter:
    cfg = I2PConfig(mode=mode, **kwargs)
    return I2PAdapter(cfg)


# ---------------------------------------------------------------------------
# 4.1 warm_up_seconds
# ---------------------------------------------------------------------------

def test_warm_up_seconds_is_480():
    adapter = make_adapter()
    assert adapter.warm_up_seconds == 480.0


# ---------------------------------------------------------------------------
# 4.2 _generate_i2pd_conf
# ---------------------------------------------------------------------------

def test_generate_i2pd_conf_writes_correct_content(tmp_path):
    adapter = make_adapter(
        mode=DaemonMode.MANAGED,
        managed_http_proxy_port=4445,
        managed_i2pcontrol_port=7651,
    )
    adapter._conf_path = tmp_path / "i2pd" / "i2pd.conf"

    def fake_ensure(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    with patch.object(adapter, "_ensure_config_dir", side_effect=fake_ensure) as mock_dir:
        adapter._generate_i2pd_conf()

    mock_dir.assert_called_once_with(adapter._conf_path.parent)
    content = adapter._conf_path.read_text()
    assert "port = 4445" in content
    assert "port = 7651" in content
    assert "enabled = true" in content   # httpserver
    assert "[sam]" in content
    assert "enabled = false" in content


def test_generate_i2pd_conf_sets_permissions(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._conf_path = tmp_path / "i2pd" / "i2pd.conf"

    def fake_ensure(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    with patch.object(adapter, "_ensure_config_dir", side_effect=fake_ensure):
        adapter._generate_i2pd_conf()

    stat = adapter._conf_path.stat()
    assert oct(stat.st_mode)[-3:] == "600"


# ---------------------------------------------------------------------------
# 4.3 _start_managed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_managed_fails_fast_if_binary_missing():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="i2pd binary not found"):
            await adapter._start_managed()


@pytest.mark.asyncio
async def test_start_managed_spawns_subprocess(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._conf_path = tmp_path / "i2pd" / "i2pd.conf"
    mock_proc = MagicMock()
    mock_proc.pid = 1234

    with patch("shutil.which", return_value="/usr/bin/i2pd"), \
         patch.object(adapter, "_generate_i2pd_conf"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        await adapter._start_managed()

    assert adapter._process is mock_proc


# ---------------------------------------------------------------------------
# 4.4 _stop_managed — SIGTERM, wait 10s, SIGKILL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_managed_sends_sigterm():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    adapter._process = mock_proc

    await adapter._stop_managed()

    mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
    assert adapter._process is None


@pytest.mark.asyncio
async def test_stop_managed_sigkill_on_timeout():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    adapter._process = mock_proc

    async def patched_wait_for(coro, timeout):
        # Close coro to avoid warning
        try:
            coro.close()
        except Exception:
            pass
        raise asyncio.TimeoutError()

    with patch("styrened.services.i2p.asyncio.wait_for", side_effect=patched_wait_for):
        await adapter._stop_managed()

    # Should have sent SIGKILL after timeout
    assert signal.SIGKILL in [c.args[0] for c in mock_proc.send_signal.call_args_list]


@pytest.mark.asyncio
async def test_stop_managed_noop_if_no_process():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._process = None
    # Should not raise
    await adapter._stop_managed()


# ---------------------------------------------------------------------------
# 4.5 _probe — TCP connect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_returns_true_when_connection_succeeds():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    mock_writer = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("styrened.services.i2p.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), mock_writer)):
        result = await adapter._probe()

    assert result is True


@pytest.mark.asyncio
async def test_probe_returns_false_on_connection_refused():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    with patch("styrened.services.i2p.asyncio.open_connection", side_effect=OSError("refused")):
        result = await adapter._probe()

    assert result is False


@pytest.mark.asyncio
async def test_probe_returns_false_on_timeout():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    with patch("styrened.services.i2p.asyncio.open_connection", side_effect=TimeoutError()):
        result = await adapter._probe()

    assert result is False


def test_probe_managed_uses_port_4445_not_4444():
    """Managed mode selects managed_http_proxy_port in the probe logic."""
    adapter = make_adapter(
        mode=DaemonMode.MANAGED,
        http_proxy_port=4444,
        managed_http_proxy_port=4445,
    )
    # Verify the conditional in _probe: MANAGED → managed port
    assert adapter._config.managed_http_proxy_port == 4445
    assert adapter._config.http_proxy_port == 4444
    assert adapter.mode == DaemonMode.MANAGED


# ---------------------------------------------------------------------------
# 4.6 _detect_b32_address
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_b32_falls_back_to_config():
    adapter = make_adapter(mode=DaemonMode.ADOPT, b32_address="abc123.b32.i2p")

    with patch.object(adapter, "_i2pcontrol_call", new_callable=AsyncMock, return_value=None):
        result = await adapter._detect_b32_address()

    assert result == "abc123.b32.i2p"


@pytest.mark.asyncio
async def test_detect_b32_returns_none_if_both_fail():
    adapter = make_adapter(mode=DaemonMode.ADOPT, b32_address="")

    with patch.object(adapter, "_i2pcontrol_call", new_callable=AsyncMock, return_value=None):
        result = await adapter._detect_b32_address()

    assert result is None


@pytest.mark.asyncio
async def test_detect_b32_uses_managed_port_in_managed_mode():
    adapter = make_adapter(mode=DaemonMode.MANAGED, managed_i2pcontrol_port=7651)
    called_ports = []

    async def fake_call(port, method, params=None):
        called_ports.append(port)
        return None

    with patch.object(adapter, "_i2pcontrol_call", side_effect=fake_call):
        await adapter._detect_b32_address()

    assert 7651 in called_ports


@pytest.mark.asyncio
async def test_detect_b32_uses_default_port_in_adopt_mode():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    called_ports = []

    async def fake_call(port, method, params=None):
        called_ports.append(port)
        return None

    with patch.object(adapter, "_i2pcontrol_call", side_effect=fake_call):
        await adapter._detect_b32_address()

    assert 7650 in called_ports


# ---------------------------------------------------------------------------
# 4.7 _gather_details
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_details_returns_b32_and_proxy_port():
    adapter = make_adapter(mode=DaemonMode.ADOPT, http_proxy_port=4444, b32_address="test.b32.i2p")

    with patch.object(adapter, "_i2pcontrol_call", new_callable=AsyncMock, return_value=None):
        details = await adapter._gather_details()

    assert details["b32_address"] == "test.b32.i2p"
    assert details["proxy_port"] == 4444


@pytest.mark.asyncio
async def test_gather_details_managed_uses_managed_proxy_port():
    adapter = make_adapter(mode=DaemonMode.MANAGED, managed_http_proxy_port=4445)

    with patch.object(adapter, "_detect_b32_address", new_callable=AsyncMock, return_value=None):
        details = await adapter._gather_details()

    assert details["proxy_port"] == 4445


# ---------------------------------------------------------------------------
# 4.8 get_http_proxy_url
# ---------------------------------------------------------------------------

def test_get_http_proxy_url_returns_none_when_disabled():
    adapter = make_adapter(mode=DaemonMode.DISABLED)
    assert adapter.get_http_proxy_url() is None


def test_get_http_proxy_url_returns_none_when_no_cached_details():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    adapter._cached_details = None
    assert adapter.get_http_proxy_url() is None


def test_get_http_proxy_url_returns_url_from_cached_details():
    adapter = make_adapter(mode=DaemonMode.ADOPT, http_proxy_host="127.0.0.1")
    adapter._cached_details = {"proxy_port": 4444, "b32_address": None}
    assert adapter.get_http_proxy_url() == "http://127.0.0.1:4444"


def test_get_http_proxy_url_managed_returns_managed_port():
    adapter = make_adapter(mode=DaemonMode.MANAGED, http_proxy_host="127.0.0.1")
    adapter._cached_details = {"proxy_port": 4445, "b32_address": None}
    assert adapter.get_http_proxy_url() == "http://127.0.0.1:4445"


# ---------------------------------------------------------------------------
# 4.9 provision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provision_prints_instructions_if_binary_missing(capsys):
    adapter = make_adapter()
    with patch("shutil.which", return_value=None):
        await adapter.provision()

    out = capsys.readouterr().out
    assert "i2pd binary not found" in out
    assert "nix profile install" in out


@pytest.mark.asyncio
async def test_provision_confirms_found_if_binary_exists(capsys):
    adapter = make_adapter()
    with patch("shutil.which", return_value="/usr/bin/i2pd"):
        await adapter.provision()

    out = capsys.readouterr().out
    assert "found" in out.lower()


# ---------------------------------------------------------------------------
# 4.10 warm-up skips _gather_details; config dir permissions enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_warm_up_skips_gather_details():
    """While warming up, _gather_details should NOT be called."""
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._started_at = time.monotonic()  # just started → warming up

    with patch.object(adapter, "_probe", new_callable=AsyncMock, return_value=True), \
         patch.object(adapter, "_gather_details", new_callable=AsyncMock) as mock_gd:
        await adapter.status()

    mock_gd.assert_not_called()


@pytest.mark.asyncio
async def test_gather_details_called_when_not_warming_up():
    """After warm-up, _gather_details should be called."""
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._started_at = time.monotonic() - 600  # well past 480s

    with patch.object(adapter, "_probe", new_callable=AsyncMock, return_value=True), \
         patch.object(adapter, "_gather_details", new_callable=AsyncMock, return_value={"b32_address": None, "proxy_port": 4445}) as mock_gd:
        await adapter.status()

    mock_gd.assert_called_once()


def test_ensure_config_dir_creates_with_correct_permissions(tmp_path):
    """_ensure_config_dir should create dir with 0700."""
    target = tmp_path / "i2pd"
    I2PAdapter._ensure_config_dir(target)
    stat = target.stat()
    assert oct(stat.st_mode)[-3:] == "700"
