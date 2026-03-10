"""Tests for CommsScreen workspace structure and navigation semantics."""

from unittest.mock import patch

import pytest
from textual.widgets import Static, TabPane, TabbedContent

from styrened.tui.app import StyreneApp
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
    async def test_comms_screen_has_expected_modes_and_placeholders(self):
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

            assert "Direct synchronous communication" in str(
                screen.query_one("#comms-direct-placeholder", Static).render()
            )
            assert "Active sessions" in str(
                screen.query_one("#comms-active-placeholder", Static).render()
            )
            assert "Bridge-backed communication surfaces" in str(
                screen.query_one("#comms-bridges-placeholder", Static).render()
            )
            assert "Live presence and reachability" in str(
                screen.query_one("#comms-presence-placeholder", Static).render()
            )
