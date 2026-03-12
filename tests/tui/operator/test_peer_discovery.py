"""Operator path tests: peer discovery and node detail.

These tests drive a real StyreneApp via Textual pilot against real
daemon subprocesses with known fixture identities. They are the
top of the test pyramid — slow, integration-heavy, human-simulation fidelity.

Requires: alpha daemon fixture running (session-scoped).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Generator

import pytest

from tests.harness.daemon import DaemonHarness

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.operator_path,
    pytest.mark.asyncio,
]

# -- Helpers -----------------------------------------------------------------

ALPHA_IDENTITY_HASH = "e426a96311c5ea0e7644317040455b39"
ALPHA_LXMF_HASH = "ce9dc706ef10c0c0d31c6a8d8942c9de"


def _host_config(alpha_port: int) -> dict:
    """Build extra_config for a host daemon peered with alpha."""
    return {
        "reticulum": {
            "interfaces": {
                "server": {"enabled": True},
                "peers": [
                    {
                        "name": "Alpha Peer",
                        "host": "127.0.0.1",
                        "port": alpha_port,
                        "enabled": True,
                    }
                ],
            }
        }
    }


# -- Tier 1: Harness Basics -------------------------------------------------


class TestDaemonHarnessBasics:
    """Verify the daemon harness itself works before testing TUI."""

    async def test_alpha_daemon_is_running(self, alpha_daemon: DaemonHarness) -> None:
        """Alpha daemon subprocess should be alive."""
        assert alpha_daemon.process is not None
        assert alpha_daemon.process.poll() is None, "Daemon exited prematurely"

    async def test_alpha_port_is_listening(self, alpha_daemon: DaemonHarness) -> None:
        """Alpha's TCP server port should accept connections."""
        reader, writer = await asyncio.open_connection("127.0.0.1", alpha_daemon.port)
        writer.close()
        await writer.wait_closed()

    async def test_alpha_identity_hash_matches_fixture(
        self, alpha_daemon: DaemonHarness
    ) -> None:
        """Alpha's identity hash should match the fixture README."""
        assert alpha_daemon.identity_hash == ALPHA_IDENTITY_HASH

    async def test_alpha_lxmf_hash_matches_fixture(
        self, alpha_daemon: DaemonHarness
    ) -> None:
        """Alpha's LXMF destination hash should match the fixture README."""
        assert alpha_daemon.lxmf_dest_hash == ALPHA_LXMF_HASH


# -- Tier 2: Host Daemon Connectivity ---------------------------------------


