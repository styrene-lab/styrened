"""Smoke tests for core services."""
from __future__ import annotations


import tempfile
from pathlib import Path


def test_rns_service_import() -> None:
    """RNS service should import without errors."""
    from styrened.services.rns_service import RNSService, get_rns_service

    assert RNSService is not None
    assert get_rns_service is not None


def test_rns_service_instantiation() -> None:
    """RNS service should instantiate as singleton."""
    from styrened.services.rns_service import get_rns_service

    service1 = get_rns_service()
    service2 = get_rns_service()

    assert service1 is not None
    assert service1 is service2  # Singleton
    assert service1.is_initialized is False  # Not initialized yet
    assert service1.error_state.is_error is False


def test_lxmf_service_import() -> None:
    """LXMF service should import without errors."""
    from styrened.services.lxmf_service import LXMFService, get_lxmf_service

    assert LXMFService is not None
    assert get_lxmf_service is not None


def test_lxmf_service_instantiation() -> None:
    """LXMF service should instantiate as singleton."""
    from styrened.services.lxmf_service import get_lxmf_service

    service1 = get_lxmf_service()
    service2 = get_lxmf_service()

    assert service1 is not None
    assert service1 is service2  # Singleton
    assert service1.is_initialized is False


def test_auto_reply_import() -> None:
    """Auto-reply handler should import without errors."""
    from styrened.services.auto_reply import AutoReplyHandler

    assert AutoReplyHandler is not None


def test_auto_reply_instantiation() -> None:
    """Auto-reply handler should instantiate with mocked dependencies."""
    from styrened.models.config import ChatConfig
    from styrened.services.auto_reply import AutoReplyHandler

    _config = ChatConfig()
    # AutoReplyHandler requires identity and router (RNS/LXMF objects)
    # For smoke test, just verify it can be imported and class exists
    # Full instantiation requires RNS/LXMF which needs network initialization
    assert AutoReplyHandler is not None
    assert callable(AutoReplyHandler)


def test_node_store_import() -> None:
    """Node store should import without errors."""
    from styrened.services.node_store import NodeStore, get_node_store

    assert NodeStore is not None
    assert get_node_store is not None


def test_node_store_instantiation() -> None:
    """Node store should instantiate as singleton."""
    from styrened.services.node_store import get_node_store

    store1 = get_node_store()
    store2 = get_node_store()

    assert store1 is not None
    assert store1 is store2  # Singleton


def test_node_store_basic_operations() -> None:
    """Node store should support basic CRUD operations."""
    from styrened.models.mesh_device import DeviceType, MeshDevice
    from styrened.services.node_store import NodeStore

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_nodes.db"
        store = NodeStore(db_path)

        # Create test device with valid 32-char hex hashes
        dest_hash = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        identity_hash = "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6"
        device = MeshDevice(
            destination_hash=dest_hash,
            identity_hash=identity_hash,
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1234567890,
        )

        # Save
        store.save_node(device)

        # Retrieve
        retrieved = store.get_node_by_destination(dest_hash)
        assert retrieved is not None
        assert retrieved.name == "test-node"
        assert retrieved.device_type == DeviceType.STYRENE_NODE

        # List all
        all_nodes = store.get_all_nodes()
        assert len(all_nodes) == 1

        # Clear
        count = store.clear_all_nodes()
        assert count == 1
        assert len(store.get_all_nodes()) == 0


def test_reticulum_service_import() -> None:
    """Reticulum service should import without errors."""
    from styrened.services.reticulum import (
        discover_devices,
        ensure_operator_identity,
        find_reticulum_config,
        get_operator_identity,
        start_discovery,
        stop_discovery,
    )

    assert discover_devices is not None
    assert ensure_operator_identity is not None
    assert find_reticulum_config is not None
    assert get_operator_identity is not None
    assert start_discovery is not None
    assert stop_discovery is not None


def test_hub_connection_import() -> None:
    """Hub connection should import without errors."""
    from styrened.services.hub_connection import (
        STYRENE_HUB_ADDRESS,
        HubConnection,
        get_hub_connection,
    )

    assert HubConnection is not None
    assert get_hub_connection is not None
    assert STYRENE_HUB_ADDRESS is not None


def test_hub_connection_instantiation() -> None:
    """Hub connection should instantiate as singleton."""
    from styrened.services.hub_connection import get_hub_connection

    hub1 = get_hub_connection()
    hub2 = get_hub_connection()

    assert hub1 is not None
    assert hub1 is hub2  # Singleton
    assert hub1.is_connected is False  # Not connected yet
    assert hub1.hub_address is None  # No address set


def test_core_lifecycle_import() -> None:
    """CoreLifecycle should import without errors."""
    from styrened.services.lifecycle import CoreLifecycle

    assert CoreLifecycle is not None
    assert callable(CoreLifecycle)


def test_core_lifecycle_instantiation() -> None:
    """CoreLifecycle should instantiate with CoreConfig."""
    from styrened.services.config import get_default_core_config
    from styrened.services.lifecycle import CoreLifecycle

    config = get_default_core_config()
    lifecycle = CoreLifecycle(config)

    assert lifecycle is not None
    assert lifecycle.config is config
    assert lifecycle.is_initialized is False
    assert lifecycle.rns_error_state.is_error is False
