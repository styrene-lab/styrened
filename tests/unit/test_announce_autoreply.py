"""Unit tests for autoreply capability in announces.

Tests the _build_announce_data method and verifies the autoreply capability
is included/excluded based on config.
"""

from unittest.mock import MagicMock, patch

from styrened.models.config import CoreConfig


class TestBuildAnnounceData:
    """Verify _build_announce_data includes autoreply capability."""

    def _make_daemon(self, auto_reply_enabled: bool = False):  # noqa: ANN202
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.chat.auto_reply_enabled = auto_reply_enabled
        config.identity.display_name = "test-node"
        config.identity.icon = ""
        config.identity.short_name = "tnode"
        daemon = StyreneDaemon(config)
        daemon._operator_destination = MagicMock()
        return daemon

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_announce_includes_autoreply_when_enabled(self, mock_lxmf):
        """Announce data should include 'autoreply' capability when enabled."""
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.delivery_destination = MagicMock()
        lxmf_svc.delivery_destination.hash.hex.return_value = "deadbeef" * 4
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_enabled=True)
        data = daemon._build_announce_data()
        decoded = data.decode("utf-8")

        assert "autoreply" in decoded

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_announce_excludes_autoreply_when_disabled(self, mock_lxmf):
        """Announce data should NOT include 'autoreply' when disabled."""
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.delivery_destination = MagicMock()
        lxmf_svc.delivery_destination.hash.hex.return_value = "deadbeef" * 4
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_enabled=False)
        data = daemon._build_announce_data()
        decoded = data.decode("utf-8")

        assert "autoreply" not in decoded

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_announce_autoreply_coexists_with_other_caps(self, mock_lxmf):
        """Autoreply should coexist with other capabilities like hub, api."""
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.delivery_destination = MagicMock()
        lxmf_svc.delivery_destination.hash.hex.return_value = "deadbeef" * 4
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_enabled=True)
        daemon.config.api.enabled = True

        data = daemon._build_announce_data()
        decoded = data.decode("utf-8")
        parts = decoded.split(":")
        caps = parts[3]  # capabilities field

        assert "api" in caps
        assert "autoreply" in caps

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_announce_includes_short_name(self, mock_lxmf):
        """Announce data should include short_name (bug fix verification)."""
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.delivery_destination = MagicMock()
        lxmf_svc.delivery_destination.hash.hex.return_value = "deadbeef" * 4
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_enabled=False)
        data = daemon._build_announce_data()
        decoded = data.decode("utf-8")
        parts = decoded.split(":")

        # short_name should be in the 6th field (index 5)
        assert len(parts) >= 6
        assert parts[5] == "tnode"
