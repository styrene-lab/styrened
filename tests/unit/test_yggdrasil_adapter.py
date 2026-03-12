"""Unit tests for YggdrasilAdapter."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import stat
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from styrened.services.daemon_adapter import DaemonMode, DaemonStatus
from styrened.services.yggdrasil import (
    MANAGED_PORT,
    SYSTEM_SOCKET_PATHS,
    YggdrasilAdapter,
    YggdrasilConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_adapter(
    mode: DaemonMode = DaemonMode.DISABLED,
    initial_peers: list[str] | None = None,
    multicast: bool = True,
    admin_socket: str = "",
) -> YggdrasilAdapter:
    cfg = YggdrasilConfig(
        mode=mode,
        initial_peers=initial_peers or [],
        multicast=multicast,
        admin_socket=admin_socket,
    )
    return YggdrasilAdapter(cfg)


# ---------------------------------------------------------------------------
# warm_up_seconds
# ---------------------------------------------------------------------------

def test_warm_up_seconds_is_30():
    adapter = make_adapter()
    assert adapter.warm_up_seconds == 30.0


# ---------------------------------------------------------------------------
# _ensure_yggdrasil_config
# ---------------------------------------------------------------------------

def test_ensure_yggdrasil_config_writes_file(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    with patch.object(adapter, "_managed_config_dir", return_value=tmp_path), \
         patch.object(adapter, "_managed_conf_path", return_value=tmp_path / "yggdrasil.conf"), \
         patch.object(adapter, "_managed_socket_path", return_value=tmp_path / "yggdrasil.sock"):
        adapter._ensure_yggdrasil_config()

    conf_path = tmp_path / "yggdrasil.conf"
    assert conf_path.exists()
    data = json.loads(conf_path.read_text())
    # Managed port
    assert any(str(MANAGED_PORT) in l for l in data["Listen"])
    # Admin socket
    assert str(tmp_path / "yggdrasil.sock") in data["AdminListen"]


def test_ensure_yggdrasil_config_includes_initial_peers(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED, initial_peers=["tcp://1.2.3.4:9001"])
    with patch.object(adapter, "_managed_config_dir", return_value=tmp_path), \
         patch.object(adapter, "_managed_conf_path", return_value=tmp_path / "yggdrasil.conf"), \
         patch.object(adapter, "_managed_socket_path", return_value=tmp_path / "yggdrasil.sock"):
        adapter._ensure_yggdrasil_config()

    data = json.loads((tmp_path / "yggdrasil.conf").read_text())
    assert "tcp://1.2.3.4:9001" in data["Peers"]


def test_ensure_yggdrasil_config_permissions(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    with patch.object(adapter, "_managed_config_dir", return_value=tmp_path), \
         patch.object(adapter, "_managed_conf_path", return_value=tmp_path / "yggdrasil.conf"), \
         patch.object(adapter, "_managed_socket_path", return_value=tmp_path / "yggdrasil.sock"):
        adapter._ensure_yggdrasil_config()

    conf_path = tmp_path / "yggdrasil.conf"
    perms = oct(stat.S_IMODE(conf_path.stat().st_mode))
    assert perms == oct(0o600)


def test_ensure_config_dir_sets_0700(tmp_path):
    target = tmp_path / "subdir"
    YggdrasilAdapter._ensure_config_dir(target)
    perms = oct(stat.S_IMODE(target.stat().st_mode))
    assert perms == oct(0o700)


# ---------------------------------------------------------------------------
# _start_managed — fail fast if binary missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_managed_fails_fast_if_binary_missing():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    with patch("shutil.which", return_value=None), \
         patch("os.access", return_value=False), \
         patch.object(Path, "exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="yggdrasil binary not found"):
            await adapter._start_managed()


@pytest.mark.asyncio
async def test_start_managed_spawns_process(tmp_path):
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    mock_proc = MagicMock()
    mock_proc.pid = 12345

    with patch("shutil.which", return_value="/usr/bin/yggdrasil"), \
         patch.object(adapter, "_ensure_yggdrasil_config"), \
         patch.object(adapter, "_managed_conf_path", return_value=tmp_path / "yggdrasil.conf"), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        await adapter._start_managed()

    assert adapter._process is mock_proc


# ---------------------------------------------------------------------------
# _stop_managed — SIGTERM → wait → SIGKILL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_managed_sends_sigterm():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    mock_proc = AsyncMock()
    mock_proc.send_signal = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    adapter._process = mock_proc

    await adapter._stop_managed()

    mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
    assert adapter._process is None


@pytest.mark.asyncio
async def test_stop_managed_sigkill_on_timeout():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    mock_proc = AsyncMock()
    mock_proc.send_signal = MagicMock()
    mock_proc.kill = MagicMock()

    call_count = 0

    async def wait_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()
        return 0

    with patch("asyncio.wait_for", side_effect=[asyncio.TimeoutError(), None]):
        mock_proc.send_signal = MagicMock()
        mock_proc.kill = MagicMock()
        adapter._process = mock_proc
        await adapter._stop_managed()

    mock_proc.kill.assert_called_once()
    assert adapter._process is None


@pytest.mark.asyncio
async def test_stop_managed_noop_when_no_process():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._process = None
    # Should not raise
    await adapter._stop_managed()


# ---------------------------------------------------------------------------
# _probe — socket path ordering and success/failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_managed_socket_first():
    """In MANAGED mode, the managed socket path is tried first."""
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    checked_paths: list[Path] = []

    async def fake_admin_call_on(sock_path, method, params=None, timeout=5.0):
        checked_paths.append(sock_path)
        if sock_path == adapter._managed_socket_path():
            return {"address": "200::1"}
        return None

    with patch.object(adapter, "_admin_call_on", side_effect=fake_admin_call_on):
        result = await adapter._probe()

    assert result is True
    assert checked_paths[0] == adapter._managed_socket_path()
    assert adapter._active_socket == adapter._managed_socket_path()


@pytest.mark.asyncio
async def test_probe_falls_through_to_system_paths():
    """In ADOPT mode with no admin_socket set, system socket paths are tried."""
    adapter = make_adapter(mode=DaemonMode.ADOPT)

    async def fake_admin_call_on(sock_path, method, params=None, timeout=5.0):
        if sock_path == SYSTEM_SOCKET_PATHS[0]:
            return {"address": "200::2"}
        raise ConnectionRefusedError("not here")

    with patch.object(adapter, "_admin_call_on", side_effect=fake_admin_call_on):
        result = await adapter._probe()

    assert result is True
    assert adapter._active_socket == SYSTEM_SOCKET_PATHS[0]


@pytest.mark.asyncio
async def test_probe_returns_false_when_all_sockets_fail():
    adapter = make_adapter(mode=DaemonMode.ADOPT)

    async def fake_admin_call_on(sock_path, method, params=None, timeout=5.0):
        raise ConnectionRefusedError("not here")

    with patch.object(adapter, "_admin_call_on", side_effect=fake_admin_call_on):
        result = await adapter._probe()

    assert result is False
    assert adapter._active_socket is None


@pytest.mark.asyncio
async def test_probe_adopt_uses_configured_socket():
    adapter = make_adapter(mode=DaemonMode.ADOPT, admin_socket="/custom/sock")

    checked_paths: list[Path] = []

    async def fake_admin_call_on(sock_path, method, params=None, timeout=5.0):
        checked_paths.append(sock_path)
        if sock_path == Path("/custom/sock"):
            return {"address": "200::3"}
        raise ConnectionRefusedError()

    with patch.object(adapter, "_admin_call_on", side_effect=fake_admin_call_on):
        result = await adapter._probe()

    assert result is True
    assert checked_paths[0] == Path("/custom/sock")


# ---------------------------------------------------------------------------
# _gather_details — caches address, returns peer count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_details_caches_local_address():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._active_socket = Path("/fake/sock")

    async def fake_admin_call(method, params=None, timeout=5.0):
        if method == "getSelf":
            return {"address": "200::abcd"}
        if method == "getPeers":
            return {"peers": [{"addr": "200::1"}, {"addr": "200::2"}]}
        return None

    with patch.object(adapter, "_admin_call", side_effect=fake_admin_call):
        details = await adapter._gather_details()

    assert details["address"] == "200::abcd"
    assert details["peer_count"] == 2
    assert adapter.get_local_address() == "200::abcd"


@pytest.mark.asyncio
async def test_gather_details_handles_missing_address():
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._active_socket = Path("/fake/sock")

    async def fake_admin_call(method, params=None, timeout=5.0):
        if method == "getSelf":
            return {}
        if method == "getPeers":
            return {"peers": []}
        return None

    with patch.object(adapter, "_admin_call", side_effect=fake_admin_call):
        details = await adapter._gather_details()

    assert "address" not in details
    assert details["peer_count"] == 0


# ---------------------------------------------------------------------------
# get_local_address — returns cached or None
# ---------------------------------------------------------------------------

def test_get_local_address_returns_none_initially():
    adapter = make_adapter()
    assert adapter.get_local_address() is None


def test_get_local_address_returns_cached():
    adapter = make_adapter()
    adapter._local_address = "200::cafe"
    assert adapter.get_local_address() == "200::cafe"


# ---------------------------------------------------------------------------
# add_peer — ephemeral, no filesystem write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_peer_calls_admin_socket():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    adapter._active_socket = Path("/fake/sock")

    calls: list[tuple] = []

    async def fake_admin_call(method, params=None, timeout=5.0):
        calls.append((method, params))
        return {"added": ["tcp://1.2.3.4:9001"]}

    with patch.object(adapter, "_admin_call", side_effect=fake_admin_call):
        result = await adapter.add_peer("1.2.3.4", 9001)

    assert result is True
    assert calls[0][0] == "addPeer"
    assert calls[0][1]["uri"] == "tcp://1.2.3.4:9001"


@pytest.mark.asyncio
async def test_add_peer_does_not_write_to_filesystem(tmp_path):
    """add_peer must not touch any config file."""
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    adapter._active_socket = Path("/fake/sock")

    files_before = set(tmp_path.rglob("*"))

    with patch.object(adapter, "_admin_call", new=AsyncMock(return_value={"added": []})):
        await adapter.add_peer("1.2.3.4")

    files_after = set(tmp_path.rglob("*"))
    assert files_before == files_after


@pytest.mark.asyncio
async def test_add_peer_returns_false_when_not_running():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    adapter._active_socket = None

    with patch.object(adapter, "_probe", new=AsyncMock(return_value=False)):
        result = await adapter.add_peer("1.2.3.4")

    assert result is False


@pytest.mark.asyncio
async def test_add_peer_returns_false_on_exception():
    adapter = make_adapter(mode=DaemonMode.ADOPT)
    adapter._active_socket = Path("/fake/sock")

    async def raise_exc(method, params=None, timeout=5.0):
        raise ConnectionRefusedError("socket gone")

    with patch.object(adapter, "_admin_call", side_effect=raise_exc):
        result = await adapter.add_peer("1.2.3.4")

    assert result is False


# ---------------------------------------------------------------------------
# provision — prints instructions, does NOT install
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provision_prints_found_message(capsys):
    adapter = make_adapter()
    with patch.object(adapter, "_find_binary", return_value="/usr/bin/yggdrasil"):
        await adapter.provision()

    captured = capsys.readouterr()
    assert "found" in captured.out.lower()
    assert "/usr/bin/yggdrasil" in captured.out


@pytest.mark.asyncio
async def test_provision_prints_install_instructions_when_missing(capsys):
    adapter = make_adapter()
    with patch.object(adapter, "_find_binary", return_value=None):
        await adapter.provision()

    captured = capsys.readouterr()
    assert "nix profile install" in captured.out
    assert "nixpkgs#yggdrasil" in captured.out


@pytest.mark.asyncio
async def test_provision_does_not_install(capsys):
    """provision() must not execute any install command."""
    adapter = make_adapter()
    with patch("shutil.which", return_value=None), \
         patch.object(Path, "exists", return_value=False), \
         patch("subprocess.run") as mock_run, \
         patch("subprocess.check_call") as mock_check:
        await adapter.provision()

    mock_run.assert_not_called()
    mock_check.assert_not_called()


# ---------------------------------------------------------------------------
# status() integration — disabled, adopt probe, warm-up
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_disabled_returns_not_running():
    adapter = make_adapter(mode=DaemonMode.DISABLED)
    st = await adapter.status()
    assert not st.running
    assert not st.warming_up
    assert st.mode == DaemonMode.DISABLED


@pytest.mark.asyncio
async def test_status_adopt_probe_fail_graceful():
    adapter = make_adapter(mode=DaemonMode.ADOPT)

    with patch.object(adapter, "_probe", new=AsyncMock(return_value=False)):
        st = await adapter.status()

    assert not st.running
    assert st.details == {}


@pytest.mark.asyncio
async def test_status_managed_skips_gather_details_during_warmup():
    import time
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    adapter._started_at = time.monotonic()  # just started → warming up

    gather_called = False

    async def fake_gather():
        nonlocal gather_called
        gather_called = True
        return {"address": "200::1"}

    with patch.object(adapter, "_probe", new=AsyncMock(return_value=True)), \
         patch.object(adapter, "_gather_details", side_effect=fake_gather):
        st = await adapter.status()

    assert st.running
    assert st.warming_up
    assert not gather_called


@pytest.mark.asyncio
async def test_status_calls_gather_details_after_warmup():
    import time
    adapter = make_adapter(mode=DaemonMode.MANAGED)
    # Simulate warm-up already complete
    adapter._started_at = time.monotonic() - 100.0

    with patch.object(adapter, "_probe", new=AsyncMock(return_value=True)), \
         patch.object(adapter, "_gather_details", new=AsyncMock(return_value={"address": "200::1", "peer_count": 3})):
        st = await adapter.status()

    assert st.running
    assert not st.warming_up
    assert st.details["address"] == "200::1"
    assert st.details["peer_count"] == 3
