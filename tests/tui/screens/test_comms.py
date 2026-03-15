"""Tests for CommsScreen workspace structure, navigation, and capability gating."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from textual.widgets import Input, Static, TabbedContent, TabPane

from styrened.tui.app import StyreneApp
from styrened.tui.screens.base import BridgeUnavailableError
from styrened.tui.screens.comms import CommsScreen
from styrened.ui_state import CommsMode


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


class TestCommsScreenStructure:
    """Comms workspace should expose the planned aggregate shell."""

    def test_escape_binding_exists(self):
        screen = CommsScreen()
        escape_bindings = [b for b in screen.BINDINGS if b.key == "escape"]
        assert len(escape_bindings) == 1
        assert escape_bindings[0].action == "app.pop_screen"

    @pytest.mark.asyncio
    async def test_comms_screen_has_expected_modes(self):
        """CommsScreen renders all four mode tabs."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(CommsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, CommsScreen)

            title = screen.query_one("#comms-title", Static)
            assert "COMMS" in str(title.render())

            tabs = screen.query_one("#comms-tabs", TabbedContent)
            panes = list(screen.query(TabPane))
            pane_ids = {pane.id for pane in panes}

            assert tabs.active == CommsMode.DIRECT.value
            assert pane_ids == {
                CommsMode.DIRECT.value,
                CommsMode.ACTIVE.value,
                CommsMode.BRIDGES.value,
                CommsMode.PRESENCE.value,
            }

    @pytest.mark.asyncio
    async def test_comms_direct_tab_shows_no_sessions_by_default(self):
        """Direct tab should show 'No active direct sessions.' when no daemon."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(CommsScreen())
            await pilot.pause()

            screen = app.screen
            placeholder = screen.query_one("#comms-direct-placeholder", Static)
            assert "No active direct sessions" in str(placeholder.render())

    @pytest.mark.asyncio
    async def test_comms_bridges_shows_no_capabilities_by_default(self):
        """Bridges tab shows 'no capabilities' message when bridge is unavailable."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(CommsScreen())
            await pilot.pause()

            screen = app.screen
            placeholder = screen.query_one("#comms-bridges-placeholder", Static)
            assert not placeholder.has_class("hidden")
            # Yggdrasil/I2P sections should be hidden
            ygg = screen.query_one("#comms-yggdrasil-section")
            i2p = screen.query_one("#comms-i2p-section")
            assert ygg.has_class("hidden")
            assert i2p.has_class("hidden")

    @pytest.mark.asyncio
    async def test_comms_bridges_i2p_url_input_present(self):
        """I2P section contains a URL input widget."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(CommsScreen())
            await pilot.pause()

            screen = app.screen
            i2p_input = screen.query_one("#comms-i2p-url-input", Input)
            assert i2p_input is not None

    def test_comms_screen_inherits_styrene_screen(self):
        """CommsScreen must inherit StyreneScreen for shared lifecycle."""
        from styrened.tui.screens.base import StyreneScreen
        assert issubclass(CommsScreen, StyreneScreen)

    def test_loading_message(self):
        """_loading_message() returns a non-empty string."""
        screen = CommsScreen()
        assert "comms" in screen._loading_message().lower()


class TestCommsCapabilityGating:
    """Capability-gated sections appear/disappear based on daemon config."""

    def test_apply_capability_state_shows_yggdrasil_section(self):
        """Yggdrasil section becomes visible when yggdrasil_enabled=True."""
        screen = CommsScreen()

        ygg = MagicMock()
        ygg.has_class = MagicMock(return_value=True)
        i2p_sec = MagicMock()
        i2p_sec.has_class = MagicMock(return_value=True)
        placeholder = MagicMock()
        direct_ph = MagicMock()

        def query_one_side_effect(selector, *args):
            if selector == "#comms-direct-placeholder":
                return direct_ph
            if selector == "#comms-bridges-placeholder":
                return placeholder
            if selector == "#comms-yggdrasil-section":
                return ygg
            if selector == "#comms-i2p-section":
                return i2p_sec
            raise Exception(f"Unknown selector: {selector}")

        screen.query_one = query_one_side_effect

        screen._apply_capability_state(
            yggdrasil_enabled=True,
            i2p_enabled=False,
            active_links=0,
        )

        ygg.remove_class.assert_called_once_with("hidden")
        i2p_sec.add_class.assert_called_once_with("hidden")
        placeholder.add_class.assert_called_once_with("hidden")

    def test_apply_capability_state_shows_i2p_section(self):
        """I2P section becomes visible when i2p_enabled=True."""
        screen = CommsScreen()

        ygg = MagicMock()
        i2p_sec = MagicMock()
        placeholder = MagicMock()
        direct_ph = MagicMock()

        def query_one_side_effect(selector, *args):
            if selector == "#comms-direct-placeholder":
                return direct_ph
            if selector == "#comms-bridges-placeholder":
                return placeholder
            if selector == "#comms-yggdrasil-section":
                return ygg
            if selector == "#comms-i2p-section":
                return i2p_sec
            raise Exception(f"Unknown: {selector}")

        screen.query_one = query_one_side_effect

        screen._apply_capability_state(
            yggdrasil_enabled=False,
            i2p_enabled=True,
            active_links=0,
        )

        ygg.add_class.assert_called_once_with("hidden")
        i2p_sec.remove_class.assert_called_once_with("hidden")

    def test_apply_capability_state_shows_active_links_count(self):
        """Direct tab placeholder updates with active link count."""
        screen = CommsScreen()

        direct_ph = MagicMock()
        placeholder = MagicMock()
        ygg = MagicMock()
        i2p_sec = MagicMock()

        def query_one_side_effect(selector, *args):
            if selector == "#comms-direct-placeholder":
                return direct_ph
            if selector == "#comms-bridges-placeholder":
                return placeholder
            if selector == "#comms-yggdrasil-section":
                return ygg
            if selector == "#comms-i2p-section":
                return i2p_sec
            raise Exception(f"Unknown: {selector}")

        screen.query_one = query_one_side_effect

        screen._apply_capability_state(
            yggdrasil_enabled=False,
            i2p_enabled=False,
            active_links=3,
        )

        direct_ph.update.assert_called_once_with("3 active direct session(s).")

    def test_apply_capability_state_no_bridges_shows_placeholder(self):
        """Bridges 'no capabilities' placeholder is visible when neither bridge active."""
        screen = CommsScreen()

        direct_ph = MagicMock()
        placeholder = MagicMock()
        ygg = MagicMock()
        i2p_sec = MagicMock()

        def query_one_side_effect(selector, *args):
            if selector == "#comms-direct-placeholder":
                return direct_ph
            if selector == "#comms-bridges-placeholder":
                return placeholder
            if selector == "#comms-yggdrasil-section":
                return ygg
            if selector == "#comms-i2p-section":
                return i2p_sec
            raise Exception(f"Unknown: {selector}")

        screen.query_one = query_one_side_effect

        screen._apply_capability_state(
            yggdrasil_enabled=False,
            i2p_enabled=False,
            active_links=0,
        )

        placeholder.remove_class.assert_called_once_with("hidden")

    @pytest.mark.asyncio
    async def test_load_data_calls_get_core_config_and_status(self):
        """_load_data() calls bridge.get_core_config() and get_status()."""
        screen = CommsScreen()
        bridge = MagicMock()
        bridge.get_core_config = AsyncMock(return_value={
            "yggdrasil": {"mode": "adopt"},
            "i2p": {"mode": "disabled"},
        })
        bridge.get_status = AsyncMock(return_value=MagicMock(active_links=2))

        apply_mock = MagicMock()
        screen._apply_capability_state = apply_mock

        with patch.object(CommsScreen, "bridge", new_callable=PropertyMock, return_value=bridge):
            await screen._load_data()

        bridge.get_core_config.assert_awaited_once()
        bridge.get_status.assert_awaited_once()
        apply_mock.assert_called_once_with(
            yggdrasil_enabled=True,
            i2p_enabled=False,
            active_links=2,
        )

    @pytest.mark.asyncio
    async def test_load_data_handles_both_bridges_enabled(self):
        """Both Yggdrasil and I2P enabled → both sections visible."""
        screen = CommsScreen()
        bridge = MagicMock()
        bridge.get_core_config = AsyncMock(return_value={
            "yggdrasil": {"mode": "managed"},
            "i2p": {"mode": "adopt"},
        })
        bridge.get_status = AsyncMock(return_value=MagicMock(active_links=0))

        apply_mock = MagicMock()
        screen._apply_capability_state = apply_mock

        with patch.object(CommsScreen, "bridge", new_callable=PropertyMock, return_value=bridge):
            await screen._load_data()

        apply_mock.assert_called_once_with(
            yggdrasil_enabled=True,
            i2p_enabled=True,
            active_links=0,
        )

    @pytest.mark.asyncio
    async def test_load_data_gracefully_handles_missing_bridge(self):
        """No bridge → _apply_capability_state is never called."""
        screen = CommsScreen()
        apply_mock = MagicMock()
        screen._apply_capability_state = apply_mock

        with patch.object(
            CommsScreen, "bridge", new_callable=PropertyMock,
            side_effect=BridgeUnavailableError("no bridge"),
        ):
            await screen._load_data()

        apply_mock.assert_not_called()
