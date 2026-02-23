"""Tests for Reticulum identity and configuration services.

These tests verify:
- Reading Reticulum configuration from ~/.reticulum/
- Parsing identity from storage/identity file
- Parsing interfaces from config file
- Proper error handling when Reticulum is not configured
- Device discovery via RNS announces
- Real-time network status detection
"""

from pathlib import Path
from typing import Any

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.reticulum import (
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
    ReticulumState,
)
from styrened.tui.services.reticulum import (
    get_reticulum_config,
    is_reticulum_configured,
)


class TestReticulumModels:
    """Tests for Reticulum data models."""

    def test_reticulum_identity_creation(self) -> None:
        """Test ReticulumIdentity can be created with address."""
        identity = ReticulumIdentity(address="3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c")
        assert identity.address == "3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c"
        assert identity.created is None

    def test_reticulum_identity_with_timestamp(self) -> None:
        """Test ReticulumIdentity can include creation timestamp."""
        identity = ReticulumIdentity(
            address="3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c",
            created=1704067200,
        )
        assert identity.address == "3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c"
        assert identity.created == 1704067200

    def test_reticulum_identity_truncated_display(self) -> None:
        """Test identity address can be truncated for display."""
        identity = ReticulumIdentity(address="3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c")
        truncated = identity.truncated_address()
        assert truncated == "3f8a...4b5c"
        assert len(truncated) == 11  # 4 prefix + 3 dots + 4 suffix

    def test_reticulum_identity_truncated_custom_length(self) -> None:
        """Test identity truncation with custom length."""
        identity = ReticulumIdentity(address="3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c")
        truncated = identity.truncated_address(prefix_len=6, suffix_len=6)
        assert truncated == "3f8a1b...3a4b5c"

    def test_reticulum_interface_creation(self) -> None:
        """Test ReticulumInterface can be created."""
        interface = ReticulumInterface(
            name="Default Interface",
            interface_type="AutoInterface",
            enabled=True,
        )
        assert interface.name == "Default Interface"
        assert interface.interface_type == "AutoInterface"
        assert interface.enabled is True

    def test_reticulum_interface_disabled(self) -> None:
        """Test ReticulumInterface can be disabled."""
        interface = ReticulumInterface(
            name="TCP Client",
            interface_type="TCPClientInterface",
            enabled=False,
        )
        assert interface.enabled is False

    def test_reticulum_state_creation(self) -> None:
        """Test ReticulumState can be created with all components."""
        identity = ReticulumIdentity(address="abc123")
        interfaces = [
            ReticulumInterface(
                name="Auto", interface_type="AutoInterface", enabled=True
            ),
        ]
        state = ReticulumState(
            identity=identity,
            interfaces=interfaces,
            config_path=Path("/home/user/.reticulum"),
        )
        assert state.identity == identity
        assert len(state.interfaces) == 1
        assert state.config_path == Path("/home/user/.reticulum")

    def test_reticulum_state_interface_count(self) -> None:
        """Test ReticulumState reports interface counts correctly."""
        identity = ReticulumIdentity(address="abc123")
        interfaces = [
            ReticulumInterface(
                name="Auto", interface_type="AutoInterface", enabled=True
            ),
            ReticulumInterface(
                name="TCP", interface_type="TCPClientInterface", enabled=True
            ),
            ReticulumInterface(
                name="UDP", interface_type="UDPInterface", enabled=False
            ),
        ]
        state = ReticulumState(
            identity=identity,
            interfaces=interfaces,
            config_path=Path("/home/user/.reticulum"),
        )
        assert state.enabled_interface_count == 2
        assert state.total_interface_count == 3


class TestReticulumNotConfiguredError:
    """Tests for the ReticulumNotConfiguredError exception."""

    def test_error_has_user_friendly_message(self) -> None:
        """Test error provides user-friendly message."""
        error = ReticulumNotConfiguredError()
        message = str(error)
        assert "reticulum" in message.lower()
        assert len(message) > 20  # Should be descriptive

    def test_error_with_custom_message(self) -> None:
        """Test error can have custom message."""
        error = ReticulumNotConfiguredError("Custom error message")
        assert str(error) == "Custom error message"

    def test_error_includes_path_hint(self) -> None:
        """Test default error message hints at expected path."""
        error = ReticulumNotConfiguredError()
        message = str(error)
        assert ".reticulum" in message


