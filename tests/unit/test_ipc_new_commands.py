"""Unit tests for the 5 new IPC commands.

Tests: GET_NODES, GET_CORE_CONFIG, SAVE_CORE_CONFIG, GET_HUB_STATUS, GET_UNREAD_COUNTS.
Each handler is tested in isolation with mocked daemon services.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from styrened.ipc.handlers import IPCHandlers
from styrened.ipc.messages import (
    ErrorResponse,
    GetCoreConfigRequest,
    GetHubStatusRequest,
    GetNodesRequest,
    GetUnreadCountsRequest,
    ResultResponse,
    SaveCoreConfigRequest,
    create_request,
)
from styrened.ipc.protocol import IPCMessageType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeMeshDevice:
    """Minimal MeshDevice stand-in for handler tests."""

    def __init__(
        self,
        destination_hash="aabb",
        identity_hash="ccdd",
        name="test-node",
        device_type=None,
        status=None,
        is_styrene_node=True,
        lxmf_destination_hash=None,
        last_announce=0.0,
        announce_count=1,
        short_name=None,
        system_fingerprint=None,
    ):
        self.destination_hash = destination_hash
        self.identity_hash = identity_hash
        self.name = name
        self.device_type = device_type or MagicMock(value="styrene_node")
        self.status = status or MagicMock(value="online")
        self.is_styrene_node = is_styrene_node
        self.lxmf_destination_hash = lxmf_destination_hash
        self.last_announce = last_announce
        self.announce_count = announce_count
        self.short_name = short_name
        self.system_fingerprint = system_fingerprint


class FakeConversationService:
    """Minimal conversation service with unread counts."""

    def __init__(self, unread_counts=None):
        self._unread_counts = unread_counts or {}
        self._initialized = True


class FakeDaemon:
    """Minimal daemon for handler tests."""

    def __init__(self, conversation_service=None):
        self._conversation_service = conversation_service
        self._rpc_client = None
        self._operator_destination = None
        self._lxmf_service = None
        self._start_time = time.time()
        self.config = MagicMock()
        self.lifecycle = MagicMock()
        self.lifecycle._initialized = True


# ---------------------------------------------------------------------------
# Protocol + Message round-trip
# ---------------------------------------------------------------------------


class TestProtocolMessageTypes:
    """Verify the 5 new message types exist and round-trip through create_request."""

    def test_get_nodes_message_type_exists(self):
        assert IPCMessageType.GET_NODES == 0x1E

    def test_get_core_config_message_type_exists(self):
        assert IPCMessageType.GET_CORE_CONFIG == 0x1F

    def test_save_core_config_message_type_exists(self):
        assert IPCMessageType.SAVE_CORE_CONFIG == 0x4D

    def test_get_hub_status_message_type_exists(self):
        assert IPCMessageType.GET_HUB_STATUS == 0x4E

    def test_get_unread_counts_message_type_exists(self):
        assert IPCMessageType.GET_UNREAD_COUNTS == 0x4F

    def test_get_nodes_request_roundtrip(self):
        req = GetNodesRequest(styrene_only=True)
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.GET_NODES
        assert payload["styrene_only"] is True
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, GetNodesRequest)
        assert reconstructed.styrene_only is True

    def test_get_nodes_request_roundtrip_default(self):
        req = GetNodesRequest()
        msg_type, payload = req.to_wire()
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, GetNodesRequest)
        assert reconstructed.styrene_only is False

    def test_get_core_config_request_roundtrip(self):
        req = GetCoreConfigRequest()
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.GET_CORE_CONFIG
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, GetCoreConfigRequest)

    def test_save_core_config_request_roundtrip(self):
        cfg = {"reticulum": {"mode": "standalone"}}
        req = SaveCoreConfigRequest(config_dict=cfg)
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.SAVE_CORE_CONFIG
        assert payload["config_dict"] == cfg
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, SaveCoreConfigRequest)
        assert reconstructed.config_dict == cfg

    def test_get_hub_status_request_roundtrip(self):
        req = GetHubStatusRequest()
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.GET_HUB_STATUS
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, GetHubStatusRequest)

    def test_get_unread_counts_request_roundtrip(self):
        req = GetUnreadCountsRequest()
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.GET_UNREAD_COUNTS
        reconstructed = create_request(msg_type, payload)
        assert isinstance(reconstructed, GetUnreadCountsRequest)


# ---------------------------------------------------------------------------
# Handler tests: handle_get_nodes
# ---------------------------------------------------------------------------


class TestHandleGetNodes:
    """Tests for handle_get_nodes handler."""

    @pytest.fixture
    def handlers(self):
        return IPCHandlers(daemon=None)

    @pytest.mark.asyncio
    async def test_returns_empty_when_node_store_is_none(self, handlers):
        with patch("styrened.services.node_store.get_node_store", return_value=None):
            resp = await handlers.handle_get_nodes(GetNodesRequest())
        assert isinstance(resp, ResultResponse)
        assert resp.data["nodes"] == []

    @pytest.mark.asyncio
    async def test_returns_all_nodes(self, handlers):
        node_store = MagicMock()
        node_store.get_all_nodes.return_value = [
            FakeMeshDevice(destination_hash="aa", identity_hash="11", name="n1"),
            FakeMeshDevice(destination_hash="bb", identity_hash="22", name="n2"),
        ]
        with patch("styrened.services.node_store.get_node_store", return_value=node_store):
            resp = await handlers.handle_get_nodes(GetNodesRequest(styrene_only=False))
        assert isinstance(resp, ResultResponse)
        assert len(resp.data["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_returns_styrene_only(self, handlers):
        node_store = MagicMock()
        node_store.get_styrene_nodes.return_value = [
            FakeMeshDevice(destination_hash="cc", identity_hash="33", name="styrene1"),
        ]
        with patch("styrened.services.node_store.get_node_store", return_value=node_store):
            resp = await handlers.handle_get_nodes(GetNodesRequest(styrene_only=True))
        assert isinstance(resp, ResultResponse)
        assert len(resp.data["nodes"]) == 1
        node_store.get_styrene_nodes.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_node_store_exception(self, handlers):
        with patch(
            "styrened.services.node_store.get_node_store",
            side_effect=RuntimeError("boom"),
        ):
            resp = await handlers.handle_get_nodes(GetNodesRequest())
        assert isinstance(resp, ErrorResponse)
        assert "boom" in resp.message


# ---------------------------------------------------------------------------
# Handler tests: handle_get_core_config
# ---------------------------------------------------------------------------


class TestHandleGetCoreConfig:
    """Tests for handle_get_core_config handler."""

    @pytest.fixture
    def handlers(self):
        return IPCHandlers(daemon=None)

    @pytest.mark.asyncio
    async def test_returns_serialized_config(self, handlers):
        fake_config = MagicMock()
        fake_dict = {"reticulum": {"mode": "standalone"}, "rpc": {"enabled": True}}
        with (
            patch(
                "styrened.services.config.load_core_config",
                return_value=fake_config,
            ),
            patch(
                "styrened.services.config._serialize_config",
                return_value=fake_dict,
            ),
        ):
            resp = await handlers.handle_get_core_config(GetCoreConfigRequest())
        assert isinstance(resp, ResultResponse)
        assert resp.data["config"] == fake_dict

    @pytest.mark.asyncio
    async def test_handles_config_load_error(self, handlers):
        with patch(
            "styrened.services.config.load_core_config",
            side_effect=RuntimeError("bad yaml"),
        ):
            resp = await handlers.handle_get_core_config(GetCoreConfigRequest())
        assert isinstance(resp, ErrorResponse)
        assert "bad yaml" in resp.message


# ---------------------------------------------------------------------------
# Handler tests: handle_save_core_config
# ---------------------------------------------------------------------------


class TestHandleSaveCoreConfig:
    """Tests for handle_save_core_config handler."""

    @pytest.fixture
    def handlers(self):
        return IPCHandlers(daemon=None)

    @pytest.mark.asyncio
    async def test_rejects_empty_config_dict(self, handlers):
        resp = await handlers.handle_save_core_config(SaveCoreConfigRequest(config_dict={}))
        assert isinstance(resp, ErrorResponse)
        assert "config_dict is required" in resp.message

    @pytest.mark.asyncio
    async def test_saves_config_successfully(self, handlers, tmp_path):
        config_dict = {"reticulum": {"mode": "standalone"}}
        fake_config = MagicMock()
        config_file = tmp_path / "config.yaml"

        with (
            patch(
                "styrened.services.config.load_core_config",
                return_value=fake_config,
            ),
            patch("styrened.services.config.save_core_config"),
            patch("styrened.paths.config_file", return_value=config_file),
        ):
            resp = await handlers.handle_save_core_config(
                SaveCoreConfigRequest(config_dict=config_dict)
            )

        assert isinstance(resp, ResultResponse)
        assert resp.data["saved"] is True

    @pytest.mark.asyncio
    async def test_handles_write_error(self, handlers):
        config_dict = {"reticulum": {"mode": "standalone"}}
        with patch(
            "styrened.paths.config_file",
            side_effect=RuntimeError("disk full"),
        ):
            resp = await handlers.handle_save_core_config(
                SaveCoreConfigRequest(config_dict=config_dict)
            )
        assert isinstance(resp, ErrorResponse)
        assert "disk full" in resp.message


# ---------------------------------------------------------------------------
# Handler tests: handle_get_hub_status
# ---------------------------------------------------------------------------


class TestHandleGetHubStatus:
    """Tests for handle_get_hub_status handler."""

    @pytest.fixture
    def handlers(self):
        return IPCHandlers(daemon=None)

    @pytest.mark.asyncio
    async def test_returns_connected_hub_status(self, handlers):
        hub = MagicMock()
        hub.is_connected = True
        hub.hub_address = "6fc8bf22aa293588c9bf8d7488102e95"
        hub.status.value = "connected"
        hub.hub_destination = MagicMock()
        hub.hub_destination.hexhash = "abcdef1234567890"

        with patch("styrened.services.hub_connection.get_hub_connection", return_value=hub):
            resp = await handlers.handle_get_hub_status(GetHubStatusRequest())

        assert isinstance(resp, ResultResponse)
        assert resp.data["is_connected"] is True
        assert resp.data["hub_address"] == "6fc8bf22aa293588c9bf8d7488102e95"
        assert resp.data["status"] == "connected"
        assert resp.data["hub_destination_hash"] == "abcdef1234567890"

    @pytest.mark.asyncio
    async def test_returns_disconnected_hub_status(self, handlers):
        hub = MagicMock()
        hub.is_connected = False
        hub.hub_address = None
        hub.status.value = "disabled"
        hub.hub_destination = None

        with patch("styrened.services.hub_connection.get_hub_connection", return_value=hub):
            resp = await handlers.handle_get_hub_status(GetHubStatusRequest())

        assert isinstance(resp, ResultResponse)
        assert resp.data["is_connected"] is False
        assert resp.data["hub_address"] is None
        assert "hub_destination_hash" not in resp.data

    @pytest.mark.asyncio
    async def test_handles_hub_exception(self, handlers):
        with patch(
            "styrened.services.hub_connection.get_hub_connection",
            side_effect=RuntimeError("no hub"),
        ):
            resp = await handlers.handle_get_hub_status(GetHubStatusRequest())
        assert isinstance(resp, ErrorResponse)
        assert "no hub" in resp.message


# ---------------------------------------------------------------------------
# Handler tests: handle_get_unread_counts
# ---------------------------------------------------------------------------


class TestHandleGetUnreadCounts:
    """Tests for handle_get_unread_counts handler."""

    @pytest.mark.asyncio
    async def test_returns_unread_counts(self):
        counts = {"aabbccdd": 3, "eeff0011": 1}
        daemon = FakeDaemon(conversation_service=FakeConversationService(counts))
        handlers = IPCHandlers(daemon=daemon)

        resp = await handlers.handle_get_unread_counts(GetUnreadCountsRequest())
        assert isinstance(resp, ResultResponse)
        assert resp.data["counts"] == {"aabbccdd": 3, "eeff0011": 1}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_conversation_service(self):
        daemon = FakeDaemon(conversation_service=None)
        handlers = IPCHandlers(daemon=daemon)

        resp = await handlers.handle_get_unread_counts(GetUnreadCountsRequest())
        assert isinstance(resp, ResultResponse)
        assert resp.data["counts"] == {}

    @pytest.mark.asyncio
    async def test_returns_error_when_no_daemon(self):
        handlers = IPCHandlers(daemon=None)
        resp = await handlers.handle_get_unread_counts(GetUnreadCountsRequest())
        assert isinstance(resp, ErrorResponse)

    @pytest.mark.asyncio
    async def test_returns_empty_counts_when_no_unread(self):
        daemon = FakeDaemon(conversation_service=FakeConversationService({}))
        handlers = IPCHandlers(daemon=daemon)

        resp = await handlers.handle_get_unread_counts(GetUnreadCountsRequest())
        assert isinstance(resp, ResultResponse)
        assert resp.data["counts"] == {}


# ---------------------------------------------------------------------------
# tui/utils._deduplicate_by_identity
# ---------------------------------------------------------------------------


class TestDeduplicateByIdentity:
    """Tests for the _deduplicate_by_identity pure function in tui/utils.py."""

    def _make_device(self, identity_hash, destination_hash="x", name="n",
                     is_styrene=True, last_announce=None, lxmf_hash=None):
        """Create a FakeMeshDevice for dedup tests."""
        if last_announce is None:
            last_announce = time.time()  # recent by default
        return FakeMeshDevice(
            destination_hash=destination_hash,
            identity_hash=identity_hash,
            name=name,
            is_styrene_node=is_styrene,
            last_announce=last_announce,
            lxmf_destination_hash=lxmf_hash,
        )

    def test_empty_list(self):
        from styrened.tui.utils import _deduplicate_by_identity

        assert _deduplicate_by_identity([]) == []

    def test_single_device(self):
        from styrened.tui.utils import _deduplicate_by_identity

        d = self._make_device("id1")
        result = _deduplicate_by_identity([d])
        assert len(result) == 1

    def test_deduplicates_same_identity(self):
        from styrened.tui.utils import _deduplicate_by_identity

        now = time.time()
        d1 = self._make_device("id1", destination_hash="a", last_announce=now - 10)
        d2 = self._make_device("id1", destination_hash="b", last_announce=now)
        result = _deduplicate_by_identity([d1, d2])
        assert len(result) == 1
        # Should keep more recent
        assert result[0].destination_hash == "b"

    def test_prefers_styrene_node(self):
        from styrened.tui.utils import _deduplicate_by_identity

        now = time.time()
        d1 = self._make_device("id1", destination_hash="a", is_styrene=False, last_announce=now)
        d2 = self._make_device("id1", destination_hash="b", is_styrene=True, last_announce=now - 5)
        result = _deduplicate_by_identity([d1, d2])
        assert len(result) == 1
        assert result[0].is_styrene_node is True

    def test_merges_lxmf_destination(self):
        from styrened.tui.utils import _deduplicate_by_identity

        now = time.time()
        d1 = self._make_device("id1", destination_hash="a", last_announce=now, lxmf_hash=None)
        d2 = self._make_device("id1", destination_hash="b", last_announce=now - 10, lxmf_hash="lxmf123")
        result = _deduplicate_by_identity([d1, d2])
        assert len(result) == 1
        assert result[0].lxmf_destination_hash == "lxmf123"

    def test_filters_stale_devices(self):
        from styrened.tui.utils import _deduplicate_by_identity

        old = time.time() - 3600  # 1 hour ago
        d1 = self._make_device("id1", last_announce=old)
        result = _deduplicate_by_identity([d1])
        assert len(result) == 0

    def test_different_identities_not_merged(self):
        from styrened.tui.utils import _deduplicate_by_identity

        now = time.time()
        d1 = self._make_device("id1", last_announce=now)
        d2 = self._make_device("id2", last_announce=now)
        result = _deduplicate_by_identity([d1, d2])
        assert len(result) == 2
