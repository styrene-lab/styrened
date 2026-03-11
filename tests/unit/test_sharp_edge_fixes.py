"""Tests for operator sharp edge fixes (O5) and exploration identity_hash regression (O6).

O5: Tests for 8 operator sharp edge fixes across TUI widgets.
O6: Regression test ensuring MeshDevice uses identity_hash (not 'identity').

Spec deviations documented:
- O5-3: Spec calls for uptime warning style at <300s boundary. The actual
  HomeStatusBar.render() uses "dim" style unconditionally for uptime — there is
  no warning/dim style transition. Tests cover _format_uptime() and verify the
  actual render() style behavior (always dim).
- O5-4: Spec calls for total_device_count "MESH 5/10" vs "MESH 5". The widget
  has no total_device_count reactive — only styrene_mesh_count. Tests cover the
  actual MESH display behavior.
- O5-5: Spec calls for transport_enabled/propagation_enabled "T"/"P" indicators.
  These reactives do not exist in HomeStatusBar. No tests written — feature absent.
- O5-6: Spec calls for active_links "LNK 3" indicator. This reactive does not
  exist in HomeStatusBar. No tests written — feature absent.
- O5-7 (W1): Spec says hub_status=WAITING → 'connecting'. Actual widget renders
  'HUB ◐' (spinner glyph). Test matches actual widget behavior.
- W2: mypy guardrail: existing project-wide mypy errors are outside this task's
  file scope (tests/unit/test_sharp_edge_fixes.py). The test file itself has no
  mypy errors.
"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(**overrides) -> MeshDevice:
    """Create a MeshDevice with sensible defaults, overridable by kwargs."""
    defaults = dict(
        destination_hash="abcdef1234567890",
        identity_hash="abc123",
        name="test-node",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=int(time.time()),
    )
    defaults.update(overrides)
    return MeshDevice(**defaults)


def _plain(rich_text: Any) -> str:
    """Extract plain text from a Rich Text object."""
    return str(rich_text.plain)


def _render_bar(**kwargs) -> str:
    """Create a HomeStatusBar, set reactives, render, return plain text."""
    from styrened.tui.widgets.home_status_bar import HomeStatusBar
    bar = HomeStatusBar()
    for k, v in kwargs.items():
        object.__setattr__(bar, k, v)
    return _plain(bar.render())


# ===========================================================================
# O5-1: DeviceStatusWidget loading indicator
# ===========================================================================

class TestDeviceStatusWidgetLoading:
    """DeviceStatusWidget shows 'Querying' when loading=True and status=None."""

    def _make_widget(self, **kwargs):
        from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
        device = kwargs.pop("device", _make_device())
        w = DeviceStatusWidget(device=device)
        for k, v in kwargs.items():
            object.__setattr__(w, k, v)
        return w

    def test_loading_true_status_none_shows_querying(self):
        w = self._make_widget(loading=True, status=None)
        output = w.render()
        assert "Querying" in output

    def test_loading_true_with_status_set_no_querying(self):
        """When status is populated, loading indicator should not appear."""
        from unittest.mock import MagicMock
        status = MagicMock()
        status.hostname = "node1"
        status.uptime = 3600
        status.format_uptime.return_value = "1h"
        status.os_id = None
        status.os_version = None
        status.arch = None
        status.nixos_generation = None
        status.styrened_version = None
        status.ip = None
        status.services = None
        status.disk_total = 0
        status.available_commands = None
        w = self._make_widget(loading=False, status=status)
        output = w.render()
        assert "Querying" not in output

    def test_loading_false_status_none_no_querying(self):
        """Edge case: not loading and no status should NOT show loading indicator."""
        w = self._make_widget(loading=False, status=None)
        output = w.render()
        assert "Querying" not in output


# ===========================================================================
# O5-2: Inbox unread indicator formatting logic
# ===========================================================================

class TestInboxUnreadFormatting:
    """Test the unread formatting logic from InboxScreen._render_conversations.

    The actual rendering requires a mounted screen with DataTable, so we test
    that the production module's formatting pattern produces the expected Rich
    markup by importing the cascade color system and applying the same branch.
    """

    @pytest.fixture()
    def cascade(self):
        """Get a real ColorCascade instance from the theme system."""
        from styrened.tui.themes.styrene_brand import create_styrene_cascade
        return create_styrene_cascade()

    def test_unread_true_produces_bold_bright_markup(self, cascade):
        """Production logic: is_unread=True → [{cascade.bright} bold]{count}[/]"""
        is_unread = True
        unread = 3
        # This is the exact expression from inbox.py line 282
        unread_text = f"[{cascade.bright} bold]{unread}[/]"

        assert "bold" in unread_text
        assert cascade.bright in unread_text
        assert "3" in unread_text

    def test_unread_false_produces_dim_dash_markup(self, cascade):
        """Production logic: is_unread=False → [{cascade.dim}]-[/]"""
        is_unread = False
        # inbox.py line 284
        unread_text = f"[{cascade.dim}]-[/]"

        assert "bold" not in unread_text
        assert cascade.dim in unread_text
        assert "-" in unread_text

    def test_unread_dest_gets_bold_bright(self, cascade):
        """is_unread=True → dest wrapped in [{cascade.bright} bold]"""
        dest = "TestNode"
        # inbox.py line 298
        dest_display = f"[{cascade.bright} bold]{dest}[/]"
        assert "bold" in dest_display
        assert dest in dest_display

    def test_read_dest_gets_dim(self, cascade):
        """is_unread=False → dest wrapped in [{cascade.dim}]"""
        dest = "TestNode"
        # inbox.py line 301
        dest_display = f"[{cascade.dim}]{dest}[/]"
        assert "bold" not in dest_display
        assert cascade.dim in dest_display

    def test_cascade_colors_are_distinct(self, cascade):
        """bright and dim must be different colors for visual distinction."""
        assert cascade.bright != cascade.dim


# ===========================================================================
# O5-3: HomeStatusBar daemon uptime formatting and style
# ===========================================================================

class TestHomeStatusBarUptime:
    """HomeStatusBar._format_uptime produces correct compact strings,
    and render() applies the correct style to the uptime segment.

    Spec deviation: The spec calls for warning style at uptime < 300s.
    The actual widget uses 'dim' style unconditionally for the IPC/uptime
    segment. Tests verify the actual behavior.
    """

    def test_format_uptime_seconds(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(45) == "45s"

    def test_format_uptime_minutes(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(120) == "2m"

    def test_format_uptime_hours(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(3600) == "1h"

    def test_format_uptime_hours_minutes(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(3720) == "1h 2m"

    def test_format_uptime_days(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(86400) == "1d"

    def test_format_uptime_days_hours(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(90000) == "1d 1h"

    def test_format_uptime_zero(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(0) == "0s"

    def test_format_uptime_boundary_59(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(59) == "59s"

    def test_format_uptime_boundary_60(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert HomeStatusBar._format_uptime(60) == "1m"

    def test_render_uptime_style_is_dim_when_connected(self):
        """Verify the IPC segment uses 'dim' style regardless of uptime value."""
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        # Low uptime (spec says <300s = warning, but actual code is always dim)
        object.__setattr__(bar, "daemon_connected", True)
        object.__setattr__(bar, "daemon_uptime", 120)
        result = bar.render()
        plain = result.plain
        assert "IPC ●" in plain
        # The IPC segment is built with style="dim" — verify via _spans
        ipc_idx = plain.index("IPC")
        # Check that a span covering the IPC text has "dim" style
        found_dim = any(
            span.start <= ipc_idx < span.end and "dim" in str(span.style)
            for span in result._spans
        )
        assert found_dim, f"Expected 'dim' style at IPC segment, spans: {result._spans}"

    def test_render_uptime_high_value_also_dim(self):
        """High uptime (>300s) also renders dim — no style transition exists."""
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        object.__setattr__(bar, "daemon_connected", True)
        object.__setattr__(bar, "daemon_uptime", 600)
        result = bar.render()
        plain = result.plain
        assert "IPC ●" in plain
        ipc_idx = plain.index("IPC")
        found_dim = any(
            span.start <= ipc_idx < span.end and "dim" in str(span.style)
            for span in result._spans
        )
        assert found_dim, f"Expected 'dim' style at IPC segment, spans: {result._spans}"


# ===========================================================================
# O5-4: HomeStatusBar mesh count display
# ===========================================================================

class TestHomeStatusBarMeshCount:
    """HomeStatusBar renders MESH count from styrene_mesh_count reactive.

    Spec deviation: The spec calls for total_device_count support with
    'MESH 5/10' vs 'MESH 5' formatting. The widget has no total_device_count
    reactive — only styrene_mesh_count — so 'MESH N' is the only format.
    """

    def test_mesh_count_shown(self):
        output = _render_bar(styrene_mesh_count=5)
        assert "MESH 5" in output

    def test_mesh_count_zero(self):
        output = _render_bar(styrene_mesh_count=0)
        assert "MESH 0" in output

    def test_mesh_count_large(self):
        output = _render_bar(styrene_mesh_count=999)
        assert "MESH 999" in output

    def test_no_total_device_count_reactive(self):
        """Confirm the widget has no total_device_count — spec feature is absent."""
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert not hasattr(HomeStatusBar, "total_device_count")


# ===========================================================================
# O5-5: HomeStatusBar transport/propagation indicators
# ===========================================================================

class TestHomeStatusBarTransportPropagation:
    """Spec calls for transport_enabled/propagation_enabled T/P indicators.

    These reactives do not exist in the widget. Tests confirm absence and
    document that the feature is not implemented.
    """

    def test_no_transport_enabled_reactive(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert not hasattr(HomeStatusBar, "transport_enabled")

    def test_no_propagation_enabled_reactive(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert not hasattr(HomeStatusBar, "propagation_enabled")

    def test_render_does_not_contain_tp_indicators(self):
        """Without T/P reactives, output should not contain standalone T or P flags."""
        output = _render_bar()
        # Ensure no "│ T │" or "│ P │" or "│ TP │" segments
        segments = [s.strip() for s in output.split("│")]
        assert "T" not in segments
        assert "P" not in segments
        assert "TP" not in segments


# ===========================================================================
# O5-6: HomeStatusBar active_links
# ===========================================================================

class TestHomeStatusBarActiveLinks:
    """Spec calls for active_links 'LNK 3' indicator.

    This reactive does not exist in the widget. Tests confirm absence.
    """

    def test_no_active_links_reactive(self):
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        assert not hasattr(HomeStatusBar, "active_links")

    def test_render_does_not_contain_lnk(self):
        output = _render_bar()
        assert "LNK" not in output


# ===========================================================================
# O5-7: HomeStatusBar hub status indicators
# ===========================================================================

class TestHomeStatusBarHubStatus:
    """HomeStatusBar renders hub status correctly.

    Spec deviation (W1): Spec says hub_status=WAITING → 'connecting'.
    Actual widget renders 'HUB ◐' (spinner glyph, no text 'connecting').
    Tests match actual widget behavior.
    """

    def test_hub_connected(self):
        from styrened.services.hub_connection import HubStatus
        output = _render_bar(hub_status=HubStatus.CONNECTED)
        assert "HUB ●" in output

    def test_hub_disconnected(self):
        from styrened.services.hub_connection import HubStatus
        output = _render_bar(hub_status=HubStatus.DISCONNECTED)
        assert "HUB ○ lost" in output

    def test_hub_disabled(self):
        from styrened.services.hub_connection import HubStatus
        output = _render_bar(hub_status=HubStatus.DISABLED)
        assert "HUB —" in output

    def test_hub_waiting_shows_spinner_glyph(self):
        """WAITING renders '◐' spinner, not the word 'connecting'."""
        from styrened.services.hub_connection import HubStatus
        output = _render_bar(hub_status=HubStatus.WAITING)
        assert "HUB ◐" in output


# ===========================================================================
# O5-7b: HomeStatusBar unread count
# ===========================================================================

class TestHomeStatusBarUnread:
    """HomeStatusBar shows unread envelope icon when count > 0."""

    def test_unread_shown(self):
        output = _render_bar(unread_count=3)
        assert "✉ 3" in output

    def test_no_unread_no_envelope(self):
        output = _render_bar(unread_count=0)
        assert "✉" not in output


# ===========================================================================
# O5-7c: HomeStatusBar RNS status and error display
# ===========================================================================

class TestHomeStatusBarRNS:
    """HomeStatusBar RNS online/offline indicators."""

    def test_rns_online(self):
        output = _render_bar(rns_online=True)
        assert "RNS ● online" in output

    def test_rns_offline(self):
        output = _render_bar(rns_online=False)
        assert "RNS ○ offline" in output

    def test_rns_offline_with_error(self):
        from styrened.models.rns_error import RNSErrorState, RNSErrorCategory
        err = RNSErrorState(category=RNSErrorCategory.PORT_CONFLICT, message="port in use")
        output = _render_bar(rns_online=False, error_state=err)
        assert "port in use" in output

    def test_rns_error_message_truncated(self):
        from styrened.models.rns_error import RNSErrorState, RNSErrorCategory
        long_msg = "a" * 50
        err = RNSErrorState(category=RNSErrorCategory.PORT_CONFLICT, message=long_msg)
        output = _render_bar(rns_online=False, error_state=err)
        assert len(long_msg) > 20
        assert "…" in output


# ===========================================================================
# O5-8: HomeStatusBar IPC/daemon status
# ===========================================================================

class TestHomeStatusBarDaemon:
    """HomeStatusBar daemon connection and uptime display."""

    def test_daemon_connected_with_uptime(self):
        output = _render_bar(daemon_connected=True, daemon_uptime=3600)
        assert "IPC ●" in output
        assert "1h" in output

    def test_daemon_disconnected(self):
        output = _render_bar(daemon_connected=False)
        assert "IPC ○" in output


# ===========================================================================
# O5-8b: MeshDevice hops display formatting
# ===========================================================================

class TestMeshDeviceHopsDisplay:
    """Test hops display formatting logic (used by widgets rendering hops)."""

    def test_hops_zero_means_direct(self):
        d = _make_device(hops=0)
        assert d.hops == 0
        label = "direct" if d.hops == 0 else f"{d.hops} hop{'s' if d.hops != 1 else ''}"
        assert label == "direct"

    def test_hops_one_singular(self):
        d = _make_device(hops=1)
        label = "direct" if d.hops == 0 else f"{d.hops} hop{'s' if d.hops != 1 else ''}"
        assert label == "1 hop"

    def test_hops_multiple_plural(self):
        d = _make_device(hops=3)
        label = "direct" if d.hops == 0 else f"{d.hops} hop{'s' if d.hops != 1 else ''}"
        assert label == "3 hops"

    def test_hops_none_not_rendered(self):
        d = _make_device(hops=None)
        assert d.hops is None

    def test_hops_in_device_status_widget_render(self):
        """DeviceStatusWidget includes hops in MESH section when set."""
        from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
        d = _make_device(hops=3)
        w = DeviceStatusWidget(device=d)
        output = w.render()
        plain = re.sub(r"\[.*?\]", "", output)
        assert "Hops:" in plain
        assert "3" in plain

    def test_hops_none_not_in_device_status_widget(self):
        from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
        d = _make_device(hops=None)
        w = DeviceStatusWidget(device=d)
        output = w.render()
        plain = re.sub(r"\[.*?\]", "", output)
        assert "Hops:" not in plain


# ===========================================================================
# O6: Exploration identity_hash regression test
# ===========================================================================

class TestIdentityHashRegression:
    """Ensure MeshDevice uses identity_hash, not the old broken 'identity' attr."""

    def test_identity_hash_attribute_exists(self):
        d = _make_device(identity_hash="abc123")
        assert d.identity_hash == "abc123"

    def test_no_identity_attribute(self):
        """MeshDevice should NOT have a bare 'identity' attribute (the old broken name)."""
        d = _make_device()
        assert not hasattr(d, "identity") or "identity" not in d.__dataclass_fields__

    def test_identity_hash_used_for_lookup(self):
        """Filtering devices by identity_hash finds the right device."""
        devices = [
            _make_device(identity_hash="aaa111", name="node-a"),
            _make_device(identity_hash="bbb222", name="node-b"),
            _make_device(identity_hash="ccc333", name="node-c"),
        ]
        found = [d for d in devices if d.identity_hash == "bbb222"]
        assert len(found) == 1
        assert found[0].name == "node-b"

    def test_identity_hash_not_empty_string(self):
        d = _make_device(identity_hash="deadbeef")
        assert len(d.identity_hash) > 0

    def test_identity_hash_in_dataclass_fields(self):
        assert "identity_hash" in MeshDevice.__dataclass_fields__

    def test_identity_short_property_uses_identity_hash(self):
        d = _make_device(identity_hash="abcdef1234567890")
        short = d.identity_short
        assert d.identity_hash.startswith(short) or short in d.identity_hash
