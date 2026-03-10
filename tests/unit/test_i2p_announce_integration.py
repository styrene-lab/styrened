"""Tests for I2P announce integration in StyreneAnnounceHandler."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from styrened.models.capabilities import CAPABILITY_I2P
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.reticulum import StyreneAnnounceHandler


def _fake_identity(hex_hash: str = "a" * 32) -> MagicMock:
    identity = MagicMock()
    identity.hash = bytes.fromhex(hex_hash)
    identity.get_public_key.return_value = None
    return identity


def _styrene_app_data(capabilities: list[str]) -> bytes:
    caps_str = ",".join(capabilities) if capabilities else "node"
    lxmf_dest = "b" * 64
    return f"styrene:TestNode:0.15.4:{caps_str}:{lxmf_dest}:tn:fp:".encode()


def _call_received_announce(handler: StyreneAnnounceHandler, capabilities: list[str] | None = None) -> None:
    dest_hex = "c" * 32
    identity_hex = "a" * 32
    dest_hash = bytes.fromhex(dest_hex)
    identity = _fake_identity(identity_hex)
    app_data = _styrene_app_data(capabilities or [])

    with (
        patch("styrened.services.reticulum.RNS") as mock_rns,
        patch("styrened.services.reticulum.create_mesh_device") as mock_create,
        patch("styrened.services.reticulum.logger"),
    ):
        mock_rns.Transport.path_table = {}
        device = MeshDevice(
            destination_hash=dest_hex,
            identity_hash=identity_hex,
            device_type=DeviceType.STYRENE_NODE,
            name="TestNode",
            capabilities=capabilities or [],
            lxmf_destination_hash="b" * 64,
            last_announce=int(time.time()),
        )
        mock_create.return_value = device

        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=identity,
            app_data=app_data,
        )


class TestI2PCapabilityDetection:
    def test_i2p_capability_sets_b32_address_none(self) -> None:
        handler = StyreneAnnounceHandler(callback=None, node_store=None)
        _call_received_announce(handler, capabilities=[CAPABILITY_I2P])
        device = list(handler.discovered_devices.values())[0]
        assert device.b32_address is None

    def test_no_i2p_capability_leaves_b32_address_default(self) -> None:
        handler = StyreneAnnounceHandler(callback=None, node_store=None)
        _call_received_announce(handler, capabilities=["hub"])
        device = list(handler.discovered_devices.values())[0]
        assert device.b32_address is None

    def test_i2p_capability_is_persisted_to_node_store(self, tmp_path) -> None:
        from styrened.services.node_store import NodeStore

        store = NodeStore(db_path=str(tmp_path / "nodes.db"))
        handler = StyreneAnnounceHandler(callback=None, node_store=store)
        _call_received_announce(handler, capabilities=[CAPABILITY_I2P, "api"])

        stored = store.get_node_by_destination("c" * 32)
        assert stored is not None
        assert CAPABILITY_I2P in (stored.capabilities or [])
        assert stored.b32_address is None
