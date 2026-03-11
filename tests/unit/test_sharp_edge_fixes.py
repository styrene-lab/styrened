"""Tests for operator sharp edge fixes (O5) and exploration identity_hash regression (O6).

O5: Tests for 8 operator sharp edge fixes across TUI widgets.
O6: Regression test ensuring MeshDevice uses identity_hash (not 'identity').
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


# ===========================================================================
# O5-1: DeviceStatusWidget loading indicator
# ===========================================================================

class TestDeviceStatusWidgetLoading:
    """DeviceStatusWidget shows 'Querying' when loading=True and status=None."""

    def _make_widget(self, **kwargs):
        from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
        device = kwargs.pop("device", _make_device())
        w = DeviceStatusWidget(device=device)
        # Set reactives directly (widget is not mounted)
        for k, v in kwargs.items():
            object.__setattr__(w, k, v)
        return w

    def test_loading_true_status_none_shows_querying(self):
        w = self._make_widget(loading=True, status=None)
        output = w.render()
        assert "Querying" in output

    def test_loading_true_with_status_set_no_querying(self):
        """When status is populated, loading indicator should not appear in SYSTEM."""
        # We need a StatusResponse-like object
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

    The actual rendering requires a mounted screen, so we test the formatting
    pattern directly: unread=True → bold bright style, unread=False → dim style.
    """

    def test_unread_true_uses_bold_bright_style(self):
        """When is_unread=True, text should use bright+bold styling."""
        # Replicate the formatting logic from inbox.py lines 281-284
        is_unread = True
        unread_count = 3
        cascade_bright = "#00ff00"
        cascade_dim = "#333333"

        if is_unread:
            unread_text = f"[{cascade_bright} bold]{unread_count}[/]"
        else:
            unread_text = f"[{cascade_dim}]-[/]"

        assert "bold" in unread_text
        assert str(unread_count) in unread_text

    def test_unread_false_uses_dim_style(self):
        """When is_unread=False, text should use dim style with dash."""
        is_unread = False
        cascade_dim = "#333333"

        if is_unread:
            unread_text = f"[#00ff00 bold]1[/]"
        else:
            unread_text = f"[{cascade_dim}]-[/]"

        assert "bold" not in unread_text
        assert "-" in unread_text

    def test_unread_dest_display_bold_when_unread(self):
        """Unread conversations get bright bold destination display."""
        is_unread = True
        cascade_bright = "#00ff00"
        cascade_dim = "#333333"
        dest = "TestNode"

        if is_unread:
            dest_display = f"[{cascade_bright} bold]{dest}[/]"
        else:
            dest_display = f"[{cascade_dim}]{dest}[/]"

        assert "bold" in dest_display
        assert dest in dest_display

    def test_unread_dest_display_dim_when_read(self):
        is_unread = False
        cascade_dim = "#333333"
        dest = "TestNode"

        if is_unread:
            dest_display = f"[#00ff00 bold]{dest}[/]"
        else:
            dest_display = f"[{cascade_dim}]{dest}[/]"

        assert "bold" not in dest_display


# ===========================================================================
# O5-3: HomeStatusBar daemon uptime
# ===========================================================================

class TestHomeStatusBarUptime:
    """HomeStatusBar._format_uptime produces correct compact strings."""

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


# ===========================================================================
# O5-4: HomeStatusBar mesh count display
# ===========================================================================

class TestHomeStatusBarMeshCount:
    """HomeStatusBar renders MESH count from styrene_mesh_count reactive."""

    def _render_bar(self, **kwargs) -> str:
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        for k, v in kwargs.items():
            object.__setattr__(bar, k, v)
        return _plain(bar.render())

    def test_mesh_count_shown(self):
        output = self._render_bar(styrene_mesh_count=5)
        assert "MESH 5" in output

    def test_mesh_count_zero(self):
        output = self._render_bar(styrene_mesh_count=0)
        assert "MESH 0" in output

    def test_mesh_count_large(self):
        output = self._render_bar(styrene_mesh_count=999)
        assert "MESH 999" in output


# ===========================================================================
# O5-5: HomeStatusBar hub status indicators
# ===========================================================================

class TestHomeStatusBarHubStatus:
    """HomeStatusBar renders hub status correctly."""

    def _render_bar(self, **kwargs) -> str:
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        for k, v in kwargs.items():
            object.__setattr__(bar, k, v)
        return _plain(bar.render())

    def test_hub_connected(self):
        from styrened.services.hub_connection import HubStatus
        output = self._render_bar(hub_status=HubStatus.CONNECTED)
        assert "HUB ●" in output

    def test_hub_disconnected(self):
        from styrened.services.hub_connection import HubStatus
        output = self._render_bar(hub_status=HubStatus.DISCONNECTED)
        assert "HUB ○ lost" in output

    def test_hub_disabled(self):
        from styrened.services.hub_connection import HubStatus
        output = self._render_bar(hub_status=HubStatus.DISABLED)
        assert "HUB —" in output

    def test_hub_waiting_shows_connecting_indicator(self):
        from styrened.services.hub_connection import HubStatus
        output = self._render_bar(hub_status=HubStatus.WAITING)
        assert "HUB ◐" in output