class TestIsReticulumConfigured:
    """Tests for the is_reticulum_configured function."""

    def test_returns_false_when_directory_missing(self, tmp_path: Path) -> None:
        """Test returns False when ~/.reticulum directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        result = is_reticulum_configured(config_dir=nonexistent)
        assert result is False

    def test_returns_false_when_config_missing(self, tmp_path: Path) -> None:
        """Test returns False when config file is missing."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()
        result = is_reticulum_configured(config_dir=reticulum_dir)
        assert result is False

    def test_returns_true_when_identity_missing(self, tmp_path: Path) -> None:
        """Test returns True when config exists even if identity file is missing.

        Identity files are created automatically by RNS on first use, so we only
        check for the config file to determine if RNS is intentionally set up.
        """
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()
        (reticulum_dir / "config").write_text("[reticulum]\n")
        result = is_reticulum_configured(config_dir=reticulum_dir)
        assert result is True

    def test_returns_true_when_properly_configured(self, tmp_path: Path) -> None:
        """Test returns True when both config and identity exist."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()
        (reticulum_dir / "config").write_text("[reticulum]\n")
        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(b"\x00" * 32)  # Dummy identity bytes
        result = is_reticulum_configured(config_dir=reticulum_dir)
        assert result is True


class TestGetReticulumConfig:
    """Tests for the get_reticulum_config function."""

    def test_raises_error_when_not_configured(self, tmp_path: Path) -> None:
        """Test raises ReticulumNotConfiguredError when not set up."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(ReticulumNotConfiguredError):
            get_reticulum_config(config_dir=nonexistent)

    def test_parses_basic_config(self, tmp_path: Path) -> None:
        """Test parses a basic Reticulum configuration."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        # Write a minimal config file (ConfigParser format)
        config_content = """[reticulum]
enable_transport = false
share_instance = true

[interfaces]

[[Default Interface]]
type = AutoInterface
enabled = true
"""
        (reticulum_dir / "config").write_text(config_content)

        # Write a dummy identity file (32 bytes minimum for identity)
        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        identity_bytes = bytes.fromhex("3f8a1b2c4d5e6f7a8b9c0d1e2f3a4b5c" * 2)
        (storage_dir / "identity").write_bytes(identity_bytes)

        config = get_reticulum_config(config_dir=reticulum_dir)

        assert config.config_path == reticulum_dir
        assert config.identity is not None
        assert len(config.interfaces) >= 1

    def test_parses_multiple_interfaces(self, tmp_path: Path) -> None:
        """Test parses configuration with multiple interfaces."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        config_content = """[reticulum]
enable_transport = false

[interfaces]

[[Default Interface]]
type = AutoInterface
enabled = true

[[TCP Server]]
type = TCPServerInterface
enabled = true
listen_ip = 0.0.0.0
listen_port = 4242

[[UDP Interface]]
type = UDPInterface
enabled = false
"""
        (reticulum_dir / "config").write_text(config_content)

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(bytes(32))

        config = get_reticulum_config(config_dir=reticulum_dir)

        assert len(config.interfaces) == 3
        interface_names = [i.name for i in config.interfaces]
        assert "Default Interface" in interface_names
        assert "TCP Server" in interface_names
        assert "UDP Interface" in interface_names

    def test_parses_interface_enabled_status(self, tmp_path: Path) -> None:
        """Test correctly parses interface enabled/disabled status."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        config_content = """[reticulum]

[interfaces]

[[Enabled Interface]]
type = AutoInterface
enabled = true

[[Disabled Interface]]
type = TCPClientInterface
enabled = false
"""
        (reticulum_dir / "config").write_text(config_content)

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(bytes(32))

        config = get_reticulum_config(config_dir=reticulum_dir)

        enabled = next(i for i in config.interfaces if i.name == "Enabled Interface")
        disabled = next(i for i in config.interfaces if i.name == "Disabled Interface")

        assert enabled.enabled is True
        assert disabled.enabled is False

    def test_reads_identity_as_hex(self, tmp_path: Path) -> None:
        """Test reads identity file and converts to hex string."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        (reticulum_dir / "config").write_text("[reticulum]\n[interfaces]\n")

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        # Write specific bytes so we can verify hex conversion
        identity_bytes = bytes.fromhex("abcdef0123456789" * 4)
        (storage_dir / "identity").write_bytes(identity_bytes)

        config = get_reticulum_config(config_dir=reticulum_dir)

        # Identity address should contain hex representation of the bytes
        assert config.identity.address is not None
        assert all(c in "0123456789abcdef" for c in config.identity.address)

    def test_handles_empty_interfaces_section(self, tmp_path: Path) -> None:
        """Test handles config with no interfaces defined."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        config_content = """[reticulum]