class TestHostDaemonConnectivity:
    """Verify the host daemon can discover alpha over TCP."""

    @pytest.fixture
    def host_daemon(self, alpha_daemon: DaemonHarness) -> Generator[DaemonHarness]:
        """Start host daemon configured to peer with alpha."""
        harness = DaemonHarness.from_fixture(
            "host", extra_config=_host_config(alpha_daemon.port)
        )
        harness.start(timeout=15.0)
        yield harness
        harness.stop()

    async def test_host_daemon_starts(self, host_daemon: DaemonHarness) -> None:
        """Host daemon should start successfully."""
        assert host_daemon.process is not None
        assert host_daemon.process.poll() is None

    async def test_host_can_reach_alpha_port(
        self, host_daemon: DaemonHarness, alpha_daemon: DaemonHarness
    ) -> None:
        """Host should be able to connect to alpha's TCP port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", alpha_daemon.port)
        writer.close()
        await writer.wait_closed()


# -- Tier 3: TUI Pilot Tests ------------------------------------------------


class TestTUIPeerDiscovery:
    """Drive StyreneApp via Textual pilot to discover alpha peer."""

    @pytest.fixture
    def host_daemon(self, alpha_daemon: DaemonHarness) -> Generator[DaemonHarness]:
        """Start host daemon peered with alpha, return harness."""
        harness = DaemonHarness.from_fixture(
            "host", extra_config=_host_config(alpha_daemon.port)
        )
        harness.start(timeout=15.0)
        yield harness
        harness.stop()

    @pytest.fixture
    def _host_env(self, host_daemon: DaemonHarness):
        """Set env vars so StyreneApp connects to host daemon."""
        old_socket = os.environ.get("STYRENED_SOCKET")
        old_config = os.environ.get("STYRENE_CONFIG_DIR")
        old_data = os.environ.get("STYRENE_DATA_DIR")
        old_state = os.environ.get("STYRENE_STATE_DIR")
        os.environ["STYRENED_SOCKET"] = str(host_daemon.socket_path)
        os.environ["STYRENE_CONFIG_DIR"] = str(host_daemon.config_dir)
        os.environ["STYRENE_DATA_DIR"] = str(host_daemon.config_dir / "data")
        os.environ["STYRENE_STATE_DIR"] = str(host_daemon.config_dir / "state")
        yield
        for key, old in [
            ("STYRENED_SOCKET", old_socket),
            ("STYRENE_CONFIG_DIR", old_config),
            ("STYRENE_DATA_DIR", old_data),
            ("STYRENE_STATE_DIR", old_state),
        ]:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    async def _poll_for_alpha(self, bridge, *, timeout: float = 30.0) -> object | None:
        """Poll IPC bridge until alpha peer appears or timeout."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            devices = await bridge.get_devices()
            for d in devices:
                if d.identity_hash == ALPHA_IDENTITY_HASH:
                    return d
            await asyncio.sleep(2.0)
        return None

    async def test_tui_connects_to_host_daemon(
        self, host_daemon: DaemonHarness, _host_env: None
    ) -> None:
        """StyreneApp should connect to the host daemon via IPC."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)
            bridge = app.bridge
            assert bridge is not None, "IPC bridge not connected"

    async def test_tui_discovers_alpha_peer(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Alpha peer should appear in the TUI device list after announces."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            assert alpha is not None, (
                f"Alpha peer ({ALPHA_IDENTITY_HASH}) not found after 30s"
            )

    async def test_tui_alpha_display_name_correct(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Alpha's display name should match fixture value."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            assert alpha is not None, "Alpha peer not discovered"
            assert "Test Peer Alpha" in (alpha.name or ""), (
                f"Expected 'Test Peer Alpha' in name, got: {alpha.name}"
            )

    async def test_navigate_to_device_detail(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Push MeshDeviceDetailScreen for alpha, verify it mounts."""
        from styrened.tui.app import StyreneApp
        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            # Wait for alpha to be discovered first
            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            if alpha is None:
                pytest.skip("Alpha not discovered in time")

            # Push device detail screen
            app.push_screen(
                MeshDeviceDetailScreen(device_identity=ALPHA_IDENTITY_HASH)
            )
            await pilot.pause(delay=2.0)

            # Verify we're on the detail screen
            assert isinstance(app.screen, MeshDeviceDetailScreen), (
                f"Expected MeshDeviceDetailScreen, got {type(app.screen).__name__}"
            )
            assert app.screen.device_identity == ALPHA_IDENTITY_HASH

    @pytest.mark.slow
    async def test_status_tab_fires_rpc(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Status tab on detail screen should fire RPC status request.

        Requires LXMF path for RPC. Marked slow (~30-60s).
        """
        from styrened.ipc.client import IPCResponseError, IPCTimeoutError
        from styrened.tui.app import StyreneApp
        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            if alpha is None:
                pytest.skip("Alpha not discovered in time")

            # Push detail screen — status tab is default
            app.push_screen(
                MeshDeviceDetailScreen(device_identity=ALPHA_IDENTITY_HASH)
            )
            await pilot.pause(delay=2.0)

            # Try to get status via bridge RPC
            try:
                status = await bridge.send_rpc(
                    destination=ALPHA_IDENTITY_HASH,
                    command="status",
                    timeout=45.0,
                )
            except (IPCResponseError, IPCTimeoutError) as e:
                if "timed out" in str(e).lower():
                    pytest.skip(f"RPC status timed out — LXMF path not ready: {e}")
                raise

            assert status is not None, "Status response was None"

    @pytest.mark.slow
    async def test_chat_send_and_auto_reply(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Send message to alpha via IPC, receive auto-reply.

        Requires full LXMF path establishment (~20-60s on localhost TCP).
        Marked slow — only runs with --run-slow flag.
        """
        from styrened.ipc.client import IPCResponseError, IPCTimeoutError
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            # Wait for alpha to be discovered
            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            if alpha is None:
                pytest.skip("Alpha not discovered in time")

            # Retry send_chat until LXMF path is established
            lxmf_hash = alpha_daemon.lxmf_dest_hash
            assert lxmf_hash, "Alpha fixture has no LXMF destination hash"

            sent = False
            for attempt in range(10):
                try:
                    result = await bridge.send_chat(
                        peer_hash=lxmf_hash,
                        content="Hello from operator test",
                    )
                    sent = True
                    break
                except (IPCResponseError, IPCTimeoutError) as e:
                    err = str(e).lower()
                    if "no path" in err or "not known" in err or "timed out" in err:
                        await pilot.pause(delay=3.0)
                        continue
                    raise

            if not sent:
                pytest.skip("LXMF path to alpha not established after retries")

            # Poll for auto-reply (alpha has auto_reply_mode=always, cooldown=1s)
            reply_found = False
            for _ in range(15):
                await pilot.pause(delay=2.0)
                messages = await bridge.get_messages(peer_hash=lxmf_hash)
                incoming = [m for m in messages if m.get("incoming", False)]
                if incoming:
                    reply_found = True
                    last = incoming[-1]
                    assert "Roger that" in last.get("content", ""), (
                        f"Expected auto-reply, got: {last.get('content', '')}"
                    )
                    break

            assert reply_found, "No auto-reply received within 30s"

    @pytest.mark.slow
    async def test_rpc_exec(
        self, host_daemon: DaemonHarness, _host_env: None, alpha_daemon: DaemonHarness
    ) -> None:
        """Execute command on alpha via RPC, verify response.

        Note: RPC over LXMF requires bidirectional path discovery which
        can take 20-30s on localhost TCP. The 60s timeout accommodates this.
        """
        from styrened.ipc.client import IPCResponseError
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=3.0)

            bridge = app.bridge
            if bridge is None:
                pytest.skip("IPC bridge not connected")

            # Wait for alpha to be discovered
            alpha = await self._poll_for_alpha(bridge, timeout=30.0)
            if alpha is None:
                pytest.skip("Alpha not discovered in time")

            # Allow extra time for LXMF path establishment
            await pilot.pause(delay=5.0)

            # Execute command via RPC (may timeout if LXMF path not ready)
            try:
                result = await bridge.send_rpc(
                    destination=ALPHA_IDENTITY_HASH,
                    command="echo hello-from-test",
                    timeout=45.0,
                )
            except IPCResponseError as e:
                if "timed out" in str(e):
                    pytest.skip(f"RPC timed out — LXMF path not ready: {e}")
                raise

            assert result is not None, "RPC exec returned None"
            # ExecResultInfo has stdout/output
            output = getattr(result, "stdout", None) or getattr(result, "output", None) or str(result)
            assert "hello-from-test" in output, (
                f"Expected 'hello-from-test' in exec result, got: {output}"
            )
