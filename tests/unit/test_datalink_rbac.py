"""Tests for RBAC-gated DirectLink request handlers (Phase 3).

TDD: These tests are written BEFORE the implementation.
They define the expected behavior for ALLOW_LIST enforcement
on the 5 DirectLink request handlers.

Capability mapping:
    /ping      → datalink.ping       (PEER+)
    /meta      → datalink.meta       (PEER+)
    /info      → datalink.info       (PEER+)
    /status    → datalink.status     (PEER+, app-layer gates full data to MONITOR+)
    /speedtest → datalink.speedtest  (MONITOR+)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.rbac import (
    Capability,
    RBACPolicy,
    ROLE_CAPABILITIES,
    Role,
    RosterEntry,
)


# ---------------------------------------------------------------------------
# 1. Capability model: new capabilities exist at correct tiers
# ---------------------------------------------------------------------------


class TestDirectLinkCapabilitiesExist:
    """New datalink capabilities exist and are at the right role tier."""

    def test_datalink_ping_exists(self):
        assert hasattr(Capability, "DATALINK_PING")
        assert Capability.DATALINK_PING == "datalink.ping"

    def test_datalink_meta_exists(self):
        assert hasattr(Capability, "DATALINK_META")
        assert Capability.DATALINK_META == "datalink.meta"

    def test_datalink_info_exists(self):
        assert hasattr(Capability, "DATALINK_INFO")
        assert Capability.DATALINK_INFO == "datalink.info"

    def test_ping_in_peer_tier(self):
        assert Capability.DATALINK_PING in ROLE_CAPABILITIES[Role.PEER]

    def test_meta_in_peer_tier(self):
        assert Capability.DATALINK_META in ROLE_CAPABILITIES[Role.PEER]

    def test_info_in_peer_tier(self):
        assert Capability.DATALINK_INFO in ROLE_CAPABILITIES[Role.PEER]

    def test_status_in_peer_tier(self):
        """DATALINK_STATUS moved from MONITOR to PEER (link-level access)."""
        assert Capability.DATALINK_STATUS in ROLE_CAPABILITIES[Role.PEER]

    def test_speedtest_in_monitor_tier(self):
        """DATALINK_SPEEDTEST stays at MONITOR."""
        assert Capability.DATALINK_SPEEDTEST in ROLE_CAPABILITIES[Role.MONITOR]
        assert Capability.DATALINK_SPEEDTEST not in ROLE_CAPABILITIES[Role.PEER]

    def test_new_caps_in_registry(self):
        """All new capabilities appear in Capability.ALL."""
        for cap in [Capability.DATALINK_PING, Capability.DATALINK_META, Capability.DATALINK_INFO]:
            assert cap in Capability.ALL

    def test_cumulative_monitor_has_all_peer_datalink_caps(self):
        """MONITOR role inherits all PEER datalink caps."""
        for cap in [
            Capability.DATALINK_PING,
            Capability.DATALINK_META,
            Capability.DATALINK_INFO,
            Capability.DATALINK_STATUS,
        ]:
            assert cap in ROLE_CAPABILITIES[Role.MONITOR]

    def test_peer_cannot_speedtest(self):
        """PEER does not have speedtest capability."""
        policy = RBACPolicy(default_role=Role.PEER)
        assert not policy.has_capability("unknown_peer", Capability.DATALINK_SPEEDTEST)

    def test_monitor_can_speedtest(self):
        """MONITOR has speedtest capability."""
        policy = RBACPolicy(default_role=Role.PEER)
        policy.roster["mon123"] = RosterEntry(identity_hash="mon123", role=Role.MONITOR)
        assert policy.has_capability("mon123", Capability.DATALINK_SPEEDTEST)


# ---------------------------------------------------------------------------
# 2. Handler capability mapping dict
# ---------------------------------------------------------------------------


class TestHandlerCapabilityMapping:
    """A HANDLER_CAPABILITY dict maps each path to its required capability."""

    def test_mapping_exists(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert isinstance(DATALINK_HANDLER_CAPABILITY, dict)

    def test_ping_mapped(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert DATALINK_HANDLER_CAPABILITY["/ping"] == Capability.DATALINK_PING

    def test_meta_mapped(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert DATALINK_HANDLER_CAPABILITY["/meta"] == Capability.DATALINK_META

    def test_info_mapped(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert DATALINK_HANDLER_CAPABILITY["/info"] == Capability.DATALINK_INFO

    def test_status_mapped(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert DATALINK_HANDLER_CAPABILITY["/status"] == Capability.DATALINK_STATUS

    def test_speedtest_mapped(self):
        from styrened.daemon import DATALINK_HANDLER_CAPABILITY
        assert DATALINK_HANDLER_CAPABILITY["/speedtest"] == Capability.DATALINK_SPEEDTEST


# ---------------------------------------------------------------------------
# 3. _datalink_allow_mode: selects ALLOW_ALL vs ALLOW_LIST per capability
# ---------------------------------------------------------------------------


class TestDatalinkAllowMode:
    """_datalink_allow_mode returns (allow_flag, allowed_list) per capability."""

    def _make_daemon(self, rbac_policy=None):
        from styrened.daemon import StyreneDaemon
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = rbac_policy
        daemon._datalink_allow_mode = StyreneDaemon._datalink_allow_mode.__get__(daemon)
        return daemon

    def test_default_peer_returns_allow_all_for_peer_cap(self):
        """default_role=PEER grants datalink.ping → ALLOW_ALL."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)
        allow, allowed_list = daemon._datalink_allow_mode(Capability.DATALINK_PING)
        assert allow == 0x00  # ALLOW_ALL

    def test_default_peer_returns_allow_list_for_monitor_cap(self):
        """default_role=PEER does NOT grant datalink.speedtest → ALLOW_LIST."""
        policy = RBACPolicy(
            default_role=Role.PEER,
            roster={"aa" * 16: RosterEntry(identity_hash="aa" * 16, role=Role.MONITOR)},
        )
        daemon = self._make_daemon(rbac_policy=policy)
        allow, allowed_list = daemon._datalink_allow_mode(Capability.DATALINK_SPEEDTEST)
        assert allow == 0x01  # ALLOW_LIST
        assert isinstance(allowed_list, list)
        assert len(allowed_list) == 1

    def test_default_none_returns_allow_list_for_peer_cap(self):
        """default_role=NONE does NOT grant datalink.ping → ALLOW_LIST with rostered peers."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"bb" * 16: RosterEntry(identity_hash="bb" * 16, role=Role.PEER)},
        )
        daemon = self._make_daemon(rbac_policy=policy)
        allow, allowed_list = daemon._datalink_allow_mode(Capability.DATALINK_PING)
        assert allow == 0x01  # ALLOW_LIST
        assert len(allowed_list) == 1

    def test_allow_list_excludes_blocked(self):
        """Blocked identities not in the allow list even if rostered."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={
                "cc" * 16: RosterEntry(identity_hash="cc" * 16, role=Role.PEER),
                "dd" * 16: RosterEntry(identity_hash="dd" * 16, role=Role.BLOCKED),
            },
        )
        daemon = self._make_daemon(rbac_policy=policy)
        allow, allowed_list = daemon._datalink_allow_mode(Capability.DATALINK_PING)
        assert allow == 0x01
        assert len(allowed_list) == 1  # only "good"


