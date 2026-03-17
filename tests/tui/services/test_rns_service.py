"""Tests for RNS service lifecycle management.

These tests verify:
- RNS initialization with optional config override
- Singleton pattern for RNSService
- Operator destination creation
- Transport detection
- Graceful shutdown
- Error handling when RNS fails to initialize
"""
from __future__ import annotations

from pathlib import Path

import pytest

from styrened.services.rns_service import RNSService, get_rns_service


class TestRNSServiceSingleton:
    """Tests for RNSService singleton pattern."""

    @pytest.mark.rns_singleton
    def test_get_rns_service_returns_instance(self) -> None:
        """Test get_rns_service returns RNSService instance."""
        service = get_rns_service()
        assert isinstance(service, RNSService)

    def test_get_rns_service_returns_same_instance(self) -> None:
        """Test get_rns_service returns same instance (singleton)."""
        service1 = get_rns_service()
        service2 = get_rns_service()
        assert service1 is service2


class TestRNSServiceInitialization:
    """Tests for RNS initialization."""

    def test_service_starts_not_initialized(self) -> None:
        """Test service starts in uninitialized state."""
        service = RNSService()
        assert service.is_initialized is False
        assert service.reticulum is None

    @pytest.mark.rns_singleton
    def test_initialize_creates_reticulum_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test initialize creates RNS.Reticulum instance."""
        import RNS

        # Create a minimal Reticulum config for testing
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()

        # Write minimal config
        config_content = """[reticulum]
enable_transport = false
share_instance = false

[interfaces]

[[Test Interface]]
type = AutoInterface
enabled = true
"""
        (config_dir / "config").write_text(config_content)

        # Create storage directory with identity
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        # Initialize with test config
        service = RNSService()
        result = service.initialize(config_override=config_dir)

        assert result is True
        assert service.is_initialized is True
        assert service.reticulum is not None

    def test_initialize_returns_false_on_failure(self) -> None:
        """Test initialize returns False when RNS fails to start."""
        from pathlib import Path

        # Try to initialize with nonexistent config
        service = RNSService()
        result = service.initialize(config_override=Path("/nonexistent"))

        assert result is False
        assert service.is_initialized is False
        assert service.reticulum is None

    @pytest.mark.rns_singleton
    def test_initialize_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test multiple initialize calls don't break the service."""
        import RNS

        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        result1 = service.initialize(config_override=config_dir)
        result2 = service.initialize(config_override=config_dir)

        assert result1 is True
        assert result2 is True
        assert service.is_initialized is True


