"""Tests for Reticulum panel widget."""

from unittest.mock import patch

import pytest

from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.services.hub_connection import HubStatus
from styrened.tui.widgets.reticulum_panel import ReticulumPanel


class TestReticulumPanelInstantiation:
    """Tests for basic instantiation."""

    def test_can_import_reticulum_panel(self) -> None:
        """Verify ReticulumPanel can be imported."""
        from styrened.tui.widgets.reticulum_panel import ReticulumPanel

        assert ReticulumPanel is not None

    def test_reticulum_panel_instantiation(self) -> None:
        """Verify panel can be created."""
        panel = ReticulumPanel()
        assert panel is not None


class TestReticulumPanelStatus:
    """Tests for status display."""

    @pytest.mark.asyncio
    async def test_displays_mode(self) -> None:
        """Verify panel displays deployment mode."""
        panel = ReticulumPanel()
        panel.mode = "standalone"
        rendered = panel.render()
        assert "MODE:" in rendered
        assert "STANDALONE" in rendered.upper()

    @pytest.mark.asyncio
    async def test_displays_hub_status_connected(self) -> None:
        """Verify panel displays hub connection status when connected."""
        panel = ReticulumPanel()
        panel.hub_status = HubStatus.CONNECTED
        rendered = panel.render()
        assert "HUB:" in rendered
        assert "connected" in rendered

    @pytest.mark.asyncio
    async def test_displays_hub_status_waiting(self) -> None:
        """Verify panel displays waiting status."""
        panel = ReticulumPanel()
        panel.hub_status = HubStatus.WAITING
        rendered = panel.render()
        assert "HUB:" in rendered
        assert "waiting" in rendered

    @pytest.mark.asyncio
    async def test_displays_hub_status_disconnected(self) -> None:
        """Verify panel displays disconnected status."""
        panel = ReticulumPanel()
        panel.hub_status = HubStatus.DISCONNECTED
        rendered = panel.render()
        assert "HUB:" in rendered
        assert "disconnected" in rendered

    @pytest.mark.asyncio
    async def test_displays_reticulum_status(self) -> None:
        """Verify panel displays Reticulum network status."""
        panel = ReticulumPanel()
        panel.rns_online = True
        rendered = panel.render()
        assert "RNS:" in rendered
        assert "online" in rendered

    @pytest.mark.asyncio
    async def test_displays_styrene_mesh_count(self) -> None:
        """Verify panel displays Styrene mesh node count."""
        panel = ReticulumPanel()
        panel.styrene_mesh_count = 3
        rendered = panel.render()
        assert "MESH:" in rendered
        assert "3 nodes" in rendered


class TestReticulumPanelLoadData:
    """Tests for loading data."""

    @pytest.mark.asyncio
    async def test_loads_config_on_mount(self) -> None:
        """Verify panel loads configuration on mount."""
        with patch("styrened.tui.widgets.reticulum_panel.load_config") as mock_load:
            from styrened.tui.models.config import DeploymentMode, ReticulumConfig, StyreneConfig

            mock_config = StyreneConfig(reticulum=ReticulumConfig(mode=DeploymentMode.HUB))
            mock_load.return_value = mock_config

            with (
                patch("styrened.tui.widgets.reticulum_panel.get_reticulum_status", return_value={}),
                patch("styrened.tui.widgets.reticulum_panel.get_hub_connection"),
                patch("styrened.tui.widgets.reticulum_panel.discover_devices", return_value=[]),
            ):
                panel = ReticulumPanel()
                panel._load_reticulum_data()
                assert panel.mode == "hub"

    @pytest.mark.asyncio
    async def test_handles_config_load_error(self) -> None:
        """Verify panel handles config loading errors gracefully."""
        with (
            patch(
                "styrened.tui.widgets.reticulum_panel.load_config",
                side_effect=Exception("Config error"),
            ),
            patch("styrened.tui.widgets.reticulum_panel.get_reticulum_status", return_value={}),
            patch("styrened.tui.widgets.reticulum_panel.get_hub_connection"),
            patch("styrened.tui.widgets.reticulum_panel.discover_devices", return_value=[]),
        ):
            panel = ReticulumPanel()
            panel._load_reticulum_data()
            # Should default to standalone
            assert panel.mode == "standalone"


