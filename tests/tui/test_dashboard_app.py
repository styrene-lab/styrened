"""Tests for the dashboard mode MVP."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, Mock, patch

import pytest

from styrened.tui.widgets.uptime_panel import UptimePanel


class TestDashboardFlag:
    """Tests for --dashboard CLI flag."""

    def test_dashboard_flag_parsed(self) -> None:
        """Verify --dashboard flag is recognized by argparse."""
        from styrened.tui.__main__ import main

        with (
            patch("sys.argv", ["styrene", "--dashboard"]),
            patch("styrened.tui.__main__.argparse.ArgumentParser.parse_args") as mock_parse,
        ):
            mock_args = argparse.Namespace(
                mode="standalone",
                port=None,
                peers=None,
                headless=False,
                api_port=None,
                config=None,
                remote=None,
                dashboard=True,
                reset=False,
                upgrade=False,
                restart_daemon=False,
            )
            mock_parse.return_value = mock_args

            with patch("styrened.tui.dashboard_app.LocalDashboardApp") as mock_app_cls:
                mock_app = MagicMock()
                mock_app_cls.return_value = mock_app
                main()
                mock_app_cls.assert_called_once()
                mock_app.run.assert_called_once()

    def test_dashboard_incompatible_with_headless(self) -> None:
        """Verify --dashboard and --headless are mutually exclusive."""
        from styrened.tui.__main__ import main

        with (
            patch("sys.argv", ["styrene", "--dashboard", "--headless"]),
            pytest.raises(SystemExit),
        ):
            main()

    def test_dashboard_incompatible_with_remote(self) -> None:
        """Verify --dashboard and --remote are mutually exclusive."""
        from styrened.tui.__main__ import main

        with (
            patch(
                "sys.argv",
                ["styrene", "--dashboard", "--remote", "http://example.com"],
            ),
            pytest.raises(SystemExit),
        ):
            main()


class TestLocalDashboardApp:
    """Tests for LocalDashboardApp instantiation."""

    def test_app_title(self) -> None:
        """Verify dashboard app has correct title."""
        from styrened.tui.dashboard_app import LocalDashboardApp

        assert LocalDashboardApp.TITLE == "STYRENE"
        assert LocalDashboardApp.SUB_TITLE == "Dashboard"

    def test_app_instantiation(self) -> None:
        """Verify dashboard app can be instantiated."""
        from styrened.tui.dashboard_app import LocalDashboardApp

        app = LocalDashboardApp()
        assert app.title == "STYRENE"
        assert app.sub_title == "Dashboard"
        assert hasattr(app, "config")
        assert hasattr(app, "_lifecycle")


class TestUptimePanel:
    """Tests for UptimePanel widget."""

    def test_format_duration_minutes(self) -> None:
        """Verify duration formatting for minutes only."""
        assert UptimePanel._format_duration(300) == "5m"

    def test_format_duration_hours_minutes(self) -> None:
        """Verify duration formatting for hours and minutes."""
        assert UptimePanel._format_duration(3900) == "1h 5m"

    def test_format_duration_days_hours_minutes(self) -> None:
        """Verify duration formatting for days, hours, minutes."""
        assert UptimePanel._format_duration(90300) == "1d 1h 5m"

    def test_format_duration_zero(self) -> None:
        """Verify duration formatting for zero seconds."""
        assert UptimePanel._format_duration(0) == "0m"

    def test_get_uptime_with_psutil(self) -> None:
        """Verify uptime retrieval via psutil."""
        import time

        panel = UptimePanel()

        with patch("psutil.boot_time", return_value=time.time() - 86400):
            result = panel._get_uptime()
            assert "1d" in result

    def test_get_uptime_fallback(self) -> None:
        """Verify graceful fallback when psutil unavailable."""
        panel = UptimePanel()

        with (
            patch.dict("sys.modules", {"psutil": None}),
            patch("builtins.__import__", side_effect=ImportError),
        ):
            result = panel._get_uptime()
            assert result == "unavailable"

    def test_get_load_average(self) -> None:
        """Verify load average retrieval."""
        panel = UptimePanel()

        with patch("os.getloadavg", return_value=(0.50, 1.25, 2.00)):
            result = panel._get_load_average()
            assert "0.50" in result
            assert "1.25" in result
            assert "2.00" in result

    def test_get_load_average_fallback(self) -> None:
        """Verify graceful fallback when getloadavg unavailable."""
        panel = UptimePanel()

        with patch("os.getloadavg", side_effect=OSError):
            result = panel._get_load_average()
            assert result == "unavailable"


class TestLocalDashboardScreen:
    """Tests for LocalDashboardScreen."""

    def test_screen_bindings(self) -> None:
        """Verify screen has expected keybindings."""
        from styrened.tui.screens.dashboard_local import LocalDashboardScreen

        binding_keys = [b.key for b in LocalDashboardScreen.BINDINGS]
        assert "q" in binding_keys
        assert "r" in binding_keys

    def test_screen_suspend_pauses_refresh_timer(self) -> None:
        """Suspending the local dashboard should pause refresh."""
        from styrened.tui.screens.dashboard_local import LocalDashboardScreen

        screen = LocalDashboardScreen()
        screen._refresh_timer = Mock()

        screen.on_screen_suspend(Mock())

        screen._refresh_timer.pause.assert_called_once_with()

    def test_screen_resume_resumes_refresh_timer(self) -> None:
        """Resuming the local dashboard should resume refresh and repaint."""
        from styrened.tui.screens.dashboard_local import LocalDashboardScreen

        screen = LocalDashboardScreen()
        screen._refresh_timer = Mock()
        screen._refresh_all = Mock()

        screen.on_screen_resume(Mock())

        screen._refresh_timer.resume.assert_called_once_with()
        screen._refresh_all.assert_called_once_with()

    def test_on_unmount_stops_refresh_timer(self) -> None:
        """Unmounting the local dashboard should stop refresh."""
        from styrened.tui.screens.dashboard_local import LocalDashboardScreen

        screen = LocalDashboardScreen()
        timer = Mock()
        screen._refresh_timer = timer

        screen.on_unmount()

        timer.stop.assert_called_once_with()
        assert screen._refresh_timer is None
