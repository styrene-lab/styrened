"""Unit tests for RPC CMD_PROVISION command.

Tests RBAC enforcement, message serialization, and IPC bridge integration
for adapter binary provisioning.

TDD: ADMIN succeeds, OPERATOR rejected, LOCAL bypasses RBAC.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry
from styrened.models.styrene_wire import StyreneMessageType
from styrened.rpc.messages import ProvisionRequest, ProvisionResponse


# ---------------------------------------------------------------------------
# ProvisionRequest / ProvisionResponse serialization
# ---------------------------------------------------------------------------


class TestProvisionRequest:
    """Test ProvisionRequest message serialization."""

    def test_provision_request_default_type(self):
        """ProvisionRequest has correct type field."""
        req = ProvisionRequest(adapter="yggdrasil")
        assert req.type == "provision"
        assert req.adapter == "yggdrasil"

    def test_provision_request_to_dict(self):
        """ProvisionRequest serializes adapter name."""
        req = ProvisionRequest(adapter="yggdrasil")
        d = req.to_dict()
        assert d["adapter"] == "yggdrasil"
        assert d["type"] == "provision"

    def test_provision_request_from_dict(self):
        """ProvisionRequest deserializes from dict."""
        req = ProvisionRequest.from_dict({"adapter": "yggdrasil", "type": "provision"})
        assert req.adapter == "yggdrasil"

    def test_provision_request_from_dict_missing_adapter(self):
        """ProvisionRequest defaults adapter to empty string."""
        req = ProvisionRequest.from_dict({})
        assert req.adapter == ""


class TestProvisionResponse:
    """Test ProvisionResponse message serialization."""

    def test_provision_response_success(self):
        """ProvisionResponse round-trips success case."""
        resp = ProvisionResponse(
            success=True,
            adapter="yggdrasil",
            installed_path="/usr/bin/yggdrasil",
        )
        d = resp.to_dict()
        assert d["success"] is True
        assert d["adapter"] == "yggdrasil"
        assert d["installed_path"] == "/usr/bin/yggdrasil"
        assert d["error"] is None

    def test_provision_response_failure(self):
        """ProvisionResponse round-trips failure case."""
        resp = ProvisionResponse(
            success=False,
            adapter="yggdrasil",
            error="Download failed",
        )
        d = resp.to_dict()
        assert d["success"] is False
        assert d["error"] == "Download failed"

    def test_provision_response_from_dict(self):
        """ProvisionResponse deserializes from dict."""
        resp = ProvisionResponse.from_dict({
            "success": True,
            "adapter": "yggdrasil",
            "installed_path": "/usr/bin/yggdrasil",
        })
        assert resp.success is True
        assert resp.adapter == "yggdrasil"
        assert resp.installed_path == "/usr/bin/yggdrasil"


# ---------------------------------------------------------------------------
# Wire format: StyreneMessageType.PROVISION exists
# ---------------------------------------------------------------------------


class TestProvisionWireFormat:
    """Test PROVISION message type in wire format."""

    def test_provision_command_type_exists(self):
        """PROVISION command type is registered at 0x47."""
        assert StyreneMessageType.PROVISION == 0x47

    def test_provision_result_type_exists(self):
        """PROVISION_RESULT response type is registered at 0x67."""
        assert StyreneMessageType.PROVISION_RESULT == 0x67


# ---------------------------------------------------------------------------
# RBAC: adapter.provision capability
# ---------------------------------------------------------------------------


class TestProvisionRBAC:
    """Test RBAC enforcement for adapter provisioning."""

    def test_adapter_provision_capability_exists(self):
        """adapter.provision is a registered capability."""
        assert Capability.ADAPTER_PROVISION == "adapter.provision"
        assert "adapter.provision" in Capability.ALL

    def test_admin_has_adapter_provision(self):
        """ADMIN role includes adapter.provision capability."""
        policy = RBACPolicy(default_role=Role.ADMIN)
        assert policy.has_capability("test_hash", Capability.ADAPTER_PROVISION)

    def test_operator_lacks_adapter_provision(self):
        """OPERATOR role does NOT include adapter.provision."""
        policy = RBACPolicy(default_role=Role.OPERATOR)
        assert not policy.has_capability("test_hash", Capability.ADAPTER_PROVISION)

    def test_peer_lacks_adapter_provision(self):
        """PEER role does NOT include adapter.provision."""
        policy = RBACPolicy(default_role=Role.PEER)
        assert not policy.has_capability("test_hash", Capability.ADAPTER_PROVISION)

    def test_provision_mapped_in_message_type_capability(self):
        """PROVISION message type is mapped to adapter.provision capability."""
        from styrened.rpc.server import MESSAGE_TYPE_CAPABILITY

        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.PROVISION] == Capability.ADAPTER_PROVISION


# ---------------------------------------------------------------------------
# RPC server handler
# ---------------------------------------------------------------------------


class TestRPCProvisionHandler:
    """Test RPC server _handle_provision."""

    def _make_server(self, default_role=Role.ADMIN):
        """Create an RPCServer with mocked protocol."""
        from styrened.rpc.server import RPCServer

        protocol = MagicMock()
        protocol.register_handler = MagicMock()
        policy = RBACPolicy(default_role=default_role)
        server = RPCServer(protocol, rbac_policy=policy)
        return server

    def _make_envelope(self, adapter="yggdrasil"):
        """Create a mock StyreneEnvelope for PROVISION."""
        from styrened.models.styrene_wire import StyreneEnvelope, encode_payload

        payload = encode_payload({"adapter": adapter, "type": "provision"})
        return StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PROVISION,
            request_id=b"\x00" * 16,
            payload=payload,
        )

    @pytest.mark.asyncio
    async def test_handle_provision_admin_succeeds(self):
        """ADMIN role can invoke provision handler."""
        server = self._make_server(default_role=Role.ADMIN)

        # Mock BinaryProvisioner
        mock_provisioner = MagicMock()
        mock_provisioner.provision.return_value = {
            "success": True,
            "installed_path": "/usr/bin/yggdrasil",
            "adapter": "yggdrasil",
        }
        server.set_binary_provisioner(mock_provisioner)

        # Mock protocol send to avoid real network calls
        server._protocol.send_typed_message = AsyncMock()

        envelope = self._make_envelope("yggdrasil")
        server._handle_provision("admin_hash", envelope)

        # Let async tasks complete
        await asyncio.sleep(0.05)

        mock_provisioner.provision.assert_called_once_with("yggdrasil")

    def test_operator_lacks_provision_capability(self):
        """OPERATOR role lacks adapter.provision — RBAC rejects before dispatch."""
        server = self._make_server(default_role=Role.OPERATOR)

        mock_provisioner = MagicMock()
        server.set_binary_provisioner(mock_provisioner)

        # Verify the RBAC policy itself rejects OPERATOR for this capability
        assert not server._rbac_policy.has_capability("operator_hash", Capability.ADAPTER_PROVISION)

        # Verify the MESSAGE_TYPE_CAPABILITY mapping exists so dispatch would check it
        from styrened.rpc.server import MESSAGE_TYPE_CAPABILITY
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.PROVISION] == Capability.ADAPTER_PROVISION


# ---------------------------------------------------------------------------
# IPC messages for provision
# ---------------------------------------------------------------------------


class TestIPCProvisionMessages:
    """Test IPC message types for adapter provisioning."""

    def test_ipc_provision_adapter_type_exists(self):
        """CMD_PROVISION_ADAPTER IPC message type exists."""
        from styrened.ipc.protocol import IPCMessageType

        assert hasattr(IPCMessageType, "CMD_PROVISION_ADAPTER")

    def test_ipc_provision_request_serialization(self):
        """CmdProvisionAdapterRequest round-trips."""
        from styrened.ipc.messages import CmdProvisionAdapterRequest

        req = CmdProvisionAdapterRequest(adapter_name="yggdrasil")
        payload = req.to_payload()
        assert payload["adapter_name"] == "yggdrasil"

    def test_ipc_provision_request_wire_format(self):
        """CmdProvisionAdapterRequest has correct MSG_TYPE."""
        from styrened.ipc.messages import CmdProvisionAdapterRequest
        from styrened.ipc.protocol import IPCMessageType

        req = CmdProvisionAdapterRequest(adapter_name="yggdrasil")
        assert req.MSG_TYPE == IPCMessageType.CMD_PROVISION_ADAPTER


# ---------------------------------------------------------------------------
# IPC handler
# ---------------------------------------------------------------------------


class TestIPCProvisionHandler:
    """Test IPC handler for adapter provisioning."""

    @pytest.fixture
    def handler(self):
        """Create IPC handler with mocked daemon."""
        from styrened.ipc.handlers import IPCHandlers

        daemon = MagicMock()
        daemon._binary_provisioner = MagicMock()
        daemon._binary_provisioner.provision.return_value = {
            "success": True,
            "installed_path": "/usr/bin/yggdrasil",
            "adapter": "yggdrasil",
        }
        h = IPCHandlers(daemon)
        return h

    @pytest.mark.asyncio
    async def test_provision_adapter_success(self, handler):
        """IPC provision_adapter handler invokes BinaryProvisioner."""
        from styrened.ipc.messages import CmdProvisionAdapterRequest, ResultResponse

        req = CmdProvisionAdapterRequest(adapter_name="yggdrasil")
        resp = await handler.handle_cmd_provision_adapter(req)

        assert isinstance(resp, ResultResponse)
        assert resp.data["success"] is True
        handler.daemon._binary_provisioner.provision.assert_called_once_with("yggdrasil")

    @pytest.mark.asyncio
    async def test_provision_adapter_missing_name(self, handler):
        """IPC provision_adapter rejects empty adapter name."""
        from styrened.ipc.messages import CmdProvisionAdapterRequest, ErrorResponse

        req = CmdProvisionAdapterRequest(adapter_name="")
        resp = await handler.handle_cmd_provision_adapter(req)

        assert isinstance(resp, ErrorResponse)

    @pytest.mark.asyncio
    async def test_provision_adapter_no_provisioner(self, handler):
        """IPC provision_adapter handles missing provisioner gracefully."""
        from styrened.ipc.messages import CmdProvisionAdapterRequest, ErrorResponse

        handler.daemon._binary_provisioner = None
        req = CmdProvisionAdapterRequest(adapter_name="yggdrasil")
        resp = await handler.handle_cmd_provision_adapter(req)

        assert isinstance(resp, ErrorResponse)


# ---------------------------------------------------------------------------
# IPCBridge method
# ---------------------------------------------------------------------------


class TestIPCBridgeProvision:
    """Test IPCBridge.provision_adapter method."""

    def test_bridge_has_provision_adapter_method(self):
        """IPCBridge exposes provision_adapter method."""
        from styrened.ipc.bridge import IPCBridge

        assert hasattr(IPCBridge, "provision_adapter")