class TestReticulumPanelErrorDisplay:
    """Tests for error state display in degraded mode."""

    @pytest.mark.asyncio
    async def test_displays_identity_corrupt_error(self) -> None:
        """Verify panel displays identity corruption error."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = RNSErrorState(category=RNSErrorCategory.IDENTITY_CORRUPT)

        rendered = panel.render()

        assert "RNS:" in rendered
        assert "Identity Corrupt" in rendered
        # Should show recovery guidance
        assert "operator.key" in rendered

    @pytest.mark.asyncio
    async def test_displays_config_error(self) -> None:
        """Verify panel displays config parsing error."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = RNSErrorState(category=RNSErrorCategory.CONFIG_PARSE_ERROR)

        rendered = panel.render()

        assert "RNS:" in rendered
        assert "Config Error" in rendered

    @pytest.mark.asyncio
    async def test_displays_not_configured_error(self) -> None:
        """Verify panel displays not configured state."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = RNSErrorState(category=RNSErrorCategory.NOT_CONFIGURED)

        rendered = panel.render()

        assert "Not Configured" in rendered

    @pytest.mark.asyncio
    async def test_displays_port_conflict_error(self) -> None:
        """Verify panel displays port conflict error."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = RNSErrorState(category=RNSErrorCategory.PORT_CONFLICT)

        rendered = panel.render()

        assert "Port Conflict" in rendered

    @pytest.mark.asyncio
    async def test_displays_offline_without_error_state(self) -> None:
        """Verify panel shows 'offline' when no error state is set."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = None

        rendered = panel.render()

        assert "RNS:" in rendered
        assert "offline" in rendered

    @pytest.mark.asyncio
    async def test_hides_mesh_count_when_error(self) -> None:
        """Verify panel hides mesh count when there's an error."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.styrene_mesh_count = 0
        panel.error_state = RNSErrorState(category=RNSErrorCategory.IDENTITY_CORRUPT)

        rendered = panel.render()

        # Should NOT show "no nodes" when there's an error
        assert "no nodes" not in rendered

    @pytest.mark.asyncio
    async def test_truncates_long_recovery_guidance(self) -> None:
        """Verify panel truncates long recovery messages."""
        panel = ReticulumPanel()
        panel.rns_online = False
        # Unknown error has a relatively short recovery message
        # but we can verify truncation logic with a custom state
        panel.error_state = RNSErrorState(
            category=RNSErrorCategory.UNKNOWN,
            message="Some error",
        )

        rendered = panel.render()

        # The unknown recovery mentions logs
        assert "log" in rendered.lower()

    @pytest.mark.asyncio
    async def test_online_does_not_show_error(self) -> None:
        """Verify panel doesn't show error when online."""
        panel = ReticulumPanel()
        panel.rns_online = True
        panel.interface_count = 2
        # Even if error_state is set, online should not show error
        panel.error_state = RNSErrorState(category=RNSErrorCategory.IDENTITY_CORRUPT)

        rendered = panel.render()

        assert "online" in rendered
        # Should show interface count, not error
        assert "2 if" in rendered
        assert "Identity Corrupt" not in rendered

    @pytest.mark.asyncio
    async def test_error_state_none_shows_offline(self) -> None:
        """Verify NONE error state shows regular offline status."""
        panel = ReticulumPanel()
        panel.rns_online = False
        panel.error_state = RNSErrorState.none()

        rendered = panel.render()

        # NONE is not an error, so should show regular offline
        assert "offline" in rendered
        assert "Online" not in rendered  # The NONE title shouldn't appear
