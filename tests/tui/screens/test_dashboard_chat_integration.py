"""Dashboard chat integration — retired in v0.16.1.

DashboardScreen was narrowed to a Home workspace in v0.16.1. MeshDeviceTree
(the peer-browsing tree with unread message badges) was removed from Dashboard;
it belongs in ExplorationScreen (Nodes workspace).

Tests that covered:
- Unread message count display in device tree (TestDashboardMessageIndicators)
- Device detail navigation from tree enter key (TestDashboardEnterOpensDetail)

These behaviours are now tested in:
- tests/tui/screens/test_exploration.py — Nodes/ExplorationScreen browsing
- tests/tui/screens/test_device_detail_tui.py — peer workspace navigation
- tests/tui/screens/test_dashboard_tui.py — Home workspace (activity feed,
  daemon status, no peer tree)
"""
from __future__ import annotations

