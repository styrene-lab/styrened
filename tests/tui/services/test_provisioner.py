"""Tests for provisioner service."""

import pytest

from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.profiles import Profile
from styrened.tui.services.provisioner import provision_device
from styrened.tui.services.storage import StorageDevice


@pytest.fixture
def mock_profile():
    """Create a mock profile for testing."""
    return Profile(
        id="test-profile",
        label="Test Profile",
        description="Test profile for testing",
        roles=["test-role"],
        verified=[["test-hardware"]],
        requires_traits=None,
    )


@pytest.fixture
def mock_hardware():
    """Create mock hardware for testing."""
    return Hardware(
        id="test-hardware",
        label="Test Hardware",
        arch="aarch64",
        boot="sd",
        activity="low",
        traits=["wifi"],
        type="sbc",
    )


@pytest.fixture
def mock_storage():
    """Create mock storage device for testing."""
    return StorageDevice(
        device="/dev/test",
        size_gb=32,
        type="sd",
        mounted=False,
        label="TEST",
    )


@pytest.fixture
def mock_config():
    """Create mock configuration for testing."""
    return {
        "hostname": "test-device",
        "wifi_ssid": "TestNetwork",
        "wifi_password": "password123",
        "ssh_key_path": "/tmp/test_key.pub",
        "mesh_enabled": "true",
    }


@pytest.mark.asyncio
async def test_provision_device_success(mock_profile, mock_hardware, mock_storage, mock_config):
    """Test successful mock provisioning."""
    result = await provision_device(
        profile=mock_profile,
        hardware=mock_hardware,
        storage=mock_storage,
        config=mock_config,
        progress_callback=None,
        mock=True,
    )

    assert result.success
    assert result.device == "/dev/test"
    assert result.profile == "test-profile"
    assert result.hardware == "test-hardware"
    assert len(result.errors) == 0
    assert len(result.log) > 0


@pytest.mark.asyncio
async def test_provision_device_mounted_storage(
    mock_profile, mock_hardware, mock_storage, mock_config
):
    """Test provisioning fails when storage is mounted."""
    mock_storage.mounted = True

    result = await provision_device(
        profile=mock_profile,
        hardware=mock_hardware,
        storage=mock_storage,
        config=mock_config,
        progress_callback=None,
        mock=True,
    )

    assert not result.success
    assert len(result.errors) > 0
    assert "mounted" in result.errors[0].lower()


@pytest.mark.asyncio
async def test_provision_device_with_callback(
    mock_profile, mock_hardware, mock_storage, mock_config
):
    """Test provisioning with progress callback."""
    messages = []

    def progress_callback(message: str):
        messages.append(message)

    result = await provision_device(
        profile=mock_profile,
        hardware=mock_hardware,
        storage=mock_storage,
        config=mock_config,
        progress_callback=progress_callback,
        mock=True,
    )

    assert result.success
    assert len(messages) > 0
    assert any("Starting provisioning" in m for m in messages)
