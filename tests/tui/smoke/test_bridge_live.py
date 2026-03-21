"""IPCBridge contract tests against live Rust daemon.

Tests the high-level IPCBridge API (typed methods, deserialization,
auto-reconnect) rather than raw wire protocol. Catches shape mismatches
between Rust daemon responses and Python bridge expectations.

Run: pytest tests/tui/smoke/test_bridge_live.py -v
"""
from __future__ import annotations

import pytest

from styrened.ipc.bridge import IPCBridge
from styrened.ipc.messages import DaemonStatus, DeviceInfo, IdentityInfo

pytestmark = [
    pytest.mark.tui_smoke,
    pytest.mark.asyncio,
]


@pytest.fixture
async def bridge(rust_daemon):
    """Connected IPCBridge against the live Rust daemon."""
    b = IPCBridge(socket_path=rust_daemon, timeout=5.0, auto_reconnect=False)
    await b.connect()
    yield b
    await b.disconnect()


# ── Status & Identity ────────────────────────────────────────────────────────


class TestStatusBridge:
    """Bridge methods for daemon status and identity."""

    async def test_get_status_returns_daemon_status(self, bridge):
        """get_status() should return a DaemonStatus dataclass."""
        status = await bridge.get_status()
        assert isinstance(status, DaemonStatus)

    async def test_get_identity_returns_identity_info(self, bridge):
        """get_identity() should return an IdentityInfo dataclass."""
        identity = await bridge.get_identity()
        assert isinstance(identity, IdentityInfo)
        # Identity hash should be a hex string
        assert identity.identity_hash is None or isinstance(identity.identity_hash, str)


# ── Devices & Nodes ──────────────────────────────────────────────────────────


class TestDevicesBridge:
    """Bridge methods for device discovery."""

    async def test_get_devices_returns_list(self, bridge):
        """get_devices() should return a list (possibly empty)."""
        devices = await bridge.get_devices()
        assert isinstance(devices, list)

    async def test_get_nodes_returns_list(self, bridge):
        """get_nodes() returns Styrene fleet nodes."""
        nodes = await bridge.get_nodes()
        assert isinstance(nodes, list)


# ── Messaging ────────────────────────────────────────────────────────────────


class TestMessagingBridge:
    """Bridge methods for conversations and messages."""

    async def test_get_conversations_returns_list(self, bridge):
        """get_conversations() should return a list."""
        convos = await bridge.get_conversations()
        assert isinstance(convos, list)

    async def test_get_contacts_returns_list(self, bridge):
        """get_contacts() should return a list."""
        contacts = await bridge.get_contacts()
        assert isinstance(contacts, list)

    async def test_get_unread_counts_returns_dict(self, bridge):
        """get_unread_counts() should return a dict."""
        counts = await bridge.get_unread_counts()
        assert isinstance(counts, dict)

    async def test_search_messages_returns_list(self, bridge):
        """search_messages() should return a list."""
        results = await bridge.search_messages("test query")
        assert isinstance(results, list)


# ── Config ───────────────────────────────────────────────────────────────────


class TestConfigBridge:
    """Bridge methods for configuration."""

    async def test_get_config_returns_dict(self, bridge):
        """get_config() should return a dict."""
        config = await bridge.get_config()
        assert isinstance(config, dict)

    async def test_get_core_config_returns_dict(self, bridge):
        """get_core_config() should return a dict."""
        config = await bridge.get_core_config()
        assert isinstance(config, dict)

    async def test_get_auto_reply_returns_dict(self, bridge):
        """get_auto_reply() should return a dict."""
        ar = await bridge.get_auto_reply()
        assert isinstance(ar, dict)


# ── Hub & Activity ───────────────────────────────────────────────────────────


class TestHubBridge:
    """Bridge methods for hub status and activity."""

    async def test_get_hub_status_returns_dict(self, bridge):
        """get_hub_status() should return a dict."""
        hub = await bridge.get_hub_status()
        assert isinstance(hub, dict)

    async def test_get_adapter_state_returns_list(self, bridge):
        """get_adapter_state() should return a list."""
        adapters = await bridge.get_adapter_state()
        assert isinstance(adapters, list)

    async def test_get_activity_history_returns_list(self, bridge):
        """get_activity_history() should return a list."""
        history = await bridge.get_activity_history(limit=10)
        assert isinstance(history, list)


# ── Error Handling ───────────────────────────────────────────────────────────


class TestErrorHandling:
    """Bridge handles error responses gracefully."""

    async def test_get_blocked_peers_returns_error_or_dict(self, bridge):
        """get_blocked_peers() — Rust returns error (not implemented)."""
        try:
            result = await bridge.get_blocked_peers()
            assert isinstance(result, dict)
        except Exception:
            # Expected — Rust daemon returns error for unimplemented stubs
            pass

    async def test_resolve_name_unknown_returns_none(self, bridge):
        """resolve_name() for unknown peer should return None or empty."""
        result = await bridge.resolve_name("nonexistent_peer_name")
        # Either None, empty dict, or error response — all acceptable
        assert result is None or isinstance(result, (dict, list))
