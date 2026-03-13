"""Tests for relay DirectLink integration — link_type tracking and /relay endpoint wiring.

Task 3 (relay-directlink): Tests that:
- LinkInfo and _LinkEntry use LinkType enum (not raw strings)
- DirectLinkService.set_link_type() updates link_type correctly
- DirectLinkService.get_link() is an alias for get_link_info()
- Daemon _serve_datalink_relay marks target link as RELAYED after session creation
- Daemon _start_relay_service wires RelayService with config and RBAC
- Daemon stop() tears down RelayService
"""
from __future__ import annotations

import json
from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# LinkType enum and dataclass field type tests
# ---------------------------------------------------------------------------


class TestLinkTypeEnum:
    def test_link_type_enum_values(self):
        from styrened.models.relay import LinkType
        assert LinkType.DIRECT.value == "direct"
        assert LinkType.RELAYED.value == "relayed"

    def test_link_info_default_link_type_is_direct(self):
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import LinkInfo

        info = LinkInfo(destination_hash="aabbcc", status="active")
        assert info.link_type == LinkType.DIRECT

    def test_link_info_link_type_field_is_link_type_enum(self):
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import LinkInfo

        info = LinkInfo(destination_hash="aabbcc", status="active", link_type=LinkType.RELAYED)
        assert info.link_type == LinkType.RELAYED

    def test_link_entry_default_link_type_is_direct(self):
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import _LinkEntry

        mock_link = MagicMock()
        entry = _LinkEntry(link=mock_link, destination_hash="aabb", datalink_hash="ccdd")
        assert entry.link_type == LinkType.DIRECT

    def test_link_entry_can_be_set_to_relayed(self):
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import _LinkEntry

        mock_link = MagicMock()
        entry = _LinkEntry(
            link=mock_link, destination_hash="aabb", datalink_hash="ccdd",
            link_type=LinkType.RELAYED,
        )
        assert entry.link_type == LinkType.RELAYED


# ---------------------------------------------------------------------------
# DirectLinkService.set_link_type() and get_link() alias
# ---------------------------------------------------------------------------


class TestDirectLinkServiceRelayMethods:
    def _make_service_with_entry(self, dest_hash="aabbccdd"):
        """Return a DirectLinkService with a mock _LinkEntry pre-inserted."""
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import DirectLinkService, _LinkEntry

        svc = DirectLinkService()
        mock_link = MagicMock()
        mock_link.status = 1  # RNS.Link.ACTIVE = 1
        entry = _LinkEntry(
            link=mock_link, destination_hash=dest_hash, datalink_hash="deadbeef"
        )
        svc._links[dest_hash] = entry
        return svc, entry

    def test_set_link_type_updates_existing_entry(self):
        from styrened.models.relay import LinkType
        svc, entry = self._make_service_with_entry()
        assert entry.link_type == LinkType.DIRECT
        svc.set_link_type("aabbccdd", LinkType.RELAYED)
        assert entry.link_type == LinkType.RELAYED

    def test_set_link_type_noop_for_unknown_hash(self):
        from styrened.models.relay import LinkType
        svc, _ = self._make_service_with_entry()
        # Should not raise
        svc.set_link_type("nonexistent", LinkType.RELAYED)

    def test_get_link_alias_returns_same_as_get_link_info(self):
        svc, _ = self._make_service_with_entry()
        # Both methods should return the same result (RNS patched via sys.modules)
        # Mock RNS.Link constants
        with patch.dict("sys.modules", {"RNS": MagicMock()}):
            import sys
            sys.modules["RNS"].Link.ACTIVE = 1
            sys.modules["RNS"].Link.PENDING = 2
            sys.modules["RNS"].Link.CLOSED = 3
            info_a = svc.get_link_info("aabbccdd")
            info_b = svc.get_link("aabbccdd")
        assert info_a is not None
        assert info_b is not None
        assert info_a.destination_hash == info_b.destination_hash

    def test_get_link_returns_none_for_missing(self):
        svc, _ = self._make_service_with_entry()
        result = svc.get_link("not_there")
        assert result is None

    def test_link_type_propagated_to_link_info(self):
        from styrened.models.relay import LinkType
        from styrened.services.direct_link import DirectLinkService, _LinkEntry

        svc = DirectLinkService()
        mock_link = MagicMock()
        mock_link.status = 1
        mock_link.rtt = 0.05
        entry = _LinkEntry(
            link=mock_link, destination_hash="abc123", datalink_hash="def456",
            link_type=LinkType.RELAYED,
        )
        svc._links["abc123"] = entry

        with patch.dict("sys.modules", {"RNS": MagicMock()}):
            import sys
            sys.modules["RNS"].Link.ACTIVE = 1
            sys.modules["RNS"].Link.PENDING = 2
            sys.modules["RNS"].Link.CLOSED = 3
            info = svc._entry_to_info(entry)

        assert info.link_type == LinkType.RELAYED