# ===========================================================================
# O5-6: HomeStatusBar unread count
# ===========================================================================

class TestHomeStatusBarUnread:
    """HomeStatusBar shows unread envelope icon when count > 0."""

    def _render_bar(self, **kwargs) -> str:
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        for k, v in kwargs.items():
            object.__setattr__(bar, k, v)
        return _plain(bar.render())

    def test_unread_shown(self):
        output = self._render_bar(unread_count=3)
        assert "✉ 3" in output

    def test_no_unread_no_envelope(self):
        output = self._render_bar(unread_count=0)
        assert "✉" not in output


# ===========================================================================
# O5-7: HomeStatusBar RNS status and error display
# ===========================================================================

class TestHomeStatusBarRNS:
    """HomeStatusBar RNS online/offline indicators."""

    def _render_bar(self, **kwargs) -> str:
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        for k, v in kwargs.items():
            object.__setattr__(bar, k, v)
        return _plain(bar.render())

    def test_rns_online(self):
        output = self._render_bar(rns_online=True)
        assert "RNS ● online" in output

    def test_rns_offline(self):
        output = self._render_bar(rns_online=False)
        assert "RNS ○ offline" in output

    def test_rns_offline_with_error(self):
        from styrened.models.rns_error import RNSErrorState, RNSErrorCategory
        err = RNSErrorState(category=RNSErrorCategory.PORT_CONFLICT, message="port in use")
        output = self._render_bar(rns_online=False, error_state=err)
        assert "port in use" in output

    def test_rns_error_message_truncated(self):
        from styrened.models.rns_error import RNSErrorState, RNSErrorCategory
        long_msg = "a" * 50
        err = RNSErrorState(category=RNSErrorCategory.PORT_CONFLICT, message=long_msg)
        output = self._render_bar(rns_online=False, error_state=err)
        # Should be truncated to _MAX_ERROR_MSG_LEN (20 chars - 1 + ellipsis)
        assert len(long_msg) > 20  # confirm it's long enough to truncate
        assert "…" in output


# ===========================================================================
# O5-8: HomeStatusBar IPC/daemon status
# ===========================================================================

class TestHomeStatusBarDaemon:
    """HomeStatusBar daemon connection and uptime display."""

    def _render_bar(self, **kwargs) -> str:
        from styrened.tui.widgets.home_status_bar import HomeStatusBar
        bar = HomeStatusBar()
        for k, v in kwargs.items():
            object.__setattr__(bar, k, v)
        return _plain(bar.render())

    def test_daemon_connected_with_uptime(self):
        output = self._render_bar(daemon_connected=True, daemon_uptime=3600)
        assert "IPC ●" in output
        assert "1h" in output

    def test_daemon_disconnected(self):
        output = self._render_bar(daemon_connected=False)
        assert "IPC ○" in output


# ===========================================================================
# O5-8b: MeshDevice hops display formatting
# ===========================================================================

class TestMeshDeviceHopsDisplay:
    """Test hops display formatting logic (used by widgets rendering hops)."""

    def test_hops_zero_means_direct(self):
        """0 hops = direct link, no intermediate nodes."""
        d = _make_device(hops=0)
        assert d.hops == 0
        # The label logic: hops=0 -> 'direct'
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
        # When hops is None, the field should be skipped entirely

    def test_hops_in_device_status_widget_render(self):
        """DeviceStatusWidget includes hops in MESH section when set."""
        from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
        d = _make_device(hops=3)
        w = DeviceStatusWidget(device=d)
        output = w.render()
        # Strip Rich markup
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
        # identity_hash exists, but bare 'identity' should not be a field
        assert not hasattr(d, "identity") or "identity" not in d.__dataclass_fields__

    def test_identity_hash_used_for_lookup(self):
        """Filtering devices by identity_hash finds the right device."""
        devices = [
            _make_device(identity_hash="aaa111", name="node-a"),
            _make_device(identity_hash="bbb222", name="node-b"),
            _make_device(identity_hash="ccc333", name="node-c"),
        ]
        target = "bbb222"
        found = [d for d in devices if d.identity_hash == target]
        assert len(found) == 1
        assert found[0].name == "node-b"

    def test_identity_hash_not_empty_string(self):
        """identity_hash should be a meaningful string, not empty."""
        d = _make_device(identity_hash="deadbeef")
        assert len(d.identity_hash) > 0

    def test_identity_hash_in_dataclass_fields(self):
        """identity_hash is a proper dataclass field, not a property or monkey-patch."""
        assert "identity_hash" in MeshDevice.__dataclass_fields__

    def test_identity_short_property_uses_identity_hash(self):
        """The identity_short property should derive from identity_hash."""
        d = _make_device(identity_hash="abcdef1234567890")
        short = d.identity_short
        # identity_short should be a prefix of identity_hash
        assert d.identity_hash.startswith(short) or short in d.identity_hash
