"""Tests for HomeStatusBar widget.

Validates compact SCADA-style status rendering with dim/bright anomaly logic.
"""

import io

from rich.console import Console
from rich.text import Text

from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.services.hub_connection import HubStatus
from styrened.tui.widgets.home_status_bar import HomeStatusBar


_DEFAULTS = {
    "rns_online": True,
    "hub_status": HubStatus.CONNECTED,
    "interface_count": 0,
    "styrene_mesh_count": 0,
    "daemon_connected": True,
    "daemon_uptime": 0.0,
    "unread_count": 0,
    "error_state": None,
}


def _make_bar(**kwargs) -> HomeStatusBar:
    """Create a HomeStatusBar with values set without triggering watchers.

    Textual reactive descriptors require an active app context when set
    normally.  We bypass the descriptor by writing directly to the internal
    ``_reactive_<name>`` attribute that Textual's ``reactive`` uses for storage.
    All reactives are pre-initialized to prevent lazy-init cascade.
    """
    bar = HomeStatusBar()
    merged = {**_DEFAULTS, **kwargs}
    for key, value in merged.items():
        object.__setattr__(bar, f"_reactive_{key}", value)
    return bar


def _render_bar(bar: HomeStatusBar) -> str:
    """Render HomeStatusBar to plain text for assertions."""
    renderable = bar.render()
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, markup=False, width=120)
    console.print(renderable)
    return buf.getvalue().strip()


def _render_rich(bar: HomeStatusBar) -> Text:
    """Get the Rich Text object for style inspection."""
    return bar.render()


class TestNominalRendering:
    """All-nominal state renders dim indicators."""

    def test_nominal_all_dim(self) -> None:
        """When all systems nominal, output contains expected labels."""
        bar = _make_bar(
            rns_online=True,
            hub_status=HubStatus.CONNECTED,
            interface_count=1,
            styrene_mesh_count=4,
            daemon_connected=True,
            daemon_uptime=34.0,
            unread_count=0,
            error_state=None,
        )

        text = _render_rich(bar)
        plain = text.plain

        assert "RNS ● online" in plain
        assert "IF 1" in plain
        assert "HUB ●" in plain
        assert "MESH 4" in plain
        assert "IPC ● 34s" in plain
        # No unread segment
        assert "✉" not in plain

    def test_nominal_no_bright_styles(self) -> None:
        """Nominal state uses only dim styles, no bold/warning."""
        bar = _make_bar(
            rns_online=True,
            hub_status=HubStatus.CONNECTED,
            interface_count=1,
            styrene_mesh_count=4,
            daemon_connected=True,
            daemon_uptime=34.0,
            unread_count=0,
            error_state=None,
        )

        text = _render_rich(bar)
        # Check no span uses bold
        for start, end, style in text._spans:
            assert "bold" not in str(style), f"Unexpected bold in nominal: {style}"


class TestAnomalyPromotion:
    """Anomalous states promote to bright/warning colors."""

    def test_hub_disconnected_bright(self) -> None:
        """Hub disconnected renders in warning style."""
        bar = _make_bar(
            rns_online=True,
            hub_status=HubStatus.DISCONNECTED,
            daemon_connected=True,
            daemon_uptime=100.0,
        )

        text = _render_rich(bar)
        plain = text.plain

        assert "HUB ○ lost" in plain
        # Hub segment should have bold style
        hub_start = plain.index("HUB")
        found_bold = False
        for start, end, style in text._spans:
            if start <= hub_start < end and "bold" in str(style):
                found_bold = True
        assert found_bold, "Hub disconnected should use bold style"

    def test_rns_offline_bright(self) -> None:
        """RNS offline renders in error style."""
        bar = _make_bar(
            rns_online=False,
            error_state=RNSErrorState(
                category=RNSErrorCategory.INTERFACE_FAILURE,
                message="no interfaces",
            ),
            daemon_connected=True,
        )

        text = _render_rich(bar)
        plain = text.plain

        assert "RNS ○ offline" in plain
        assert "no interfaces" in plain
        # Should have bold red
        rns_start = plain.index("RNS")
        found_red = False
        for start, end, style in text._spans:
            if start <= rns_start < end and "red" in str(style):
                found_red = True
        assert found_red, "RNS offline with error should use red style"

    def test_rns_offline_no_error_uses_yellow(self) -> None:
        """RNS offline without error_state uses yellow warning."""
        bar = _make_bar(
            rns_online=False,
            error_state=None,
            daemon_connected=True,
        )

        text = _render_rich(bar)
        plain = text.plain
        assert "RNS ○ offline" in plain

        rns_start = plain.index("RNS")
        found_yellow = False
        for start, end, style in text._spans:
            if start <= rns_start < end and "yellow" in str(style):
                found_yellow = True
        assert found_yellow

    def test_unread_count_bright(self) -> None:
        """Unread messages render with bright style."""
        bar = _make_bar(
            rns_online=True,
            hub_status=HubStatus.CONNECTED,
            daemon_connected=True,
            daemon_uptime=60.0,
            unread_count=3,
        )

        text = _render_rich(bar)
        plain = text.plain

        assert "✉ 3" in plain
        # Should have bold style
        mail_start = plain.index("✉")
        found_bold = False
        for start, end, style in text._spans:
            if start <= mail_start < end and "bold" in str(style):
                found_bold = True
        assert found_bold, "Unread count should use bold style"


class TestWidthConstraint:
    """Status bar must fit within standard terminal widths."""

    def test_width_within_80_cols(self) -> None:
        """Rendered output fits in 80 columns without overflow."""
        bar = _make_bar(
            rns_online=True,
            hub_status=HubStatus.CONNECTED,
            interface_count=3,
            styrene_mesh_count=99,
            daemon_connected=True,
            daemon_uptime=86400 * 7,  # 7d
            unread_count=99,
            error_state=None,
        )

        text = _render_rich(bar)
        # plain text length should be <= 76 chars (max spec)
        assert len(text.plain) <= 76, f"Too wide: {len(text.plain)} chars: {text.plain!r}"


class TestHubVariants:
    """Hub status rendering variants."""

    def test_hub_disabled(self) -> None:
        bar = _make_bar(hub_status=HubStatus.DISABLED)
        plain = _render_bar(bar)
        assert "HUB —" in plain

    def test_hub_waiting(self) -> None:
        bar = _make_bar(hub_status=HubStatus.WAITING)
        plain = _render_bar(bar)
        assert "HUB ◐" in plain


class TestDaemonDisconnected:
    """Daemon IPC disconnected state."""

    def test_daemon_disconnected_bright(self) -> None:
        bar = _make_bar(daemon_connected=False)
        text = _render_rich(bar)
        assert "IPC ○" in text.plain

        ipc_start = text.plain.index("IPC")
        found_bold = False
        for start, end, style in text._spans:
            if start <= ipc_start < end and "bold" in str(style):
                found_bold = True
        assert found_bold


class TestFormatUptime:
    """Uptime formatting helper."""

    def test_seconds(self) -> None:
        assert HomeStatusBar._format_uptime(34) == "34s"

    def test_minutes(self) -> None:
        assert HomeStatusBar._format_uptime(120) == "2m"

    def test_hours(self) -> None:
        assert HomeStatusBar._format_uptime(3661) == "1h 1m"

    def test_days(self) -> None:
        assert HomeStatusBar._format_uptime(90000) == "1d 1h"