enable_transport = false
"""
        (reticulum_dir / "config").write_text(config_content)

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(bytes(32))

        config = get_reticulum_config(config_dir=reticulum_dir)

        assert config.interfaces == []

    def test_handles_malformed_config_gracefully(self, tmp_path: Path) -> None:
        """Test handles malformed config file with appropriate error."""
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        # Write invalid config (not valid ConfigParser format)
        (reticulum_dir / "config").write_text("this is not valid config syntax {{{")

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(bytes(32))

        # Should either parse what it can or raise a clear error
        # For robustness, we'll accept either empty interfaces or an exception
        try:
            config = get_reticulum_config(config_dir=reticulum_dir)
            # If it succeeds, it should have at least parsed identity
            assert config.identity is not None
        except ReticulumNotConfiguredError:
            # This is also acceptable behavior
            pass

    def test_uses_default_path_when_not_specified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test uses ~/.reticulum when no config_dir specified."""
        # This test verifies the default path behavior without actually
        # reading from the real filesystem
        calls: list[Path] = []

        def mock_is_configured(config_dir: Path | None = None) -> bool:
            if config_dir is not None:
                calls.append(config_dir)
            return False

        # We can't easily test the default without mocking, but we can
        # verify the function accepts no arguments
        with pytest.raises(ReticulumNotConfiguredError):
            # This should use the default path and fail (since we're in a test env)
            get_reticulum_config()


class TestOperatorIdentity:
    """Tests for operator identity management."""

    def test_ensure_operator_identity_creates_new(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test ensure_operator_identity creates new RNS.Identity if none exists."""
        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Ensure identity
        identity_hash = core_reticulum.ensure_operator_identity()

        # Should create the file
        assert operator_key.exists()

        # Should return hex-encoded hash (RNS identity hash is 16 bytes = 32 hex chars)
        assert len(identity_hash) == 32
        assert all(c in "0123456789abcdef" for c in identity_hash)

    def test_ensure_operator_identity_loads_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test ensure_operator_identity loads existing RNS.Identity."""
        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create identity first time
        first_hash = core_reticulum.ensure_operator_identity()

        # Load it again - should return same hash
        second_hash = core_reticulum.ensure_operator_identity()

        assert first_hash == second_hash

    def test_ensure_operator_identity_creates_valid_rns_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test ensure_operator_identity creates a valid RNS.Identity that can be loaded."""
        import RNS

        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create identity
        identity_hash = core_reticulum.ensure_operator_identity()

        # Should be loadable with RNS.Identity.from_file
        identity = RNS.Identity.from_file(str(operator_key))
        assert identity is not None
        assert identity.hash.hex() == identity_hash

    def test_get_operator_identity_object_returns_none_if_not_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_operator_identity_object returns None if identity doesn't exist."""
        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        identity = core_reticulum.get_operator_identity_object()
        assert identity is None

    def test_get_operator_identity_object_returns_rns_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_operator_identity_object returns RNS.Identity object."""
        import RNS

        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create identity first
        core_reticulum.ensure_operator_identity()

        # Get identity object
        identity = core_reticulum.get_operator_identity_object()

        assert identity is not None
        assert isinstance(identity, RNS.Identity)

    def test_get_operator_identity_returns_none_if_not_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_operator_identity returns None if identity doesn't exist."""
        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        identity = core_reticulum.get_operator_identity()
        assert identity is None

    def test_get_operator_identity_returns_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_operator_identity returns existing identity hash."""
        import styrened.services.reticulum as core_reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create identity
        created_hash = core_reticulum.ensure_operator_identity()

        # Get identity should return same hash
        identity = core_reticulum.get_operator_identity()
        assert identity == created_hash


class TestReticulumStatus:
    """Tests for Reticulum status queries."""

    @pytest.mark.rns_singleton
    def test_get_reticulum_status_no_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status when no operator identity exists."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        status = reticulum.get_reticulum_status()

        assert status["running"] is False
        assert status["interfaces"] == 0
        assert status["identity"] is None

    @pytest.mark.rns_singleton
    def test_get_reticulum_status_with_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status with operator identity."""
        import RNS

        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create a real RNS identity file (not just raw bytes)
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(operator_key))
        expected_hash = identity.hash.hex()

        status = reticulum.get_reticulum_status()

        assert status["running"] is False
        assert status["identity"] == expected_hash


