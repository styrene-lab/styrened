"""SVG snapshot tests for TUI screens against live Rust daemon.

Captures SVG screenshots of each main screen and compares against golden
snapshots. Detects visual regressions: broken layouts, missing widgets,
incorrect text, theme changes.

First run: creates golden snapshots in __snapshots__/
Subsequent runs: compares against goldens, fails on diff.

Update snapshots: pytest tests/tui/smoke/test_snapshots.py --snapshot-update
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.tui_smoke,
    pytest.mark.asyncio,
]

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"


@pytest.fixture(autouse=True)
def ensure_snapshot_dir():
    """Create snapshot directory if it doesn't exist."""
    SNAPSHOT_DIR.mkdir(exist_ok=True)


import re

# Patterns for dynamic content that changes between runs
_DYNAMIC_PATTERNS = [
    # Timestamps: 2026-03-21 15:33:57, 15:33, etc.
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?"), "TIMESTAMP"),
    (re.compile(r"\d{2}:\d{2}:\d{2}"), "HH:MM:SS"),
    # Hex hashes (identity/destination hashes, 16+ hex chars)
    (re.compile(r"[0-9a-f]{16,}"), "HEXHASH"),
    # Uptime values: "0d 0h 2m", "5s ago"
    (re.compile(r"\d+[dhms]\s*\d*[dhms]?"), "UPTIME"),
    (re.compile(r"\d+s? ago"), "AGO"),
    # Version numbers that might change
    (re.compile(r"v?\d+\.\d+\.\d+"), "VERSION"),
]


def _normalize_svg(svg: str) -> str:
    """Strip dynamic content from SVG for stable snapshot comparison."""
    for pattern, replacement in _DYNAMIC_PATTERNS:
        svg = pattern.sub(replacement, svg)
    return svg


async def _capture_screen_svg(tui_app, screen, *, size=(120, 40), pause=1.0) -> str:
    """Mount a screen and capture its normalized SVG rendering."""
    async with tui_app.run_test(size=size) as pilot:
        await tui_app.push_screen(screen)
        await pilot.pause(delay=pause)
        svg = tui_app.export_screenshot()
        return _normalize_svg(svg)


def _assert_snapshot(svg: str, name: str, snapshot):
    """Compare SVG against golden snapshot."""
    assert svg == snapshot


class TestDashboardSnapshot:
    async def test_dashboard_visual(self, tui_app, snapshot):
        from styrened.tui.screens.dashboard import DashboardScreen

        svg = await _capture_screen_svg(tui_app, DashboardScreen(), pause=2.0)
        assert svg == snapshot


class TestExplorationSnapshot:
    async def test_exploration_visual(self, tui_app, snapshot):
        from styrened.tui.screens.exploration import ExplorationScreen

        svg = await _capture_screen_svg(tui_app, ExplorationScreen())
        assert svg == snapshot


class TestCommsSnapshot:
    async def test_comms_visual(self, tui_app, snapshot):
        from styrened.tui.screens.comms import CommsScreen

        svg = await _capture_screen_svg(tui_app, CommsScreen())
        assert svg == snapshot


class TestContactsSnapshot:
    async def test_contacts_visual(self, tui_app, snapshot):
        from styrened.tui.screens.contacts import ContactsScreen

        svg = await _capture_screen_svg(tui_app, ContactsScreen())
        assert svg == snapshot


class TestSettingsSnapshot:
    async def test_settings_visual(self, tui_app, snapshot):
        from styrened.tui.models.config import StyreneConfig
        from styrened.tui.screens.settings import SettingsScreen

        svg = await _capture_screen_svg(
            tui_app, SettingsScreen(config=StyreneConfig())
        )
        assert svg == snapshot


class TestInboxSnapshot:
    async def test_inbox_visual(self, tui_app, snapshot):
        from styrened.tui.screens.inbox import InboxScreen

        svg = await _capture_screen_svg(tui_app, InboxScreen())
        assert svg == snapshot


class TestGlobalCopSnapshot:
    async def test_global_cop_visual(self, tui_app, snapshot):
        from styrened.tui.screens.global_cop import GlobalCopScreen

        svg = await _capture_screen_svg(tui_app, GlobalCopScreen())
        assert svg == snapshot
