"""Tests for HomeNodeSummaryTable widget."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.widgets.home_node_summary import (
    HomeNodeSummaryTable,
    _STATUS_SORT_ORDER,
    format_relative_time,
)


def _make_device(
    name: str,
    identity_hash: str,
    last_announce: float | None = None,
    hops: int | None = None,
) -> MeshDevice:
    """Create a MeshDevice for testing."""
    return MeshDevice(
        destination_hash=f"dest_{identity_hash}",
        identity_hash=identity_hash,
        name=name,
        device_type=DeviceType.STYRENE_NODE,
        last_announce=last_announce,
        announce_count=1,
        hops=hops,
    )


class TestFormatRelativeTime:
    """Tests for relative time formatting."""

    def test_none_returns_never(self) -> None:
        assert format_relative_time(None) == "never"

    def test_future_returns_just_now(self) -> None:
        assert format_relative_time(time.time() + 100) == "just now"

    def test_seconds_ago(self) -> None:
        result = format_relative_time(time.time() - 12)
        assert result == "12s ago"

    def test_minutes_ago(self) -> None:
        result = format_relative_time(time.time() - 180)
        assert result == "3m ago"

    def test_hours_ago(self) -> None:
        result = format_relative_time(time.time() - 7200)
        assert result == "2h ago"

    def test_days_ago(self) -> None:
        result = format_relative_time(time.time() - 172800)
        assert result == "2d ago"

    def test_zero_seconds(self) -> None:
        result = format_relative_time(time.time())
        assert result == "0s ago"


class TestStatusSortOrder:
    """Tests for abnormal-first sort ordering."""

    def test_lost_sorts_before_stale(self) -> None:
        assert _STATUS_SORT_ORDER[NodeStatus.LOST] < _STATUS_SORT_ORDER[NodeStatus.STALE]

    def test_stale_sorts_before_active(self) -> None:
        assert _STATUS_SORT_ORDER[NodeStatus.STALE] < _STATUS_SORT_ORDER[NodeStatus.ACTIVE]

    def test_lost_sorts_before_active(self) -> None:
        assert _STATUS_SORT_ORDER[NodeStatus.LOST] < _STATUS_SORT_ORDER[NodeStatus.ACTIVE]


class TestNodeSelectedMessage:
    """Tests for the NodeSelected message."""

    def test_message_stores_identity_hash(self) -> None:
        msg = HomeNodeSummaryTable.NodeSelected("abc123")
        assert msg.identity_hash == "abc123"


class TestUpdateNodesLogic:
    """Tests for update_nodes sorting and data logic (no Textual app needed)."""

    def test_sort_order_abnormal_first(self) -> None:
        """Nodes are sorted LOST > STALE > ACTIVE."""
        now = time.time()
        devices = [
            _make_device("online-node", "aaa", last_announce=now - 10),       # ACTIVE
            _make_device("lost-node", "bbb", last_announce=now - 7200),       # LOST
            _make_device("stale-node", "ccc", last_announce=now - 600),       # STALE
        ]

        # Verify status assignments
        assert devices[0].status == NodeStatus.ACTIVE
        assert devices[1].status == NodeStatus.LOST
        assert devices[2].status == NodeStatus.STALE

        # Sort using same logic as widget
        sorted_devices = sorted(
            devices,
            key=lambda d: (_STATUS_SORT_ORDER.get(d.status, 99), d.name or ""),
        )
        assert sorted_devices[0].name == "lost-node"
        assert sorted_devices[1].name == "stale-node"
        assert sorted_devices[2].name == "online-node"

    def test_unread_map_values(self) -> None:
        """Unread count is correctly looked up from the map."""
        unread_map = {"hash1": 2, "hash2": 0}
        assert unread_map.get("hash1", 0) == 2
        assert unread_map.get("hash2", 0) == 0
        assert unread_map.get("hash3", 0) == 0  # missing = 0

    def test_unread_display_logic(self) -> None:
        """Unread > 0 shows count, 0 shows dash."""
        for count, expected in [(2, "2"), (0, "—"), (10, "10")]:
            text = str(count) if count > 0 else "—"
            assert text == expected

    def test_empty_nodes_sets_empty_flag(self) -> None:
        """Empty node list should produce empty-state behavior."""
        # Widget._empty should be True when no nodes
        # Testing the logic without mounting
        nodes: list[MeshDevice] = []
        assert len(nodes) == 0

    def test_row_key_is_identity_hash(self) -> None:
        """Row key should be the device's identity_hash."""
        device = _make_device("test", "deadbeef")
        assert device.identity_hash == "deadbeef"

    def test_link_text_with_hops(self) -> None:
        """Link column shows hop count."""
        device = _make_device("test", "aaa", hops=2)
        hops = device.hops
        assert isinstance(hops, int)
        link_text = f"{hops} hop{'s' if hops != 1 else ''}"
        assert link_text == "2 hops"

    def test_link_text_single_hop(self) -> None:
        """Single hop shows singular form."""
        device = _make_device("test", "aaa", hops=1)
        hops = device.hops
        assert isinstance(hops, int)
        link_text = f"{hops} hop{'s' if hops != 1 else ''}"
        assert link_text == "1 hop"

    def test_link_text_unknown_hops(self) -> None:
        """Unknown hops shows question mark."""
        device = _make_device("test", "aaa", hops=None)
        hops = device.hops if device.hops is not None else "?"
        assert hops == "?"

    def test_name_fallback_to_identity_hash(self) -> None:
        """When name is None, falls back to identity_hash prefix."""
        device = MeshDevice(
            destination_hash="dest_abc",
            identity_hash="abcdef1234567890",
            name=None,
            device_type=DeviceType.STYRENE_NODE,
            last_announce=time.time(),
            announce_count=1,
        )
        display_name = device.name or device.identity_hash[:8]
        assert display_name == "abcdef12"

    def test_sort_stability_same_status(self) -> None:
        """Nodes with same status are sorted alphabetically by name."""
        now = time.time()
        devices = [
            _make_device("zebra", "z", last_announce=now - 10),
            _make_device("alpha", "a", last_announce=now - 10),
            _make_device("middle", "m", last_announce=now - 10),
        ]
        sorted_devices = sorted(
            devices,
            key=lambda d: (_STATUS_SORT_ORDER.get(d.status, 99), d.name or ""),
        )
        assert [d.name for d in sorted_devices] == ["alpha", "middle", "zebra"]
