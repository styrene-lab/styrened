"""Tests for CopActivitySummary widget — state-driven COP situation lines."""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from styrened.tui.widgets.cop_activity_summary import (
    CopActivitySummary,
    SituationPriority,
    transport_label,
)


# ---------------------------------------------------------------------------
# Fake node for testing
# ---------------------------------------------------------------------------

@dataclass
class FakeNode:
    name: str = "test-node"
    destination_hash: str = "abcd1234"
    identity_hash: str = "ih_abcd"
    discovered_via: str | None = "TCPClientInterface"
    status: str = "active"
    device_type: str = "styrene_node"


# ---------------------------------------------------------------------------
# transport_label() parser
# ---------------------------------------------------------------------------

class TestTransportLabel:

    @pytest.mark.parametrize("via,expected", [
        ("TCPClientInterface", "TCP"),
        ("TCPServerInterface", "TCP"),
        ("TCPClientInterface → 3a4b5c6d", "TCP"),
        ("AutoInterface", "Auto"),
        ("RNodeInterface", "RNode"),
        ("I2PInterface", "I2P"),
        ("YggdrasilInterface", "Ygg"),
        ("UDPInterface", "UDP"),
        ("SerialInterface", "SER"),
        ("KISSInterface", "KISS"),
        ("PipeInterface", "Pipe"),
        ("MeshtasticBridge", "Mesh"),
        (None, "—"),
        ("", "—"),
        ("SomeNewInterface", "Some"),
    ])
    def test_transport_label(self, via, expected):
        assert transport_label(via) == expected

    def test_with_next_hop_suffix(self):
        assert transport_label("AutoInterface → deadbeef") == "Auto"


# ---------------------------------------------------------------------------
# State-driven update
# ---------------------------------------------------------------------------

class TestNodeDiscovery:

    def test_coalesces_per_transport(self):
        w = CopActivitySummary()
        nodes = [
            FakeNode(name="n1", discovered_via="TCPClientInterface"),
            FakeNode(name="n2", discovered_via="TCPClientInterface"),
            FakeNode(name="n3", discovered_via="AutoInterface"),
        ]
        w.update_from_state(nodes)
        output = w.render()
        assert "[TCP]" in output
        assert "[Auto]" in output
        assert "2 nodes [TCP]" in output
        assert "1 node [Auto]" in output

    def test_no_transport_shows_dash(self):
        w = CopActivitySummary()
        nodes = [FakeNode(name="n1", discovered_via=None)]
        w.update_from_state(nodes)
        output = w.render()
        assert "[—]" in output

    def test_plural_singular(self):
        w = CopActivitySummary()
        w.update_from_state([FakeNode()])
        assert "1 node" in w.render()
        w.update_from_state([FakeNode(name="a"), FakeNode(name="b")])
        assert "2 nodes" in w.render()


class TestNodeAnomaly:

    def test_stale_shows_anomaly(self):
        w = CopActivitySummary()
        nodes = [FakeNode(name="relay-east", status="stale", discovered_via="YggdrasilInterface")]
        w.update_from_state(nodes)
        output = w.render()
        assert "1 node stale" in output

    def test_lost_nodes_ignored(self):
        """LOST nodes are historical noise — no anomaly or discovery lines."""
        w = CopActivitySummary()
        nodes = [FakeNode(name="gone", status="lost", discovered_via="TCPClientInterface")]
        w.update_from_state(nodes)
        output = w.render()
        assert "gone" not in output
        assert "node" not in output or "no recent" in output

    def test_offline_not_in_discovery_count(self):
        w = CopActivitySummary()
        nodes = [
            FakeNode(name="good", status="active", discovered_via="TCPClientInterface"),
            FakeNode(name="bad", status="stale", discovered_via="TCPClientInterface"),
        ]
        w.update_from_state(nodes)
        output = w.render()
        assert "1 node [TCP]" in output  # Only the active one
        assert "1 node stale" in output  # Stale coalesced


class TestUnread:

    def test_shows_unread_count_and_names(self):
        w = CopActivitySummary()
        unread = {"ih_alice": 2, "ih_bob": 1}
        name_map = {"ih_alice": "Alice", "ih_bob": "Bob"}
        w.update_from_state([], unread_map=unread, node_name_map=name_map)
        output = w.render()
        assert "3 unread" in output
        assert "Alice" in output
        assert "Bob" in output

    def test_truncates_at_3_names(self):
        w = CopActivitySummary()
        unread = {"a": 1, "b": 1, "c": 1, "d": 1}
        name_map = {"a": "A", "b": "B", "c": "C", "d": "D"}
        w.update_from_state([], unread_map=unread, node_name_map=name_map)
        output = w.render()
        assert "+1" in output

    def test_zero_unread_no_line(self):
        w = CopActivitySummary()
        w.update_from_state([], unread_map={"a": 0})
        assert "unread" not in w.render()