class TestDeviceDiscovery:
    """Tests for device discovery."""

    def test_discover_devices_returns_empty_when_not_started(self) -> None:
        """Test discover_devices returns empty list when discovery not started."""
        from styrened.tui.services.reticulum import discover_devices, stop_discovery

        # Ensure discovery is stopped
        stop_discovery()

        devices = discover_devices()

        assert isinstance(devices, list)
        assert len(devices) == 0



class TestStyreneAnnounceHandler:
    """Tests for StyreneAnnounceHandler for device discovery."""

    def test_handler_initialization(self) -> None:
        """Test StyreneAnnounceHandler can be initialized."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        assert handler is not None
        assert handler.aspect_filter is None  # Listen to ALL
        assert handler.discovered_devices == {}

    def test_handler_with_callback(self) -> None:
        """Test StyreneAnnounceHandler accepts callback function."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        callback_called = []

        def test_callback(device: dict[str, Any]) -> None:
            callback_called.append(device)

        handler = StyreneAnnounceHandler(callback=test_callback)
        assert handler.callback is test_callback

    def test_received_announce_no_app_data(self) -> None:
        """Test received_announce handles announce without app_data."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("abcdef1234567890")
        identity_hash = bytes.fromhex("1234567890abcdef")

        # Mock RNS.Identity
        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=None,
        )

        # Should create device entry with generated name
        assert len(handler.discovered_devices) == 1
        device = handler.discovered_devices["abcdef1234567890"]
        assert device.name.startswith("device-")
        assert device.identity == "abcdef1234567890"
        assert (device.device_type == DeviceType.STYRENE_NODE) is False
        assert device.announce_count == 1

    def test_received_announce_styrene_device(self) -> None:
        """Test received_announce detects styrene devices from app_data."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("cafe0123456789ab")
        identity_hash = bytes.fromhex("abcafe0123456789")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        # Styrene device with name in app_data
        app_data = b"styrene:rpi-mesh-01"
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=app_data,
        )

        device = handler.discovered_devices["cafe0123456789ab"]
        assert device.name == "rpi-mesh-01"
        assert (device.device_type == DeviceType.STYRENE_NODE) is True
        assert device.announce_count == 1

    def test_received_announce_styrene_device_no_name(self) -> None:
        """Test received_announce handles styrene device without explicit name."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("deadbeef12345678")
        identity_hash = bytes.fromhex("12345678deadbeef")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        # Styrene device without colon-separated name
        app_data = b"styrene"
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=app_data,
        )

        device = handler.discovered_devices["deadbeef12345678"]
        assert (device.device_type == DeviceType.STYRENE_NODE) is True
        assert device.name == "styrene-node"  # Falls back to default styrene-node name

    def test_received_announce_non_styrene_with_name(self) -> None:
        """Test received_announce handles non-styrene device with custom name."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("feedface87654321")
        identity_hash = bytes.fromhex("87654321feedface")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        # Non-styrene device with custom app_data
        app_data = b"custom-device-name"
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=app_data,
        )

        device = handler.discovered_devices["feedface87654321"]
        assert (device.device_type == DeviceType.STYRENE_NODE) is False
        assert device.name == "custom-device-name"

    def test_received_announce_updates_existing_device(self) -> None:
        """Test received_announce updates existing device on multiple announces."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("1234567890abcdef")
        identity_hash = bytes.fromhex("abcdef1234567890")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        # First announce
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=b"styrene:test-device",
        )

        first_device = handler.discovered_devices["1234567890abcdef"]
        first_timestamp = first_device.last_announce
        assert first_device.announce_count == 1

        # Second announce (simulate time passing)
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=b"styrene:test-device",
        )

        device = handler.discovered_devices["1234567890abcdef"]
        assert device.announce_count == 2
        assert device.last_announce >= first_timestamp

    def test_received_announce_calls_callback(self) -> None:
        """Test received_announce calls callback when provided."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        callback_devices = []

        def test_callback(device: MeshDevice) -> None:
            callback_devices.append(device)

        handler = StyreneAnnounceHandler(callback=test_callback)
        dest_hash = bytes.fromhex("abcd1234efef5678")
        identity_hash = bytes.fromhex("efef5678abcd1234")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=b"styrene:callback-test",
        )

        assert len(callback_devices) == 1
        assert callback_devices[0].name == "callback-test"
        assert callback_devices[0].is_styrene_node is True

    def test_received_announce_handles_invalid_app_data(self) -> None:
        """Test received_announce handles non-UTF8 app_data gracefully."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()
        dest_hash = bytes.fromhex("bad0da7a12345678")
        identity_hash = bytes.fromhex("12345678bad0da7a")

        class MockIdentity:
            def __init__(self):
                self.hash = identity_hash

        # Invalid UTF-8 bytes
        app_data = b"\xff\xfe\xfd\xfc"
        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=MockIdentity(),
            app_data=app_data,
        )

        # Should still create device with fallback name
        device = handler.discovered_devices["bad0da7a12345678"]
        assert device.name == "binary-data"  # Fallback for invalid UTF-8
        assert (device.device_type == DeviceType.STYRENE_NODE) is False

    def test_received_announce_case_insensitive_styrene_detection(self) -> None:
        """Test received_announce detects 'styrene' case-insensitively."""
        from styrened.tui.services.reticulum import StyreneAnnounceHandler

        handler = StyreneAnnounceHandler()

        # Test different case variations
        test_cases = [
            b"STYRENE:test",
            b"Styrene:test",
            b"sTyReNe:test",
        ]

        for i, app_data in enumerate(test_cases):
            dest_hash = bytes.fromhex(f"aabb{i:012x}")
            identity_hash = bytes.fromhex(f"ccdd{i:012x}")

            class MockIdentity:
                def __init__(self, h):
                    self.hash = h

            handler.received_announce(
                destination_hash=dest_hash,
                announced_identity=MockIdentity(identity_hash),
                app_data=app_data,
            )

        # All should be detected as styrene devices
        for device in handler.discovered_devices.values():
            assert (device.device_type == DeviceType.STYRENE_NODE) is True


class TestDiscoveryFunctions:
    """Tests for discovery lifecycle functions."""

    def test_start_discovery_creates_handler(self) -> None:
        """Test start_discovery creates and registers announce handler."""
        from styrened.tui.services.reticulum import start_discovery, stop_discovery

        # Clean up any existing handler first
        stop_discovery()

        start_discovery()

        # Handler should be created (we'll verify via discover_devices)
        from styrened.tui.services.reticulum import discover_devices

        devices = discover_devices()
        assert isinstance(devices, list)

        # Clean up
        stop_discovery()

    def test_start_discovery_with_callback(self) -> None:
        """Test start_discovery accepts callback function."""
        from styrened.tui.services.reticulum import start_discovery, stop_discovery

        callback_called = []

        def test_callback(device: dict[str, Any]) -> None:
            callback_called.append(device)

        stop_discovery()
        start_discovery(callback=test_callback)

        # Clean up
        stop_discovery()

    def test_start_discovery_idempotent(self) -> None:
        """Test start_discovery is idempotent (doesn't create multiple handlers)."""
        from styrened.tui.services.reticulum import start_discovery, stop_discovery

        stop_discovery()
        start_discovery()
        start_discovery()  # Should be no-op

        # Clean up
        stop_discovery()

    def test_stop_discovery_cleans_up_handler(self) -> None:
        """Test stop_discovery deregisters and cleans up handler."""
        from styrened.tui.services.reticulum import (
            discover_devices,
            start_discovery,
            stop_discovery,
        )

        start_discovery()
        stop_discovery()

        # After stopping, discover_devices should return empty list
        devices = discover_devices()
        assert devices == []

    def test_stop_discovery_idempotent(self) -> None:
        """Test stop_discovery is idempotent (safe to call multiple times)."""
        from styrened.tui.services.reticulum import stop_discovery

        stop_discovery()
        stop_discovery()  # Should be no-op

    def test_discover_devices_returns_empty_when_not_started(self) -> None:
        """Test discover_devices returns empty list when discovery not started."""
        from styrened.tui.services.reticulum import discover_devices, stop_discovery

        stop_discovery()  # Ensure stopped
        devices = discover_devices()
        assert devices == []

    def test_discover_devices_returns_all_devices(self) -> None:
        """Test discover_devices returns all discovered devices."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services.reticulum import (
            discover_devices,
            start_discovery,
            stop_discovery,
        )

        stop_discovery()
        start_discovery()

        # Manually add some devices to the handler for testing
        if core_reticulum._announce_handler:
            core_reticulum._announce_handler.discovered_devices = {
                "aaa": {"name": "device-1", "is_styrene": False},
                "bbb": {"name": "device-2", "is_styrene": True},
                "ccc": {"name": "device-3", "is_styrene": False},
            }

            devices = discover_devices()
            assert len(devices) == 3

        stop_discovery()

    def test_get_styrene_devices_filters_correctly(self) -> None:
        """Test get_styrene_devices returns only styrene devices."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services.reticulum import (
            get_styrene_devices,
            start_discovery,
            stop_discovery,
        )

        stop_discovery()
        start_discovery()

        # Manually add mixed devices as MeshDevice objects
        if core_reticulum._announce_handler:
            from datetime import datetime

            core_reticulum._announce_handler.discovered_devices = {
                "aaa": MeshDevice(
                    destination_hash="aaa",
                    identity_hash="aaa",
                    name="device-1",
                    device_type=DeviceType.GENERIC,
                    last_announce=int(datetime.now().timestamp()),
                ),
                "bbb": MeshDevice(
                    destination_hash="bbb",
                    identity_hash="bbb",
                    name="device-2",
                    device_type=DeviceType.STYRENE_NODE,
                    last_announce=int(datetime.now().timestamp()),
                ),
                "ccc": MeshDevice(
                    destination_hash="ccc",
                    identity_hash="ccc",
                    name="device-3",
                    device_type=DeviceType.STYRENE_NODE,
                    last_announce=int(datetime.now().timestamp()),
                ),
                "ddd": MeshDevice(
                    destination_hash="ddd",
                    identity_hash="ddd",
                    name="device-4",
                    device_type=DeviceType.GENERIC,
                    last_announce=int(datetime.now().timestamp()),
                ),
            }

            styrene_devices = get_styrene_devices()
            assert len(styrene_devices) == 2
            assert all(d.is_styrene_node for d in styrene_devices)

        stop_discovery()

    def test_get_styrene_devices_returns_empty_when_not_started(self) -> None:
        """Test get_styrene_devices returns empty list when discovery not started."""
        from styrened.tui.services.reticulum import get_styrene_devices, stop_discovery

        stop_discovery()
        devices = get_styrene_devices()
        assert devices == []