class TestRNSServiceDestination:
    """Tests for operator destination creation."""

    def test_create_operator_destination_requires_initialization(self) -> None:
        """Test create_operator_destination returns None if not initialized."""
        import RNS

        service = RNSService()
        identity = RNS.Identity(create_keys=True)

        destination = service.create_operator_destination(
            identity, app_name="styrene.tui", aspect="operator"
        )

        assert destination is None

    @pytest.mark.rns_singleton
    def test_create_operator_destination_creates_destination(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test create_operator_destination creates RNS.Destination."""
        import RNS

        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        service.initialize(config_override=config_dir)

        destination = service.create_operator_destination(
            identity, app_name="styrene_tui", aspect="operator"
        )

        assert destination is not None
        assert isinstance(destination, RNS.Destination)

    @pytest.mark.rns_singleton
    def test_create_operator_destination_handles_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test create_operator_destination handles errors gracefully."""
        import RNS

        # Setup test config
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        service.initialize(config_override=config_dir)

        # Try with invalid parameters (None identity should fail)
        destination = service.create_operator_destination(
            None,
            app_name="styrene.tui",
            aspect="operator",  # type: ignore
        )

        assert destination is None


class TestRNSServiceDestinationCaching:
    """Tests for destination caching functionality."""

    def test_destination_cache_key_format(self) -> None:
        """Test that cache key uses correct format: app_name.aspect."""
        from unittest.mock import MagicMock, patch

        import RNS

        service = RNSService()
        # Mock as initialized
        service._initialized = True
        service._reticulum = MagicMock()

        identity = RNS.Identity(create_keys=True)

        # Mock RNS.Destination to avoid actual creation
        with patch("RNS.Destination") as mock_dest:
            mock_dest.return_value = MagicMock()
            mock_dest.IN = 0x02
            mock_dest.SINGLE = 0x00

            service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )

            # Verify cache key format
            assert "styrene.tui.operator" in service._destinations

    def test_destination_caching_returns_same_instance(self) -> None:
        """Test that calling create_operator_destination twice returns cached instance."""
        from unittest.mock import MagicMock, patch

        import RNS

        service = RNSService()
        # Mock as initialized
        service._initialized = True
        service._reticulum = MagicMock()

        identity = RNS.Identity(create_keys=True)

        # Mock RNS.Destination
        mock_destination = MagicMock()
        with patch("RNS.Destination", return_value=mock_destination) as mock_dest_class:
            mock_dest_class.IN = 0x02
            mock_dest_class.SINGLE = 0x00

            # First call - should create
            dest1 = service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )

            # Second call - should return cached
            dest2 = service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )

            # Both should be the same instance
            assert dest1 is dest2
            # RNS.Destination should only be called once
            assert mock_dest_class.call_count == 1

    def test_clear_destinations_removes_entries(self) -> None:
        """Test that clear_destinations removes all cached destinations."""
        from unittest.mock import MagicMock, patch

        import RNS

        service = RNSService()
        # Mock as initialized
        service._initialized = True
        service._reticulum = MagicMock()

        identity = RNS.Identity(create_keys=True)

        # Mock RNS.Destination
        with patch("RNS.Destination") as mock_dest:
            mock_dest.return_value = MagicMock()
            mock_dest.IN = 0x02
            mock_dest.SINGLE = 0x00

            # Create some destinations
            service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )
            service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="lxmf"
            )

            # Verify destinations are cached
            assert len(service._destinations) == 2

            # Clear destinations
            service.clear_destinations()

            # Verify cache is empty
            assert len(service._destinations) == 0

    def test_get_or_create_destination_uses_cache(self) -> None:
        """Test that get_or_create_destination uses the cache."""
        from unittest.mock import MagicMock, patch

        import RNS

        service = RNSService()
        # Mock as initialized
        service._initialized = True
        service._reticulum = MagicMock()

        identity = RNS.Identity(create_keys=True)

        # Mock RNS.Destination
        mock_destination = MagicMock()
        with patch("RNS.Destination", return_value=mock_destination) as mock_dest_class:
            mock_dest_class.IN = 0x02
            mock_dest_class.SINGLE = 0x00

            # Use get_or_create_destination
            dest1 = service.get_or_create_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )
            dest2 = service.get_or_create_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )

            # Both should be the same instance
            assert dest1 is dest2
            # RNS.Destination should only be called once
            assert mock_dest_class.call_count == 1

    def test_shutdown_clears_destination_cache(self) -> None:
        """Test that shutdown clears the destination cache."""
        from unittest.mock import MagicMock, patch

        import RNS

        service = RNSService()
        # Mock as initialized
        service._initialized = True
        service._reticulum = MagicMock()

        identity = RNS.Identity(create_keys=True)

        # Mock RNS.Destination
        with patch("RNS.Destination") as mock_dest:
            mock_dest.return_value = MagicMock()
            mock_dest.IN = 0x02
            mock_dest.SINGLE = 0x00

            # Create a destination
            service.create_operator_destination(
                identity, app_name="styrene.tui", aspect="operator"
            )

            # Verify destination is cached
            assert len(service._destinations) == 1

            # Shutdown
            service.shutdown()

            # Verify cache is empty
            assert len(service._destinations) == 0


