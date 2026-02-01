"""Smoke tests for styrene-core models."""


from styrened.models import (
    CoreConfig,
    DeviceType,
    MeshDevice,
    ReticulumIdentity,
    ReticulumState,
    RNSErrorState,
)


def test_core_config_instantiation() -> None:
    """CoreConfig should instantiate with defaults."""
    config = CoreConfig()
    assert config.reticulum is not None
    assert config.rpc is not None
    assert config.discovery is not None
    assert config.chat is not None
    assert config.api is not None


def test_reticulum_state_instantiation() -> None:
    """ReticulumState should instantiate with identity."""
    identity = ReticulumIdentity(address="abc123")
    state = ReticulumState(identity=identity)
    assert state.identity.address == "abc123"
    assert state.enabled_interface_count == 0


def test_mesh_device_instantiation() -> None:
    """MeshDevice should instantiate with required fields."""
    device = MeshDevice(
        destination_hash="abc123",
        identity_hash="def456",
        name="test-device",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=1234567890,
    )
    assert device.name == "test-device"
    assert device.is_styrene_node is True
    assert device.is_rnode is False


def test_rns_error_state() -> None:
    """RNSErrorState should handle error categorization."""
    error = RNSErrorState.none()
    assert error.is_error is False

    exc_error = RNSErrorState.from_exception(FileNotFoundError("config not found"))
    assert exc_error.is_error is True