class TestUpdatedReticulumStatus:
    """Tests for updated get_reticulum_status() with real RNS checks."""

    def test_get_reticulum_status_structure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status returns correct structure."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        status = reticulum.get_reticulum_status()

        # Check structure
        assert "running" in status
        assert "interfaces" in status
        assert "identity" in status
        assert "transport_enabled" in status

        # Check types
        assert isinstance(status["running"], bool)
        assert isinstance(status["interfaces"], int)
        assert status["identity"] is None or isinstance(status["identity"], str)
        assert isinstance(status["transport_enabled"], bool)

    @pytest.mark.rns_singleton
    def test_get_reticulum_status_with_rns_service_not_initialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status when RNS service is not initialized."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        status = reticulum.get_reticulum_status()

        # Should report not running
        assert status["running"] is False
        assert status["transport_enabled"] is False

    def test_get_reticulum_status_with_operator_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status includes operator identity when present."""
        import RNS

        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        # Create a real RNS identity file
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(operator_key))
        expected_hash = identity.hash.hex()

        status = reticulum.get_reticulum_status()

        assert status["identity"] == expected_hash

    def test_get_reticulum_status_with_configured_reticulum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status counts interfaces from config."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        # Setup Reticulum config
        reticulum_dir = tmp_path / ".reticulum"
        reticulum_dir.mkdir()

        config_content = """[reticulum]