class TestRNSServiceTransport:
    """Tests for transport detection."""

    def test_is_transport_enabled_returns_false_when_not_initialized(self) -> None:
        """Test is_transport_enabled returns False if not initialized."""
        service = RNSService()
        assert service.is_transport_enabled() is False

    @pytest.mark.rns_singleton
    def test_is_transport_enabled_detects_transport(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test is_transport_enabled returns correct transport status."""
        import RNS

        # Create config with transport disabled
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        service.initialize(config_override=config_dir)

        # Should return False for disabled transport
        assert service.is_transport_enabled() is False


class TestRNSServiceShutdown:
    """Tests for service shutdown."""

    def test_shutdown_when_not_initialized(self) -> None:
        """Test shutdown works when service never initialized."""
        service = RNSService()
        # Should not raise exception
        service.shutdown()
        assert service.is_initialized is False

    @pytest.mark.rns_singleton
    def test_shutdown_cleans_up_reticulum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test shutdown cleans up RNS.Reticulum instance."""
        import RNS

        # Setup and initialize
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        service.initialize(config_override=config_dir)

        # Shutdown
        service.shutdown()

        assert service.is_initialized is False
        assert service.reticulum is None

    @pytest.mark.rns_singleton
    def test_shutdown_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test multiple shutdown calls don't break the service."""
        import RNS

        # Setup and initialize
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        service = RNSService()
        service.initialize(config_override=config_dir)

        # Shutdown twice
        service.shutdown()
        service.shutdown()

        assert service.is_initialized is False


class TestOutboundPacketErrorFilter:
    """Tests for outbound packet error filtering functionality."""

    def test_filter_installed_on_initialize(self) -> None:
        """Test that RNS.log is monkey-patched during initialize."""
        from unittest.mock import patch


        service = RNSService()

        # Verify filter not installed initially
        assert service._outbound_error_filter_installed is False

        # Mock RNS.Reticulum to avoid singleton issues
        with patch("RNS.Reticulum"):
            # Initialize
            service.initialize()

            # Verify filter is installed
            assert service._outbound_error_filter_installed is True

        # Cleanup
        service.shutdown()

    def test_filter_suppresses_outbound_packet_errors(self) -> None:
        """Test that outbound packet errors are suppressed by the actual monkey-patch."""
        from unittest.mock import patch

        import RNS

        # Store the REAL original RNS.log before any patching
        original_rns_log = RNS.log

        # Capture calls to the original log function
        captured_calls = []

        def capturing_log(msg: str, level: int = 3) -> None:
            """Replacement for original RNS.log that captures calls."""
            captured_calls.append((msg, level))

        # Replace RNS.log with our capturing version
        RNS.log = capturing_log

        try:
            service = RNSService()

            # Mock RNS.Reticulum to avoid singleton issues
            with patch("RNS.Reticulum"):
                # Initialize - this installs the monkey-patch over our capturing_log
                service.initialize()

                # Verify filter was installed
                assert service._outbound_error_filter_installed is True

                # Clear any initialization logs
                captured_calls.clear()

                # Now call the monkey-patched RNS.log with filtered message
                RNS.log("No interfaces could process the outbound packet", RNS.LOG_ERROR)

                # Verify the filtered message did NOT reach our capturing_log
                # (the monkey-patch should have suppressed it)
                assert len(captured_calls) == 0, "Filtered message should not reach original log"

            service.shutdown()

        finally:
            # Restore the real original RNS.log
            RNS.log = original_rns_log

    def test_filter_allows_other_errors(self) -> None:
        """Test that other error messages pass through the actual monkey-patch."""
        from unittest.mock import patch

        import RNS

        # Store the real original RNS.log
        original_rns_log = RNS.log

        # Capture calls to the original log function
        captured_calls = []

        def capturing_log(msg: str, level: int = 3) -> None:
            """Replacement for original RNS.log that captures calls."""
            captured_calls.append((msg, level))

        # Replace RNS.log with our capturing version
        RNS.log = capturing_log

        try:
            service = RNSService()

            # Mock RNS.Reticulum to avoid singleton issues
            with patch("RNS.Reticulum"):
                # Initialize - installs the monkey-patch
                service.initialize()

                # Clear initialization logs
                captured_calls.clear()

                # Call with a non-filtered error message
                RNS.log("Some other error message", RNS.LOG_ERROR)

                # Verify the message passed through to our capturing_log
                assert len(captured_calls) == 1, "Non-filtered error should pass through"
                assert captured_calls[0][0] == "Some other error message"
                assert captured_calls[0][1] == RNS.LOG_ERROR

            service.shutdown()

        finally:
            # Restore the real original RNS.log
            RNS.log = original_rns_log

    def test_filter_allows_non_error_levels(self) -> None:
        """Test that non-ERROR log levels pass through the actual monkey-patch."""
        from unittest.mock import patch

        import RNS

        # Store the real original RNS.log
        original_rns_log = RNS.log

        # Capture calls to the original log function
        captured_calls = []

        def capturing_log(msg: str, level: int = 3) -> None:
            """Replacement for original RNS.log that captures calls."""
            captured_calls.append((msg, level))

        # Replace RNS.log with our capturing version
        RNS.log = capturing_log

        try:
            service = RNSService()

            # Mock RNS.Reticulum to avoid singleton issues
            with patch("RNS.Reticulum"):
                # Initialize - installs the monkey-patch
                service.initialize()

                # Clear initialization logs
                captured_calls.clear()

                # Call with the same message but at INFO level (not ERROR)
                RNS.log("No interfaces could process the outbound packet", RNS.LOG_INFO)

                # Verify the message passed through (filter only blocks ERROR level)
                assert len(captured_calls) == 1, "Non-ERROR level should pass through"
                assert "No interfaces could process the outbound packet" in captured_calls[0][0]
                assert captured_calls[0][1] == RNS.LOG_INFO

            service.shutdown()

        finally:
            # Restore the real original RNS.log
            RNS.log = original_rns_log

    def test_monkey_patch_preserves_signature(self) -> None:
        """Test that the monkey-patched RNS.log accepts same args as original."""
        from unittest.mock import patch

        import RNS

        # Store the real original RNS.log
        original_rns_log = RNS.log

        # Track calls with different argument patterns
        captured_calls = []

        def capturing_log(msg: str, level: int = 3) -> None:
            """Replacement for original RNS.log that captures calls."""
            captured_calls.append({"msg": msg, "level": level})

        # Replace RNS.log with our capturing version
        RNS.log = capturing_log

        try:
            service = RNSService()

            # Mock RNS.Reticulum to avoid singleton issues
            with patch("RNS.Reticulum"):
                # Initialize - installs the monkey-patch
                service.initialize()

                captured_calls.clear()

                # Test positional args
                RNS.log("Positional message", 3)
                assert len(captured_calls) == 1
                assert captured_calls[0]["msg"] == "Positional message"
                assert captured_calls[0]["level"] == 3

                captured_calls.clear()

                # Test keyword args
                RNS.log("Keyword message", level=5)
                assert len(captured_calls) == 1
                assert captured_calls[0]["msg"] == "Keyword message"
                assert captured_calls[0]["level"] == 5

                captured_calls.clear()

                # Test default level parameter
                RNS.log("Default level message")
                assert len(captured_calls) == 1
                assert captured_calls[0]["msg"] == "Default level message"
                assert captured_calls[0]["level"] == 3  # Default value

            service.shutdown()

        finally:
            # Restore the real original RNS.log
            RNS.log = original_rns_log

    def test_filter_idempotent(self) -> None:
        """Test that installing filter twice doesn't break."""
        from unittest.mock import patch


        service = RNSService()

        # Mock RNS.Reticulum
        with patch("RNS.Reticulum"):
            # Initialize twice
            service.initialize()
            service.initialize()

            # Should still be marked as installed
            assert service._outbound_error_filter_installed is True

        # Cleanup
        service.shutdown()

    def test_shutdown_does_not_remove_filter(self) -> None:
        """Test that filter remains after shutdown (permanent)."""
        from unittest.mock import patch


        service = RNSService()

        # Mock RNS.Reticulum
        with patch("RNS.Reticulum"):
            # Initialize
            service.initialize()
            assert service._outbound_error_filter_installed is True

            # Shutdown
            service.shutdown()

            # Filter flag remains set (filter is permanent)
            assert service._outbound_error_filter_installed is True

    @pytest.mark.rns_singleton
    def test_outbound_errors_suppressed_during_real_initialization(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Integration test: outbound errors are suppressed during real RNS initialization."""
        import RNS

        # Setup test config
        config_dir = tmp_path / ".reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        # Track RNS.log calls
        log_calls = []
        original_rns_log = RNS.log

        def tracking_log(msg: str, level: int = 3) -> None:
            log_calls.append((msg, level))
            # Don't call original to avoid actual logging

        # Replace RNS.log with tracking version
        RNS.log = tracking_log

        try:
            service = RNSService()
            service.initialize(config_override=config_dir)

            # Manually trigger the error that would be suppressed
            RNS.log("No interfaces could process the outbound packet", RNS.LOG_ERROR)

            # Verify the error was suppressed (not in log_calls)
            error_messages = [msg for msg, level in log_calls if level == RNS.LOG_ERROR]
            assert "No interfaces could process the outbound packet" not in error_messages

            # Cleanup
            service.shutdown()
        finally:
            # Restore original RNS.log
            RNS.log = original_rns_log