class TestHubStatus:

    def test_disconnected_shows_line(self):
        w = CopActivitySummary()
        w.update_from_state([], hub_status="disconnected")
        assert "hub disconnected" in w.render()

    def test_connected_no_line(self):
        w = CopActivitySummary()
        w.update_from_state([], hub_status="connected")
        assert "hub" not in w.render()

    def test_unknown_no_line(self):
        w = CopActivitySummary()
        w.update_from_state([], hub_status="unknown")
        assert "hub" not in w.render()


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:

    def test_anomaly_before_unread_before_discovery(self):
        w = CopActivitySummary()
        nodes = [
            FakeNode(name="good", status="active", discovered_via="AutoInterface"),
            FakeNode(name="bad", status="stale", discovered_via="TCPClientInterface"),
        ]
        unread = {"ih_alice": 1}
        name_map = {"ih_alice": "Alice"}
        w.update_from_state(nodes, unread_map=unread, node_name_map=name_map)
        output = w.render()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 3
        assert "▲" in lines[0]  # Anomaly (stale)
        assert "✉" in lines[1]  # Unread
        assert "[Auto]" in lines[2]  # Discovery


# ---------------------------------------------------------------------------
# Ephemeral events
# ---------------------------------------------------------------------------

class TestEphemeralEvents:

    def test_file_offer(self):
        w = CopActivitySummary()
        w.add_ephemeral("file_offer_received", {"peer_name": "Alice", "metadata": {"filename": "report.pdf"}})
        w.update_from_state([])  # Trigger render with ephemeral
        output = w.render()
        assert "file from Alice" in output
        assert "report.pdf" in output

    def test_pqc_established(self):
        w = CopActivitySummary()
        w.add_ephemeral("pqc_established", {"peer_name": "relay-east"})
        w.update_from_state([])
        assert "PQC session with relay-east" in w.render()

    def test_ignored_ephemeral(self):
        w = CopActivitySummary()
        w.add_ephemeral("announce_sent", {})
        w.update_from_state([])
        assert "no recent activity" in w.render()

    def test_ephemeral_caps_at_4(self):
        w = CopActivitySummary()
        for i in range(6):
            w.add_ephemeral("pqc_established", {"peer_name": f"peer-{i}"})
        assert len(w._ephemeral_events) == 4


# ---------------------------------------------------------------------------
# Max situations
# ---------------------------------------------------------------------------

class TestMaxSituations:

    def test_caps_at_6(self):
        w = CopActivitySummary()
        # Mix active nodes across many transports + unread + hub to exceed 6 lines
        nodes = [
            FakeNode(name=f"n-{i}", status="active", discovered_via=f"iface-{i}")
            for i in range(8)
        ]
        unread = {"ih1": 1}
        w.update_from_state(nodes, unread_map=unread, hub_status="disconnected")
        lines = [l for l in w.render().strip().split("\n") if l.strip()]
        assert len(lines) <= 6


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:

    def test_empty_shows_no_recent_activity(self):
        w = CopActivitySummary()
        w.update_from_state([])
        assert "no recent activity" in w.render()

    def test_no_update_shows_no_recent_activity(self):
        w = CopActivitySummary()
        assert "no recent activity" in w.render()


# ---------------------------------------------------------------------------
# State is re-derived each call (no stale shadow state)
# ---------------------------------------------------------------------------

class TestStateless:

    def test_update_replaces_not_accumulates(self):
        w = CopActivitySummary()
        w.update_from_state([FakeNode(name="a"), FakeNode(name="b")])
        assert "2 nodes" in w.render()
        w.update_from_state([FakeNode(name="a")])
        assert "1 node" in w.render()
        assert "2 nodes" not in w.render()

    def test_anomaly_clears_when_node_recovers(self):
        w = CopActivitySummary()
        w.update_from_state([FakeNode(name="x", status="stale")])
        assert "stale" in w.render()
        w.update_from_state([FakeNode(name="x", status="active")])
        assert "stale" not in w.render()


# ---------------------------------------------------------------------------
# Dashboard integration test
# ---------------------------------------------------------------------------

class TestDashboardActivitySubscription:

    @pytest.mark.asyncio
    async def test_activity_subscription_calls_add_ephemeral(self):
        """Activity subscription should call add_ephemeral for COP events."""
        from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

        from styrened.ipc.protocol import IPCMessageType
        from styrened.tui.screens.dashboard import DashboardScreen

        screen = DashboardScreen()
        bridge = MagicMock()
        bridge.subscribe_activity = AsyncMock(return_value=True)

        async def _iter_events(_event_type):
            yield (IPCMessageType.EVENT_ACTIVITY, {"type": "pqc_established", "peer_name": "test"})

        bridge.iter_events = _iter_events
        cop_widget = MagicMock()

        with (
            patch.object(
                DashboardScreen,
                "_ipc_bridge",
                new_callable=PropertyMock,
                return_value=bridge,
            ),
            patch.object(screen, "query_one", return_value=cop_widget),
        ):
            await screen._subscribe_activity()

        cop_widget.add_ephemeral.assert_called_once_with(
            "pqc_established",
            {"type": "pqc_established", "peer_name": "test"},
        )