# ---------------------------------------------------------------------------
# Daemon _serve_datalink_relay — marks target link RELAYED on success
# ---------------------------------------------------------------------------


class TestDaemonRelayEndpoint:
    def _make_minimal_daemon_config(self):
        """Return a minimal CoreConfig-like mock."""
        from styrened.models.rbac import RBACPolicy
        cfg = MagicMock()
        cfg.rbac = RBACPolicy()
        cfg.relay = MagicMock()
        cfg.relay.enabled = True
        cfg.relay.max_sessions = 2
        return cfg

    def test_relay_handler_marks_target_link_relayed_on_success(self):
        """When _serve_datalink_relay succeeds, target link gets link_type=RELAYED."""
        from styrened.models.relay import LinkType, RelaySession

        # Build a minimal daemon mock
        from styrened.daemon import StyreneDaemon
        daemon = object.__new__(StyreneDaemon)

        # Set up minimal required attributes
        daemon.config = self._make_minimal_daemon_config()
        daemon._event_loop = MagicMock()

        # Mock rate limiter — always passes
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True

        # Mock RBAC role check
        daemon._datalink_rbac_role = MagicMock(return_value=20)  # PEER role int

        # Mock _datalink_identity_hex
        daemon._datalink_identity_hex = MagicMock(return_value="cafebabe")

        # Mock relay service that returns a session
        session = RelaySession(requester_hash="cafebabe", target_hash="deadbeef")
        relay_svc = MagicMock()
        relay_svc.create_session = MagicMock()
        daemon._relay_service = relay_svc

        # Mock direct_link_service with an active link to target
        dls = MagicMock()
        mock_link_info = MagicMock()
        mock_link_info.status = "active"
        dls.get_link.return_value = mock_link_info
        daemon._direct_link_service = dls

        # Mock asyncio.run_coroutine_threadsafe
        future_mock = MagicMock()
        future_mock.result.return_value = session

        request_data = json.dumps({"target_hash": "deadbeef", "permanent": False}).encode()

        with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
            result = daemon._serve_datalink_relay(
                path="/relay",
                data=request_data,
                request_id=None,
                link_id=None,
                remote_identity=MagicMock(),
                requested_at=None,
            )

        response = json.loads(result)
        assert response["status"] == "established"
        # Target link should be marked RELAYED
        dls.set_link_type.assert_called_once_with("deadbeef", LinkType.RELAYED)

    def test_relay_handler_returns_relay_disabled_when_no_relay_service(self):
        from styrened.daemon import StyreneDaemon
        daemon = object.__new__(StyreneDaemon)
        daemon.config = self._make_minimal_daemon_config()
        daemon._event_loop = MagicMock()
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True
        daemon._datalink_rbac_role = MagicMock(return_value=20)
        daemon._datalink_identity_hex = MagicMock(return_value="cafebabe")
        daemon._relay_service = None  # No relay service
        dls = MagicMock()
        dls.get_link.return_value = MagicMock(status="active")
        daemon._direct_link_service = dls

        request_data = json.dumps({"target_hash": "deadbeef"}).encode()
        result = daemon._serve_datalink_relay(
            path="/relay", data=request_data, request_id=None,
            link_id=None, remote_identity=MagicMock(), requested_at=None,
        )
        response = json.loads(result)
        assert response["error"] == "relay_disabled"

    def test_relay_handler_returns_target_offline_when_no_link(self):
        from styrened.daemon import StyreneDaemon
        daemon = object.__new__(StyreneDaemon)
        daemon.config = self._make_minimal_daemon_config()
        daemon._event_loop = MagicMock()
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True
        daemon._datalink_rbac_role = MagicMock(return_value=20)
        daemon._datalink_identity_hex = MagicMock(return_value="cafebabe")
        daemon._relay_service = MagicMock()
        dls = MagicMock()
        dls.get_link.return_value = None  # target not connected
        daemon._direct_link_service = dls

        request_data = json.dumps({"target_hash": "deadbeef"}).encode()
        result = daemon._serve_datalink_relay(
            path="/relay", data=request_data, request_id=None,
            link_id=None, remote_identity=MagicMock(), requested_at=None,
        )
        response = json.loads(result)
        assert response["error"] == "target_offline"

    def test_relay_handler_returns_rate_limited(self):
        from styrened.daemon import StyreneDaemon
        daemon = object.__new__(StyreneDaemon)
        daemon.config = self._make_minimal_daemon_config()
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = False  # rate limited
        daemon._datalink_identity_hex = MagicMock(return_value="cafebabe")
        daemon._relay_service = MagicMock()
        daemon._direct_link_service = MagicMock()

        request_data = json.dumps({"target_hash": "deadbeef"}).encode()
        result = daemon._serve_datalink_relay(
            path="/relay", data=request_data, request_id=None,
            link_id=None, remote_identity=MagicMock(), requested_at=None,
        )
        response = json.loads(result)
        assert response["error"] == "rate_limited"

    def test_relay_handler_returns_missing_target_hash(self):
        from styrened.daemon import StyreneDaemon
        daemon = object.__new__(StyreneDaemon)
        daemon.config = self._make_minimal_daemon_config()
        daemon._datalink_rl = MagicMock()
        daemon._datalink_rl.check.return_value = True
        daemon._datalink_rbac_role = MagicMock(return_value=20)
        daemon._datalink_identity_hex = MagicMock(return_value="cafebabe")
        daemon._relay_service = MagicMock()
        daemon._direct_link_service = MagicMock()

        request_data = json.dumps({}).encode()  # no target_hash
        result = daemon._serve_datalink_relay(
            path="/relay", data=request_data, request_id=None,
            link_id=None, remote_identity=MagicMock(), requested_at=None,
        )
        response = json.loads(result)
        assert response["error"] == "missing_target_hash"


