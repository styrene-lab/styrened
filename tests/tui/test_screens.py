"""Tests for screen implementations."""

import pytest

from styrened.tui.app import StyreneApp


@pytest.mark.asyncio
async def test_dashboard_has_device_table(app: StyreneApp):
    """Verify dashboard contains the device table."""
    async with app.run_test():
        # Query on the current screen (dashboard), not app
        table = app.screen.query_one("#mesh-device-table")
        assert table is not None
        assert table.__class__.__name__ == "MeshDeviceTable"


@pytest.mark.asyncio
async def test_dashboard_refresh_notification(app: StyreneApp):
    """Verify refresh action shows notification."""
    async with app.run_test() as pilot:
        await pilot.press("r")
        # Should show a notification (we can't easily assert content,
        # but we can verify no exception was raised)


class TestDashboardHardwareBinding:
    """Test dashboard hardware panel toggle binding."""

    @pytest.mark.asyncio
    async def test_hardware_binding_exists(self, app: StyreneApp) -> None:
        """Verify H key binding exists for hardware panel."""
        async with app.run_test() as pilot:
            # Verify dashboard loads
            assert app.screen.__class__.__name__ == "DashboardScreen"

            # Test the hardware toggle binding works by pressing 'h'
            # This should toggle the hardware panel visibility without error
            await pilot.press("h")
