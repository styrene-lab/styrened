"""Unit tests for PQC session layer daemon integration."""

from unittest.mock import MagicMock, patch

from styrened.models.config import CoreConfig
from styrened.models.mesh_device import DeviceType, MeshDevice


class TestPQCServiceCreation:
    """PQC service initialization in daemon start()."""

    def test_pqc_service_created_when_available(self) -> None:
        """PQCSessionService is created when pqc_available() returns True."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        daemon = StyreneDaemon(config)

        # Simulate the protocol being available
        daemon._styrene_protocol = MagicMock()

        with patch("styrened.daemon.pqc_available", return_value=True):
            daemon._init_pqc_service()

        assert daemon._pqc_service is not None

    def test_pqc_service_none_when_unavailable(self) -> None:
        """PQCSessionService is None when liboqs is not installed."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        daemon = StyreneDaemon(config)
        daemon._styrene_protocol = MagicMock()

        with patch("styrened.daemon.pqc_available", return_value=False):
            daemon._init_pqc_service()

        assert daemon._pqc_service is None

    def test_pqc_service_none_when_disabled(self) -> None:
        """PQCSessionService is None when pqc.enabled is False."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = False
        daemon = StyreneDaemon(config)
        daemon._styrene_protocol = MagicMock()

        daemon._init_pqc_service()

        assert daemon._pqc_service is None

    def test_pqc_service_none_without_protocol(self) -> None:
        """PQCSessionService is None when StyreneProtocol is not available."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        daemon = StyreneDaemon(config)
        # _styrene_protocol is None by default

        with patch("styrened.daemon.pqc_available", return_value=True):
            daemon._init_pqc_service()

        assert daemon._pqc_service is None


class TestAutoInitiate:
    """PQC auto-initiation on device discovery."""

    def _make_device(self, device_type: DeviceType) -> MeshDevice:
        """Create a minimal MeshDevice for testing."""
        return MeshDevice(
            name="test-node",
            device_type=device_type,
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            last_announce=0,
        )

    def test_auto_initiate_on_styrene_device(self) -> None:
        """Discovery of a STYRENE_NODE triggers PQC initiation."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        config.pqc.auto_initiate = True
        daemon = StyreneDaemon(config)

        mock_pqc = MagicMock()
        daemon._pqc_service = mock_pqc

        device = self._make_device(DeviceType.STYRENE_NODE)
        daemon._maybe_initiate_pqc(device)

        mock_pqc.initiate_session_sync.assert_called_once_with(device.destination_hash)

    def test_no_auto_initiate_for_lxmf_peer(self) -> None:
        """LXMF_PEER discovery does NOT trigger PQC initiation."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        config.pqc.auto_initiate = True
        daemon = StyreneDaemon(config)

        mock_pqc = MagicMock()
        daemon._pqc_service = mock_pqc

        device = self._make_device(DeviceType.LXMF_PEER)
        daemon._maybe_initiate_pqc(device)

        mock_pqc.initiate_session_sync.assert_not_called()

    def test_no_auto_initiate_when_disabled(self) -> None:
        """auto_initiate=False prevents PQC initiation even for Styrene nodes."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        config.pqc.auto_initiate = False
        daemon = StyreneDaemon(config)

        mock_pqc = MagicMock()
        daemon._pqc_service = mock_pqc

        device = self._make_device(DeviceType.STYRENE_NODE)
        daemon._maybe_initiate_pqc(device)

        mock_pqc.initiate_session_sync.assert_not_called()

    def test_no_auto_initiate_without_pqc_service(self) -> None:
        """No crash when _pqc_service is None."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.pqc.enabled = True
        config.pqc.auto_initiate = True
        daemon = StyreneDaemon(config)

        device = self._make_device(DeviceType.STYRENE_NODE)
        daemon._maybe_initiate_pqc(device)  # Should not raise