# ---------------------------------------------------------------------------
# 4. Handler-level RBAC gates (app-layer, defense in depth)
# ---------------------------------------------------------------------------


class TestHandlerAppLayerRBAC:
    """Handlers enforce RBAC at app-layer even when ALLOW_LIST lets a request through.

    This is defense-in-depth: if roster changes between handler registration
    and request arrival, the app-layer gate catches it.
    """

    def _make_daemon(self, rbac_policy=None, info_respond=True):
        """Create a minimal daemon mock with real handler methods bound."""
        from styrened.daemon import StyreneDaemon

        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = rbac_policy
        daemon.config.discovery = MagicMock()
        daemon.config.discovery.info_respond = info_respond

        # Bind real handler methods
        daemon._serve_datalink_ping = StyreneDaemon._serve_datalink_ping.__get__(daemon)
        daemon._serve_datalink_meta = StyreneDaemon._serve_datalink_meta.__get__(daemon)
        daemon._serve_datalink_info = StyreneDaemon._serve_datalink_info.__get__(daemon)
        daemon._serve_datalink_status = StyreneDaemon._serve_datalink_status.__get__(daemon)
        daemon._serve_datalink_speedtest = StyreneDaemon._serve_datalink_speedtest.__get__(daemon)
        daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
        daemon._datalink_rbac_role = StyreneDaemon._datalink_rbac_role.__get__(daemon)

        # Rate limiter always passes
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True

        return daemon

    def _identity(self, hex_hash: str):
        """Create a mock RNS identity with the given hex hash."""
        ident = MagicMock()
        ident.hash = bytes.fromhex(hex_hash)
        return ident

    # --- /ping ---

    def test_ping_blocked_returns_empty(self):
        """BLOCKED identity gets empty response from /ping."""
        policy = RBACPolicy(default_role=Role.PEER, blocked=["dead"])
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_ping(
            "/ping", None, None, None, self._identity("deadbeef" + "0" * 24), None
        )
        data = json.loads(result)
        assert data == {} or "pong" not in data

    def test_ping_peer_succeeds(self):
        """PEER identity gets pong from /ping."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_ping(
            "/ping", None, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        assert data.get("pong") is True

    # --- /meta ---

    def test_meta_blocked_returns_empty(self):
        """BLOCKED identity gets empty response from /meta."""
        policy = RBACPolicy(default_role=Role.PEER, blocked=["dead"])
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_meta(
            "/meta", None, None, None, self._identity("deadbeef" + "0" * 24), None
        )
        data = json.loads(result)
        assert data == {}

    def test_meta_peer_gets_data(self):
        """PEER identity gets meta data."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)
        daemon._rpc_server = MagicMock()
        daemon._rpc_server._gather_meta.return_value = {"styrene_version": "0.14.6"}

        result = daemon._serve_datalink_meta(
            "/meta", None, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        assert "styrene_version" in data

    # --- /info ---

    def test_info_blocked_returns_empty(self):
        """BLOCKED identity gets empty response from /info."""
        policy = RBACPolicy(default_role=Role.PEER, blocked=["dead"])
        daemon = self._make_daemon(rbac_policy=policy, info_respond=True)

        result = daemon._serve_datalink_info(
            "/info", None, None, None, self._identity("deadbeef" + "0" * 24), None
        )
        data = json.loads(result)
        assert data == {}

    def test_info_peer_with_info_respond_gets_data(self):
        """PEER identity gets info when info_respond=True."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy, info_respond=True)
        daemon._rpc_server = MagicMock()
        daemon._rpc_server._gather_info.return_value = {"name": "test-node"}

        result = daemon._serve_datalink_info(
            "/info", None, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        assert data.get("name") == "test-node"

    def test_info_peer_without_info_respond_gets_empty(self):
        """PEER identity gets empty when info_respond=False (config gate)."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy, info_respond=False)

        result = daemon._serve_datalink_info(
            "/info", None, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        assert data == {}

    # --- /speedtest ---

    def test_speedtest_peer_denied(self):
        """PEER identity is denied /speedtest (requires MONITOR+)."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_speedtest(
            "/speedtest", b"x" * 100, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        # Should indicate denial, not return bytes_received
        assert "bytes_received" not in data

    def test_speedtest_monitor_allowed(self):
        """MONITOR identity is allowed /speedtest."""
        policy = RBACPolicy(
            default_role=Role.PEER,
            roster={"abcd" * 8: RosterEntry(identity_hash="abcd" * 8, role=Role.MONITOR)},
        )
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_speedtest(
            "/speedtest", b"x" * 100, None, None, self._identity("abcd" * 8), None
        )
        data = json.loads(result)
        assert data.get("bytes_received") == 100

    # --- /status (already app-layer gated, verify BLOCKED is denied) ---

    def test_status_blocked_returns_empty(self):
        """BLOCKED identity gets empty from /status."""
        policy = RBACPolicy(default_role=Role.PEER, blocked=["dead"])
        daemon = self._make_daemon(rbac_policy=policy)

        result = daemon._serve_datalink_status(
            "/status", None, None, None, self._identity("deadbeef" + "0" * 24), None
        )
        data = json.loads(result)
        assert data == {}


# ---------------------------------------------------------------------------
# 5. Legacy mode: no RBAC → ALLOW_ALL, no app-layer RBAC gate
# ---------------------------------------------------------------------------


class TestDefaultRBACPolicy:
    """With default RBAC policy (PEER default_role), handlers work for all callers."""

    def _make_daemon(self):
        from styrened.daemon import StyreneDaemon
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = RBACPolicy(default_role=Role.PEER)
        daemon.config.discovery = MagicMock()
        daemon.config.discovery.info_respond = True

        daemon._serve_datalink_ping = StyreneDaemon._serve_datalink_ping.__get__(daemon)
        daemon._serve_datalink_meta = StyreneDaemon._serve_datalink_meta.__get__(daemon)
        daemon._serve_datalink_info = StyreneDaemon._serve_datalink_info.__get__(daemon)
        daemon._serve_datalink_speedtest = StyreneDaemon._serve_datalink_speedtest.__get__(daemon)
        daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
        daemon._datalink_rbac_role = StyreneDaemon._datalink_rbac_role.__get__(daemon)

        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True
        daemon._rpc_server = MagicMock()
        daemon._rpc_server._gather_meta.return_value = {"styrene_version": "test"}
        daemon._rpc_server._gather_info.return_value = {"name": "node"}

        return daemon

    def _identity(self, hex_hash: str):
        ident = MagicMock()
        ident.hash = bytes.fromhex(hex_hash)
        return ident

    def test_ping_works_with_default_rbac(self):
        daemon = self._make_daemon()
        result = json.loads(daemon._serve_datalink_ping(
            "/ping", None, None, None, self._identity("abcd" * 8), None
        ))
        assert result.get("pong") is True

    def test_meta_works_with_default_rbac(self):
        daemon = self._make_daemon()
        result = json.loads(daemon._serve_datalink_meta(
            "/meta", None, None, None, self._identity("abcd" * 8), None
        ))
        assert "styrene_version" in result

    def test_speedtest_denied_for_peer(self):
        """Default PEER role is below MONITOR — speedtest denied."""
        daemon = self._make_daemon()
        result = json.loads(daemon._serve_datalink_speedtest(
            "/speedtest", b"x" * 50, None, None, self._identity("abcd" * 8), None
        ))
        assert result.get("error") == "forbidden"

    def test_speedtest_works_for_monitor(self):
        """MONITOR role grants speedtest access."""
        from styrened.daemon import StyreneDaemon
        daemon = self._make_daemon()
        identity_hash = "abcd" * 8
        daemon.config.rbac = RBACPolicy(
            default_role=Role.MONITOR,
        )
        result = json.loads(daemon._serve_datalink_speedtest(
            "/speedtest", b"x" * 50, None, None, self._identity(identity_hash), None
        ))
        assert result.get("bytes_received") == 50


# ---------------------------------------------------------------------------
# 6. _setup_datalink_destination uses ALLOW_LIST when RBAC active
# ---------------------------------------------------------------------------


class TestSetupDatalinkDestination:
    """_setup_datalink_destination passes correct allow mode to RNS."""

    @patch("styrened.services.reticulum.get_operator_identity_object")
    @patch("RNS.Destination")
    def test_rbac_active_registers_with_allow_mode(self, mock_dest_cls, mock_identity):
        """When RBAC is active, handlers are registered with computed allow mode."""
        from styrened.daemon import StyreneDaemon

        mock_identity.return_value = MagicMock()
        mock_dest = MagicMock()
        mock_dest_cls.return_value = mock_dest

        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = RBACPolicy(default_role=Role.PEER)
        daemon._setup_datalink_destination = StyreneDaemon._setup_datalink_destination.__get__(daemon)
        daemon._datalink_allow_mode = StyreneDaemon._datalink_allow_mode.__get__(daemon)
        daemon._reregister_datalink_handlers = StyreneDaemon._reregister_datalink_handlers.__get__(daemon)

        daemon._setup_datalink_destination()

        # Should have registered 5 handlers
        assert mock_dest.register_request_handler.call_count == 6

        # Verify each call used the allow mode from _datalink_allow_mode
        calls = mock_dest.register_request_handler.call_args_list
        paths_registered = [c.args[0] for c in calls]
        assert "/ping" in paths_registered
        assert "/meta" in paths_registered
        assert "/status" in paths_registered
        assert "/speedtest" in paths_registered
        assert "/info" in paths_registered


# ---------------------------------------------------------------------------
# 7. Re-registration on roster change
# ---------------------------------------------------------------------------


class TestReregisterOnRosterChange:
    """Handlers are re-registered when the RBAC roster changes."""

    def test_reregister_method_exists(self):
        """StyreneDaemon has a _reregister_datalink_handlers method."""
        from styrened.daemon import StyreneDaemon
        assert hasattr(StyreneDaemon, "_reregister_datalink_handlers")

    @patch("RNS.Destination")
    def test_reregister_updates_allow_lists(self, mock_dest_cls):
        """After roster change, re-registration updates allow lists."""
        from styrened.daemon import StyreneDaemon

        daemon = MagicMock()
        policy = RBACPolicy(default_role=Role.NONE)
        daemon.config = MagicMock()
        daemon.config.rbac = policy
        daemon._datalink_destination = MagicMock()
        daemon._reregister_datalink_handlers = StyreneDaemon._reregister_datalink_handlers.__get__(daemon)
        daemon._datalink_allow_mode = StyreneDaemon._datalink_allow_mode.__get__(daemon)

        # Initially empty roster → all handlers ALLOW_LIST with empty lists
        daemon._reregister_datalink_handlers()

        # Add a peer to roster
        policy.add_entry(RosterEntry(identity_hash="a" * 32, role=Role.PEER))
        daemon._reregister_datalink_handlers()

        # Should have re-registered handlers (at least 5 calls per invocation)
        assert daemon._datalink_destination.register_request_handler.call_count >= 5
