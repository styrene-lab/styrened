"""Tests for HomeNodeSummaryTable widget."""

from __future__ import annotations

import time

import pytest
from textual.app import App, ComposeResult

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.widgets.home_node_summary import (
    HomeNodeSummaryTable,
    _UNKNOWN_STATUS_SORT_KEY,
    format_relative_time,
)


def _make_device(
    name: str,
    identity_hash: str,
    status: NodeStatus = NodeStatus.ACTIVE,
    last_announce: float | None = None,
    hops: int | None = None,
) -> MeshDevice:
    """Create a MeshDevice for testing with explicit status control."""
    device = MeshDevice(
        destination_hash=f"dest_{identity_hash}",
        identity_hash=identity_hash,
        name=name,
        device_type=DeviceType.STYRENE_NODE,
        last_announce=last_announce,
        announce_count=1,
        hops=hops,
    )
    # Override the computed status property for test determinism
    object.__setattr__(device, "_test_status", status)
    return device


class _TestApp(App[None]):
    """Minimal app for mounting HomeNodeSummaryTable in tests."""

    def compose(self) -> ComposeResult:
        yield HomeNodeSummaryTable()


# ---------------------------------------------------------------------------
# format_relative_time (pure function, deterministic via `now` param)
# ---------------------------------------------------------------------------


class TestFormatRelativeTime:
    """Tests for relative time formatting."""

    def test_none_returns_never(self) -> None:
        assert format_relative_time(None) == "never"

    def test_future_returns_just_now(self) -> None:
        assert format_relative_time(1000.0, now=900.0) == "just now"

    def test_seconds_ago(self) -> None:
        assert format_relative_time(988.0, now=1000.0) == "12s ago"

    def test_minutes_ago(self) -> None:
        assert format_relative_time(820.0, now=1000.0) == "3m ago"

    def test_hours_ago(self) -> None:
        assert format_relative_time(0.0, now=7200.0) == "2h ago"

    def test_days_ago(self) -> None:
        assert format_relative_time(0.0, now=172800.0) == "2d ago"

    def test_zero_seconds(self) -> None:
        assert format_relative_time(1000.0, now=1000.0) == "0s ago"

    def test_boundary_59s(self) -> None:
        assert format_relative_time(941.0, now=1000.0) == "59s ago"

    def test_boundary_60s(self) -> None:
        assert format_relative_time(940.0, now=1000.0) == "1m ago"


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestStatusSortOrder:
    """Tests for active-first sort ordering (ACTIVE > STALE > LOST)."""

    def test_active_before_stale(self) -> None:
        from styrened.tui.widgets.home_node_summary import _STATUS_SORT_ORDER

        assert _STATUS_SORT_ORDER[NodeStatus.ACTIVE] < _STATUS_SORT_ORDER[NodeStatus.STALE]

    def test_stale_before_lost(self) -> None:
        from styrened.tui.widgets.home_node_summary import _STATUS_SORT_ORDER

        assert _STATUS_SORT_ORDER[NodeStatus.STALE] < _STATUS_SORT_ORDER[NodeStatus.LOST]

    def test_unknown_status_sorts_between_stale_and_lost(self) -> None:
        """Unknown/future statuses sort after STALE but before LOST."""
        from styrened.tui.widgets.home_node_summary import _STATUS_SORT_ORDER

        assert _STATUS_SORT_ORDER[NodeStatus.STALE] < _UNKNOWN_STATUS_SORT_KEY
        assert _UNKNOWN_STATUS_SORT_KEY < _STATUS_SORT_ORDER[NodeStatus.LOST]


# ---------------------------------------------------------------------------
# NodeSelected message
# ---------------------------------------------------------------------------


class TestNodeSelectedMessage:
    """Tests for the NodeSelected message."""

    def test_message_stores_identity_hash(self) -> None:
        msg = HomeNodeSummaryTable.NodeSelected("abc123")
        assert msg.identity_hash == "abc123"


# ---------------------------------------------------------------------------
# Widget tests (mounted in a real Textual app)
# ---------------------------------------------------------------------------


