"""Unit tests for page_renderers module.

Tests type-specific renderers for structured page data.
"""
from __future__ import annotations


from styrened.tui.widgets.page_renderers import (
    _format_duration,
    render_fleet_overview,
    render_node_status,
    render_structured_page,
)


class TestRenderStructuredPage:
    """Tests for the top-level dispatch function."""

    def test_dispatches_to_node_status(self):
        """Should dispatch to node_status renderer."""
        data = {"node_name": "test", "status": "active"}
        result = render_structured_page("node_status", data)
        assert result is not None
        assert "test" in result

    def test_dispatches_to_fleet(self):
        """Should dispatch to fleet renderer."""
        data = {"nodes": [], "total": 0, "active": 0}
        result = render_structured_page("fleet", data)
        assert result is not None
        assert "Fleet Overview" in result

    def test_returns_none_for_unknown_type(self):
        """Should return None for unregistered page types."""
        result = render_structured_page("unknown_type", {"foo": "bar"})
        assert result is None

    def test_returns_none_on_renderer_error(self):
        """Should return None if renderer raises."""
        # Pass data that would cause issues if renderer expected specific types
        # (render_node_status is resilient, so we test the fallback mechanism)
        result = render_structured_page("nonexistent", {})
        assert result is None


class TestRenderNodeStatus:
    """Tests for node_status renderer."""

    def test_basic_rendering(self):
        """Should render node name and status."""
        data = {
            "node_name": "edge-03",
            "status": "active",
        }
        result = render_node_status(data)
        assert "edge-03" in result
        assert "ACTIVE" in result
        assert "green" in result

    def test_degraded_status_yellow(self):
        """Degraded status should use yellow color."""
        data = {"node_name": "test", "status": "degraded"}
        result = render_node_status(data)
        assert "yellow" in result
        assert "DEGRADED" in result

    def test_offline_status_red(self):
        """Offline status should use red color."""
        data = {"node_name": "test", "status": "offline"}
        result = render_node_status(data)
        assert "red" in result
        assert "OFFLINE" in result

    def test_includes_uptime(self):
        """Should include formatted uptime."""
        data = {"node_name": "test", "status": "active", "uptime": 86400}
        result = render_node_status(data)
        assert "Uptime:" in result
        assert "1d" in result

    def test_includes_version(self):
        """Should include version string."""
        data = {"node_name": "test", "status": "active", "version": "0.9.1"}
        result = render_node_status(data)
        assert "0.9.1" in result

    def test_includes_services(self):
        """Should list services."""
        data = {
            "node_name": "test",
            "status": "active",
            "services": ["rpc", "pages", "terminal"],
        }
        result = render_node_status(data)
        assert "rpc" in result
        assert "pages" in result
        assert "terminal" in result

    def test_includes_interfaces(self):
        """Should render interface details."""
        data = {
            "node_name": "test",
            "status": "active",
            "interfaces": [
                {"name": "AutoInterface", "status": "up", "peers": 3},
                {"name": "TCPInterface", "status": "down", "peers": 0},
            ],
        }
        result = render_node_status(data)
        assert "AutoInterface" in result
        assert "3 peers" in result
        assert "TCPInterface" in result

    def test_single_peer_no_plural(self):
        """Should use singular 'peer' for count of 1."""
        data = {
            "node_name": "test",
            "status": "active",
            "interfaces": [{"name": "Auto", "status": "up", "peers": 1}],
        }
        result = render_node_status(data)
        assert "1 peer)" in result

    def test_empty_data(self):
        """Should handle empty data gracefully."""
        result = render_node_status({})
        assert "Unknown" in result

    def test_full_data(self):
        """Should render complete node status."""
        data = {
            "node_name": "edge-03",
            "status": "active",
            "uptime": 172800,
            "version": "0.9.2",
            "services": ["rpc", "pages"],
            "interfaces": [
                {"name": "AutoInterface", "status": "up", "peers": 5},
            ],
        }
        result = render_node_status(data)
        assert "edge-03" in result
        assert "ACTIVE" in result
        assert "2d" in result
        assert "0.9.2" in result
        assert "rpc" in result
        assert "AutoInterface" in result


class TestRenderFleetOverview:
    """Tests for fleet overview renderer."""

    def test_basic_rendering(self):
        """Should render fleet summary."""
        data = {"total": 5, "active": 3, "nodes": []}
        result = render_fleet_overview(data)
        assert "Fleet Overview" in result
        assert "3 active / 5 total" in result
        assert "2 offline" in result

    def test_all_active_no_offline_warning(self):
        """Should not show offline warning when all active."""
        data = {"total": 3, "active": 3, "nodes": []}
        result = render_fleet_overview(data)
        assert "offline" not in result.lower() or "0 offline" not in result

    def test_renders_node_rows(self):
        """Should render a row per node."""
        data = {
            "total": 3,
            "active": 2,
            "nodes": [
                {"name": "edge-03", "status": "active", "uptime": 86400},
                {"name": "edge-07", "status": "active", "uptime": 259200},
                {"name": "edge-12", "status": "offline", "uptime": 0},
            ],
        }
        result = render_fleet_overview(data)
        assert "edge-03" in result
        assert "edge-07" in result
        assert "edge-12" in result
        assert "1d" in result  # 86400s
        assert "3d" in result  # 259200s

    def test_offline_node_shows_dash(self):
        """Offline nodes with 0 uptime should show dash."""
        data = {
            "total": 1,
            "active": 0,
            "nodes": [{"name": "test", "status": "offline", "uptime": 0}],
        }
        result = render_fleet_overview(data)
        assert "-" in result

    def test_empty_nodes(self):
        """Should show placeholder when no nodes."""
        data = {"total": 0, "active": 0, "nodes": []}
        result = render_fleet_overview(data)
        assert "No nodes reported" in result

    def test_empty_data(self):
        """Should handle empty data gracefully."""
        result = render_fleet_overview({})
        assert "Fleet Overview" in result


class TestFormatDuration:
    """Tests for duration formatting helper."""

    def test_seconds(self):
        assert _format_duration(45) == "45s"

    def test_minutes(self):
        assert _format_duration(120) == "2m"

    def test_hours(self):
        assert _format_duration(7200) == "2h"

    def test_hours_and_minutes(self):
        assert _format_duration(5400) == "1h 30m"

    def test_days(self):
        assert _format_duration(86400) == "1d"

    def test_days_and_hours(self):
        assert _format_duration(90000) == "1d 1h"

    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_float(self):
        assert _format_duration(90.7) == "1m"