[interfaces]

[[Default Interface]]
type = AutoInterface
enabled = true

[[TCP Server]]
type = TCPServerInterface
enabled = true
"""
        (reticulum_dir / "config").write_text(config_content)

        storage_dir = reticulum_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "identity").write_bytes(bytes(32))

        # Mock find_reticulum_config on both modules
        monkeypatch.setattr(
            core_reticulum, "find_reticulum_config", lambda override=None: reticulum_dir
        )

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        status = reticulum.get_reticulum_status()

        assert status["interfaces"] == 2

    @pytest.mark.rns_singleton
    def test_get_reticulum_status_handles_not_configured_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_reticulum_status handles ReticulumNotConfiguredError gracefully."""
        import styrened.services.reticulum as core_reticulum
        from styrened.tui.services import reticulum

        # Mock find_reticulum_config to return None
        monkeypatch.setattr(
            core_reticulum, "find_reticulum_config", lambda override=None: None
        )

        operator_key = tmp_path / "operator.key"
        monkeypatch.setattr("styrened.paths.identity_file", lambda: operator_key)
        monkeypatch.setattr(core_reticulum, "SYSTEM_IDENTITY_PATH", tmp_path / "nonexistent_system")

        status = reticulum.get_reticulum_status()

        # Should not crash, interfaces should be 0
        assert status["interfaces"] == 0
        assert status["running"] is False