class TestHomeNodeSummaryTableWidget:
    """Tests that mount the widget and exercise update_nodes()."""

    @pytest.mark.asyncio
    async def test_columns_created_on_mount(self) -> None:
        """Widget creates the expected columns on mount."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            col_keys = [col.label.plain for col in table.columns.values()]
            assert col_keys == ["NAME", "STATUS", "LAST SEEN", "UNREAD", "LINK"]

    @pytest.mark.asyncio
    async def test_empty_state_placeholder(self) -> None:
        """Empty node list shows a placeholder row."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            table.update_nodes([])
            assert table._empty is True
            assert table.row_count == 1
            # The placeholder row has key "__empty__"
            cell = table.get_cell_at((0, 0))
            assert "No mesh nodes discovered" in str(cell)

    @pytest.mark.asyncio
    async def test_nodes_populate_rows(self) -> None:
        """Active/stale nodes are added as rows; LOST nodes are filtered out."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [
                _make_device("alpha", "aaa", NodeStatus.ACTIVE, now - 10),
                _make_device("bravo", "bbb", NodeStatus.LOST, now - 7200),
            ]
            table.update_nodes(devices)
            assert table._empty is False
            assert table.row_count == 1  # LOST filtered out

    @pytest.mark.asyncio
    async def test_lost_nodes_filtered_out(self) -> None:
        """All-LOST list shows placeholder with count."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [
                _make_device("gone", "bbb", NodeStatus.LOST, now - 7200),
            ]
            table.update_nodes(devices)
            assert table._empty is True
            cell = str(table.get_cell_at((0, 0)))
            assert "1 nodes known (all lost)" in cell

    @pytest.mark.asyncio
    async def test_sort_order_active_first(self) -> None:
        """Rows are sorted ACTIVE > STALE (LOST filtered out)."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [
                _make_device("stale", "ccc", NodeStatus.STALE, now - 600),
                _make_device("online", "aaa", NodeStatus.ACTIVE, now - 10),
                _make_device("lost", "bbb", NodeStatus.LOST, now - 7200),
            ]
            table.update_nodes(devices)
            assert table.row_count == 2  # LOST filtered
            first_name = str(table.get_cell_at((0, 0)))
            last_name = str(table.get_cell_at((1, 0)))
            assert first_name == "online"
            assert last_name == "stale"

    @pytest.mark.asyncio
    async def test_unread_count_displayed(self) -> None:
        """Unread column shows count or dash."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [
                _make_device("relay-east", "r1", NodeStatus.ACTIVE, now - 10),
                _make_device("casbah", "c1", NodeStatus.ACTIVE, now - 10),
            ]
            table.update_nodes(devices, unread_map={"r1": 2, "c1": 0})
            # Find rows by key
            r1_unread = str(table.get_cell("r1", "unread"))
            c1_unread = str(table.get_cell("c1", "unread"))
            assert r1_unread == "2"
            assert c1_unread == "—"

    @pytest.mark.asyncio
    async def test_row_key_is_identity_hash(self) -> None:
        """Each row's key is the device's identity_hash."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [_make_device("test", "deadbeef", NodeStatus.ACTIVE, now - 5)]
            table.update_nodes(devices)
            # Row key should be accessible
            row_keys = [rk.value for rk in table.rows.keys()]
            assert "deadbeef" in row_keys

    @pytest.mark.asyncio
    async def test_update_replaces_previous_data(self) -> None:
        """Calling update_nodes again clears old rows."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices1 = [_make_device("first", "aaa", NodeStatus.ACTIVE, now - 5)]
            devices2 = [
                _make_device("second", "bbb", NodeStatus.ACTIVE, now - 5),
                _make_device("third", "ccc", NodeStatus.STALE, now - 600),
            ]
            table.update_nodes(devices1)
            assert table.row_count == 1
            table.update_nodes(devices2)
            assert table.row_count == 2
            first_name = str(table.get_cell_at((0, 0)))
            assert first_name != "first"

    @pytest.mark.asyncio
    async def test_empty_to_populated_transition(self) -> None:
        """Transitioning from empty state to populated clears placeholder."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            table.update_nodes([])
            assert table._empty is True
            assert table.row_count == 1

            now = time.time()
            table.update_nodes([_make_device("new", "nnn", NodeStatus.ACTIVE, now - 5)])
            assert table._empty is False
            assert table.row_count == 1
            first_name = str(table.get_cell_at((0, 0)))
            assert first_name == "new"

    @pytest.mark.asyncio
    async def test_node_selected_message_on_row_select(self) -> None:
        """Selecting a row posts NodeSelected with the identity hash."""
        messages: list[HomeNodeSummaryTable.NodeSelected] = []

        class _CaptureApp(App[None]):
            def compose(self) -> ComposeResult:
                yield HomeNodeSummaryTable()

            def on_home_node_summary_table_node_selected(
                self, event: HomeNodeSummaryTable.NodeSelected
            ) -> None:
                messages.append(event)

        async with _CaptureApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            table.update_nodes([_make_device("test", "abc123", NodeStatus.ACTIVE, now - 5)])
            # Move cursor to row and select
            table.move_cursor(row=0)
            table.action_select_cursor()
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].identity_hash == "abc123"

    @pytest.mark.asyncio
    async def test_empty_row_select_suppressed(self) -> None:
        """Selecting the placeholder row does not post NodeSelected."""
        messages: list[HomeNodeSummaryTable.NodeSelected] = []

        class _CaptureApp(App[None]):
            def compose(self) -> ComposeResult:
                yield HomeNodeSummaryTable()

            def on_home_node_summary_table_node_selected(
                self, event: HomeNodeSummaryTable.NodeSelected
            ) -> None:
                messages.append(event)

        async with _CaptureApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            table.update_nodes([])
            table.move_cursor(row=0)
            table.action_select_cursor()
            await pilot.pause()
            assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_name_fallback_to_hash_prefix(self) -> None:
        """When name is None, display falls back to identity_hash[:8]."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            device = MeshDevice(
                destination_hash="dest_abc",
                identity_hash="abcdef1234567890",
                name=None,
                device_type=DeviceType.STYRENE_NODE,
                last_announce=now - 10,
                announce_count=1,
            )
            table.update_nodes([device])
            name_cell = str(table.get_cell_at((0, 0)))
            assert name_cell == "abcdef12"

    @pytest.mark.asyncio
    async def test_alphabetical_sort_within_same_status(self) -> None:
        """Nodes with same status sort alphabetically by name."""
        async with _TestApp().run_test() as pilot:
            table = pilot.app.query_one(HomeNodeSummaryTable)
            now = time.time()
            devices = [
                _make_device("zebra", "z", NodeStatus.ACTIVE, now - 10),
                _make_device("alpha", "a", NodeStatus.ACTIVE, now - 10),
                _make_device("middle", "m", NodeStatus.ACTIVE, now - 10),
            ]
            table.update_nodes(devices)
            names = [str(table.get_cell_at((i, 0))) for i in range(3)]
            assert names == ["alpha", "middle", "zebra"]