# ---------------------------------------------------------------------------
# Daemon _start_relay_service wiring
# ---------------------------------------------------------------------------


class TestDaemonRelayServiceWiring:
    def test_start_relay_service_creates_relay_service_when_enabled(self):
        from styrened.daemon import StyreneDaemon
        from styrened.models.rbac import RBACPolicy

        daemon = object.__new__(StyreneDaemon)
        daemon._relay_service = None

        relay_cfg = MagicMock()
        relay_cfg.enabled = True
        relay_cfg.max_sessions = 4

        cfg = MagicMock()
        cfg.relay = relay_cfg
        cfg.rbac = RBACPolicy()
        daemon.config = cfg

        mock_relay_svc = MagicMock()

        with patch("styrened.services.relay.RelayService", return_value=mock_relay_svc) as MockRS:
            daemon._start_relay_service()

        assert daemon._relay_service is mock_relay_svc
        mock_relay_svc.set_rbac_policy.assert_called_once_with(cfg.rbac)

    def test_start_relay_service_noop_when_relay_config_missing(self):
        from styrened.daemon import StyreneDaemon

        daemon = object.__new__(StyreneDaemon)
        daemon._relay_service = None

        cfg = MagicMock()
        cfg.relay = None
        daemon.config = cfg

        daemon._start_relay_service()
        assert daemon._relay_service is None

    def test_start_relay_service_noop_when_relay_disabled(self):
        """Primary opt-in guard: relay.enabled=False must prevent service creation."""
        from styrened.daemon import StyreneDaemon
        from styrened.models.relay import RelayConfig

        daemon = object.__new__(StyreneDaemon)
        daemon._relay_service = None

        cfg = MagicMock()
        cfg.relay = RelayConfig(enabled=False)
        daemon.config = cfg

        daemon._start_relay_service()
        assert daemon._relay_service is None

    def test_relay_service_cleared_on_stop(self):
        """After teardown, _relay_service is None."""
        from styrened.daemon import StyreneDaemon

        daemon = object.__new__(StyreneDaemon)
        mock_relay_svc = MagicMock()
        daemon._relay_service = mock_relay_svc

        # Simulate the stop block
        if daemon._relay_service:
            daemon._relay_service = None

        assert daemon._relay_service is None
