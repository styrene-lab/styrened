"""Unit tests for IPC block/unblock commands with identity_hash as canonical key."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.ipc.messages import (
    CmdBlockPeerRequest,
    CmdUnblockPeerRequest,
    QueryBlockedPeersRequest,
)


# ---------------------------------------------------------------------------
# CmdBlockPeerRequest serialization
# ---------------------------------------------------------------------------


class TestCmdBlockPeerRequestPayload:
    def test_to_payload_all_fields(self):
        req = CmdBlockPeerRequest(
            identity_hash="aabbcc",
            lxmf_dest_hash="ddeeff",
            alias="Bob",
        )
        payload = req.to_payload()
        assert payload["identity_hash"] == "aabbcc"
        assert payload["lxmf_dest_hash"] == "ddeeff"
        assert payload["alias"] == "Bob"

    def test_to_payload_defaults(self):
        req = CmdBlockPeerRequest(identity_hash="aabbcc")
        payload = req.to_payload()
        assert payload["identity_hash"] == "aabbcc"
        assert payload["lxmf_dest_hash"] == ""
        assert payload["alias"] == ""

    def test_from_payload_round_trip(self):
        original = CmdBlockPeerRequest(
            identity_hash="aabbcc112233",
            lxmf_dest_hash="ddeeff445566",
            alias="Alice",
        )
        restored = CmdBlockPeerRequest.from_payload(original.to_payload())
        assert restored.identity_hash == original.identity_hash
        assert restored.lxmf_dest_hash == original.lxmf_dest_hash
        assert restored.alias == original.alias

    def test_from_payload_missing_fields_defaults(self):
        req = CmdBlockPeerRequest.from_payload({"identity_hash": "abc123"})
        assert req.identity_hash == "abc123"
        assert req.lxmf_dest_hash == ""
        assert req.alias == ""

    def test_no_peer_hash_field(self):
        req = CmdBlockPeerRequest(identity_hash="aabbcc")
        assert not hasattr(req, "peer_hash")


# ---------------------------------------------------------------------------
# CmdUnblockPeerRequest serialization
# ---------------------------------------------------------------------------


class TestCmdUnblockPeerRequestPayload:
    def test_to_payload(self):
        req = CmdUnblockPeerRequest(identity_hash="aabbcc")
        assert req.to_payload() == {"identity_hash": "aabbcc"}

    def test_from_payload_round_trip(self):
        original = CmdUnblockPeerRequest(identity_hash="aabbccddeeff")
        restored = CmdUnblockPeerRequest.from_payload(original.to_payload())
        assert restored.identity_hash == original.identity_hash

    def test_from_payload_missing_identity_hash(self):
        req = CmdUnblockPeerRequest.from_payload({})
        assert req.identity_hash == ""

    def test_no_peer_hash_field(self):
        req = CmdUnblockPeerRequest(identity_hash="aabbcc")
        assert not hasattr(req, "peer_hash")


# ---------------------------------------------------------------------------
# handle_cmd_block_peer
# ---------------------------------------------------------------------------


class TestHandleCmdBlockPeer:
    @pytest.fixture
    def handler(self):
        from styrened.ipc.handlers import IPCHandlers

        h = IPCHandlers.__new__(IPCHandlers)
        h.daemon = MagicMock()
        return h

    @pytest.mark.asyncio
    async def test_empty_identity_hash_returns_error(self, handler):
        req = CmdBlockPeerRequest(identity_hash="")
        resp = await handler.handle_cmd_block_peer(req)
        assert resp.success is False
        assert "identity_hash" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_block_success(self, handler):
        req = CmdBlockPeerRequest(
            identity_hash="aabbcc112233",
            lxmf_dest_hash="ddeeff445566",
            alias="Bob",
        )
        mock_svc = MagicMock()
        mock_svc.block_peer.return_value = True
        with patch(
            "styrened.services.lxmf_service.get_lxmf_service", return_value=mock_svc
        ):
            resp = await handler.handle_cmd_block_peer(req)

        assert resp.success is True
        assert resp.data["blocked"] is True
        assert resp.data["identity_hash"] == "aabbcc112233"
        mock_svc.block_peer.assert_called_once_with("aabbcc112233")

    @pytest.mark.asyncio
    async def test_block_failure_returns_error(self, handler):
        req = CmdBlockPeerRequest(identity_hash="aabbcc")
        mock_svc = MagicMock()
        mock_svc.block_peer.return_value = False
        with patch(
            "styrened.services.lxmf_service.get_lxmf_service", return_value=mock_svc
        ):
            resp = await handler.handle_cmd_block_peer(req)

        assert resp.success is False

    @pytest.mark.asyncio
    async def test_no_peer_hash_fallback(self, handler):
        """Ensure there is no peer_hash fallback path."""
        req = CmdBlockPeerRequest(identity_hash="")
        resp = await handler.handle_cmd_block_peer(req)
        assert resp.success is False


# ---------------------------------------------------------------------------
# handle_cmd_unblock_peer
# ---------------------------------------------------------------------------


class TestHandleCmdUnblockPeer:
    @pytest.fixture
    def handler(self):
        from styrened.ipc.handlers import IPCHandlers

        h = IPCHandlers.__new__(IPCHandlers)
        h.daemon = MagicMock()
        return h

    @pytest.mark.asyncio
    async def test_empty_identity_hash_returns_error(self, handler):
        req = CmdUnblockPeerRequest(identity_hash="")
        resp = await handler.handle_cmd_unblock_peer(req)
        assert resp.success is False
        assert "identity_hash" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_unblock_success(self, handler):
        req = CmdUnblockPeerRequest(identity_hash="aabbcc112233")
        mock_svc = MagicMock()
        mock_svc.unblock_peer.return_value = True
        with patch(
            "styrened.services.lxmf_service.get_lxmf_service", return_value=mock_svc
        ):
            resp = await handler.handle_cmd_unblock_peer(req)

        assert resp.success is True
        assert resp.data["identity_hash"] == "aabbcc112233"
        mock_svc.unblock_peer.assert_called_once_with("aabbcc112233")

    @pytest.mark.asyncio
    async def test_unblock_failure_returns_error(self, handler):
        req = CmdUnblockPeerRequest(identity_hash="aabbcc")
        mock_svc = MagicMock()
        mock_svc.unblock_peer.return_value = False
        with patch(
            "styrened.services.lxmf_service.get_lxmf_service", return_value=mock_svc
        ):
            resp = await handler.handle_cmd_unblock_peer(req)

        assert resp.success is False


# ---------------------------------------------------------------------------
# IPCClient
# ---------------------------------------------------------------------------


class TestIPCClientBlockPeer:
    @pytest.mark.asyncio
    async def test_block_peer_sends_identity_hash(self):
        from styrened.ipc.client import ControlClient as IPCClient

        client = IPCClient.__new__(IPCClient)
        sent: list = []

        async def fake_request(req):
            sent.append(req)
            return {"success": True}

        client._request = fake_request

        await client.block_peer("aabbcc", lxmf_dest_hash="ddeeff", alias="Bob")
        assert len(sent) == 1
        req = sent[0]
        assert isinstance(req, CmdBlockPeerRequest)
        assert req.identity_hash == "aabbcc"
        assert req.lxmf_dest_hash == "ddeeff"
        assert req.alias == "Bob"

    @pytest.mark.asyncio
    async def test_unblock_peer_sends_identity_hash(self):
        from styrened.ipc.client import ControlClient as IPCClient

        client = IPCClient.__new__(IPCClient)
        sent: list = []

        async def fake_request(req):
            sent.append(req)
            return {"success": True}

        client._request = fake_request

        await client.unblock_peer("aabbcc112233")
        assert len(sent) == 1
        req = sent[0]
        assert isinstance(req, CmdUnblockPeerRequest)
        assert req.identity_hash == "aabbcc112233"


# ---------------------------------------------------------------------------
# MeshDevice.identity property deleted
# ---------------------------------------------------------------------------


class TestMeshDeviceNoIdentityProperty:
    def test_identity_property_deleted(self):
        from styrened.models.mesh_device import MeshDevice

        assert not hasattr(MeshDevice, "identity") or not isinstance(
            getattr(MeshDevice, "identity", None), property
        ), "MeshDevice.identity property must be deleted"
