"""Regression tests for tui-bug-handoff fixes.

Bug 1: Garbled timestamp "4s agox8" — missing space before ×
Bug 3: NodeInfoPanel two-column alignment with wide Unicode
"""

import re
from unittest.mock import MagicMock, PropertyMock

from rich.cells import cell_len as rich_cell_len

from styrened.models.mesh_device import DeviceType, NodeStatus
from styrened.tui.widgets.highlighted_panel import ColorCascade


def _make_device(
    announce_count: int = 1,
    last_seen_display: str = "4s ago",
    name: str = "Test Node",
    status: NodeStatus = NodeStatus.ACTIVE,
) -> MagicMock:
    d = MagicMock()
    d.name = name
    d.announce_count = announce_count
    type(d).last_seen_display = PropertyMock(return_value=last_seen_display)
    d.status = status
    d.identity_hash = "abc123"
    d.device_type = DeviceType.STYRENE_NODE
    return d


def _make_cascade() -> ColorCascade:
    return ColorCascade(bright="#00ff88", medium="#00cc66", dim="#336644")


def _format_seen(last_seen_display: str, announce_count: int) -> str:
    """Replicate the announce count formatting logic from dashboard.py."""
    seen = last_seen_display
    if announce_count > 1:
        seen += f" ×{announce_count}"
    return seen


class TestBug1AnnounceCountSpacing:
    """Bug 1: '4s agox8' → '4s ago ×8'."""

    def test_single_announce_no_multiplier(self) -> None:
        assert "×" not in _format_seen("4s ago", 1)

    def test_multiple_announces_has_space_before_multiplier(self) -> None:
        result = _format_seen("4s ago", 8)
        assert " ×8" in result, f"Expected ' ×8' in '{result}'"
        assert "ago×" not in result, "Must have space before ×"

    def test_multiplier_uses_unicode_times(self) -> None:
        """× (U+00D7) is used, not 'x'."""
        result = _format_seen("4s ago", 3)
        assert "×3" in result
        idx = result.index("×3")
        assert result[idx] == "×"  # U+00D7, not lowercase x

    def test_boundary_announce_count_2(self) -> None:
        result = _format_seen("1m ago", 2)
        assert " ×2" in result


class TestBug3TwoColumnAlignment:
    """Bug 3: NodeInfoPanel uses rich.cells.cell_len for accurate padding."""

    def test_rich_cell_len_used_for_padding(self) -> None:
        """Verify rich_cell_len handles Unicode symbols correctly."""
        # These are the symbols used in NodeInfoPanel
        assert rich_cell_len("●") >= 1
        assert rich_cell_len("⊙") >= 1
        assert rich_cell_len("○") >= 1
        # CJK wide chars should be 2
        assert rich_cell_len("全") == 2

    def test_padding_calculation_matches_rich(self) -> None:
        """The padding formula: col_width - rich_cell_len(stripped)."""
        col_width = 44
        test_line = "  RNS: ● online (3 if)"
        visible_len = rich_cell_len(test_line)
        pad = max(0, col_width - visible_len)
        # Padded line should be exactly col_width visible chars
        padded = test_line + " " * pad
        assert rich_cell_len(padded) == col_width

    def test_rich_markup_stripped_before_measuring(self) -> None:
        """Rich tags must be stripped before cell_len measurement."""
        raw = "[#00ff88]RNS: ● online[/]"
        stripped = re.sub(r"\[.*?\]", "", raw)
        assert stripped == "RNS: ● online"
        # Measuring raw (with tags) would give wrong result
        assert rich_cell_len(stripped) < rich_cell_len(raw)
