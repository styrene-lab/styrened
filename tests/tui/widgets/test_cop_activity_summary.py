"""Tests for COP situation tracker and presentation widget."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from styrened.tui.models.cop_situation import (
    CopSituationSnapshot,
    CopSituationTracker,
    SituationPriority,
    transport_label,
)
from styrened.tui.models.events import DaemonEvent
from styrened.tui.widgets.cop_activity_summary import CopActivitySummary

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


def _event(event_type: str, action: str, **data: object) -> DaemonEvent:
    return DaemonEvent(event_type=event_type, action=action, data=dict(data))


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
# CopSituationTracker — update_from_state (store-backed)
# ---------------------------------------------------------------------------

class TestNodeDiscovery:

    def test_coalesces_per_transport(self):
        t = CopSituationTracker()
        t.update_from_state([
            FakeNode(name="n1", discovered_via="TCPClientInterface"),
            FakeNode(name="n2", discovered_via="TCPClientInterface"),
            FakeNode(name="n3", discovered_via="AutoInterface"),
        ])
        snap = t.snapshot()
        messages = [l.message for l in snap.lines]
        assert any("2 nodes [TCP]" in m for m in messages)
        assert any("1 node [Auto]" in m for m in messages)

    def test_no_transport_shows_dash(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="n1", discovered_via=None)])
        snap = t.snapshot()
        assert any("[—]" in l.message for l in snap.lines)

    def test_plural_singular(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode()])
        assert any("1 node" in l.message for l in t.snapshot().lines)
        t.update_from_state([FakeNode(name="a"), FakeNode(name="b")])
        assert any("2 nodes" in l.message for l in t.snapshot().lines)


class TestNodeAnomaly:

    def test_stale_shows_anomaly(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="relay-east", status="stale")])
        snap = t.snapshot()
        assert any("stale" in l.message and l.priority == SituationPriority.ANOMALY
                   for l in snap.lines)

    def test_lost_nodes_ignored(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="gone", status="lost")])
        snap = t.snapshot()
        messages = " ".join(l.message for l in snap.lines)
        assert "gone" not in messages
        assert "lost" not in messages

    def test_stale_not_counted_in_discovery(self):
        t = CopSituationTracker()
        t.update_from_state([
            FakeNode(name="good", status="active", discovered_via="TCPClientInterface"),
            FakeNode(name="bad", status="stale", discovered_via="TCPClientInterface"),
        ])
        snap = t.snapshot()
        messages = [l.message for l in snap.lines]
        assert any("1 node [TCP]" in m for m in messages)   # active only
        assert any("1 node stale" in m for m in messages)   # anomaly line


class TestUnread:

    def test_shows_unread_count_and_names(self):
        t = CopSituationTracker()
        t.update_from_state(
            [],
            unread_map={"ih_alice": 2, "ih_bob": 1},
            node_name_map={"ih_alice": "Alice", "ih_bob": "Bob"},
        )
        snap = t.snapshot()
        line = next(l for l in snap.lines if l.priority == SituationPriority.ACTIONABLE)
        assert "3 unread" in line.message
        assert "Alice" in line.message
        assert "Bob" in line.message

    def test_truncates_at_3_names(self):
        t = CopSituationTracker()
        t.update_from_state(
            [],
            unread_map={"a": 1, "b": 1, "c": 1, "d": 1},
            node_name_map={"a": "A", "b": "B", "c": "C", "d": "D"},
        )
        line = next(l for l in t.snapshot().lines if l.priority == SituationPriority.ACTIONABLE)
        assert "+1" in line.message

    def test_zero_unread_no_line(self):
        t = CopSituationTracker()
        t.update_from_state([], unread_map={"a": 0})
        assert not any(l.priority == SituationPriority.ACTIONABLE for l in t.snapshot().lines)


class TestHubStatus:

    def test_disconnected_shows_line(self):
        t = CopSituationTracker()
        t.update_from_state([], hub_status="disconnected")
        assert any("hub disconnected" in l.message for l in t.snapshot().lines)

    def test_connected_no_line(self):
        t = CopSituationTracker()
        t.update_from_state([], hub_status="connected")
        assert not any("hub" in l.message for l in t.snapshot().lines)

    def test_unknown_no_line(self):
        t = CopSituationTracker()
        t.update_from_state([], hub_status="unknown")
        assert not any("hub" in l.message for l in t.snapshot().lines)


# ---------------------------------------------------------------------------
# CopSituationTracker — ingest (event-driven / ephemeral)
# ---------------------------------------------------------------------------

class TestIngestFileEvents:

    def test_file_offer_creates_situation(self):
        t = CopSituationTracker()
        t.ingest(_event("message_changed", "file_offer",
                         peer_name="Alice", filename="report.pdf"))
        snap = t.snapshot()
        assert any("file from Alice" in l.message and "report.pdf" in l.message
                   for l in snap.lines)

    def test_file_complete_creates_situation(self):
        t = CopSituationTracker()
        t.ingest(_event("message_changed", "file_complete",
                         peer_name="Alice", filename="report.pdf"))
        snap = t.snapshot()
        assert any("transfer complete" in l.message for l in snap.lines)

    def test_file_priority_is_file(self):
        t = CopSituationTracker()
        t.ingest(_event("message_changed", "file_offer", peer_name="X", filename="x.bin"))
        line = next(l for l in t.snapshot().lines if "file" in l.message)
        assert line.priority == SituationPriority.FILE


class TestIngestPQCEvents:

    def test_pqc_established_creates_situation(self):
        t = CopSituationTracker()
        t.ingest(_event("link_changed", "pqc_established", peer_name="relay-east"))
        snap = t.snapshot()
        assert any("PQC session with relay-east" in l.message for l in snap.lines)

    def test_pqc_rekey_creates_situation(self):
        t = CopSituationTracker()
        t.ingest(_event("link_changed", "pqc_rekey", peer_name="relay-east"))
        snap = t.snapshot()
        assert any("PQC rekey with relay-east" in l.message for l in snap.lines)

    def test_pqc_priority_is_security(self):
        t = CopSituationTracker()
        t.ingest(_event("link_changed", "pqc_established", peer_name="X"))
        line = next(l for l in t.snapshot().lines if "PQC" in l.message)
        assert line.priority == SituationPriority.SECURITY


class TestIngestIgnoredEvents:

    @pytest.mark.parametrize("et,action", [
        ("node_changed", "announced"),
        ("node_changed", "stale"),
        ("message_changed", "received"),
        ("message_changed", "delivered"),
        ("message_changed", "read"),
        ("hub_changed", "connected"),
        ("hub_changed", "disconnected"),
        ("link_changed", "established"),
        ("link_changed", "lost"),
        ("config_changed", "saved"),
    ])
    def test_ignored_event_creates_no_situation(self, et, action):
        t = CopSituationTracker()
        t.ingest(_event(et, action, peer_name="x"))
        assert t.snapshot().is_empty


class TestEphemeralCap:

    def test_caps_at_4(self):
        t = CopSituationTracker()
        for i in range(6):
            t.ingest(_event("link_changed", "pqc_established", peer_name=f"peer-{i}"))
        assert len(t._ephemerals) == 4


class TestEphemeralAging:

    def test_dims_after_10_minutes(self, monkeypatch):
        t = CopSituationTracker()
        t.ingest(_event("link_changed", "pqc_established", peer_name="x"))
        # Backdate the ephemeral
        t._ephemerals[0].created_at -= 11 * 60
        line = next(l for l in t.snapshot().lines if "PQC" in l.message)
        assert line.dim

    def test_drops_after_30_minutes(self, monkeypatch):
        t = CopSituationTracker()
        t.ingest(_event("link_changed", "pqc_established", peer_name="x"))
        t._ephemerals[0].created_at -= 31 * 60
        assert t.snapshot().is_empty


# ---------------------------------------------------------------------------
# Priority ordering and cap
# ---------------------------------------------------------------------------

class TestPriorityOrdering:

    def test_anomaly_before_unread_before_discovery(self):
        t = CopSituationTracker()
        t.update_from_state(
            [
                FakeNode(name="good", status="active", discovered_via="AutoInterface"),
                FakeNode(name="bad", status="stale", discovered_via="TCPClientInterface"),
            ],
            unread_map={"ih_alice": 1},
            node_name_map={"ih_alice": "Alice"},
        )
        lines = t.snapshot().lines
        assert lines[0].priority == SituationPriority.ANOMALY
        assert lines[1].priority == SituationPriority.ACTIONABLE
        assert lines[2].priority == SituationPriority.INFO


class TestMaxSituations:

    def test_caps_at_6(self):
        t = CopSituationTracker()
        nodes = [
            FakeNode(name=f"n-{i}", status="active", discovered_via=f"iface-{i}")
            for i in range(8)
        ]
        t.update_from_state(nodes, unread_map={"ih1": 1}, hub_status="disconnected")
        assert len(t.snapshot().lines) <= 6


# ---------------------------------------------------------------------------
# update_from_state replaces, does not accumulate
# ---------------------------------------------------------------------------

class TestStateless:

    def test_replaces_not_accumulates(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="a"), FakeNode(name="b")])
        assert any("2 nodes" in l.message for l in t.snapshot().lines)
        t.update_from_state([FakeNode(name="a")])
        messages = [l.message for l in t.snapshot().lines]
        assert any("1 node" in m for m in messages)
        assert not any("2 nodes" in m for m in messages)

    def test_anomaly_clears_when_node_recovers(self):
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="x", status="stale")])
        assert any("stale" in l.message for l in t.snapshot().lines)
        t.update_from_state([FakeNode(name="x", status="active")])
        assert not any("stale" in l.message for l in t.snapshot().lines)


# ---------------------------------------------------------------------------
# CopActivitySummary widget (presentation-only)
# ---------------------------------------------------------------------------

class TestCopActivitySummaryWidget:

    def _make_snapshot(self, tracker: CopSituationTracker) -> CopSituationSnapshot:
        return tracker.snapshot()

    def test_empty_snapshot_shows_placeholder(self):
        w = CopActivitySummary()
        t = CopSituationTracker()
        w.apply_snapshot(t.snapshot())
        assert "no recent activity" in w.render()

    def test_no_snapshot_shows_placeholder(self):
        w = CopActivitySummary()
        assert "no recent activity" in w.render()

    def test_renders_situation_messages(self):
        w = CopActivitySummary()
        t = CopSituationTracker()
        t.update_from_state(
            [],
            unread_map={"ih_alice": 2},
            node_name_map={"ih_alice": "Alice"},
        )
        w.apply_snapshot(t.snapshot())
        output = w.render()
        assert "unread" in output
        assert "Alice" in output

    def test_apply_snapshot_replaces(self):
        w = CopActivitySummary()
        t = CopSituationTracker()
        t.update_from_state([FakeNode(name="x", status="stale")])
        w.apply_snapshot(t.snapshot())
        assert "stale" in w.render()

        t2 = CopSituationTracker()
        t2.update_from_state([FakeNode(name="x", status="active")])
        w.apply_snapshot(t2.snapshot())
        assert "stale" not in w.render()


# ---------------------------------------------------------------------------
# Dashboard integration: on_daemon_event routes through tracker
# ---------------------------------------------------------------------------

class TestDashboardDaemonEventRouting:

    @pytest.mark.asyncio
    async def test_on_daemon_event_pushes_snapshot(self):
        """on_daemon_event must call tracker.ingest + apply_snapshot on widget."""
        from unittest.mock import patch

        from styrened.tui.screens.dashboard import DashboardScreen

        screen = DashboardScreen()
        cop_widget = MagicMock()

        with patch.object(screen, "query_one", return_value=cop_widget):
            event = DaemonEvent(
                event_type="link_changed",
                action="pqc_established",
                data={"peer_name": "relay-east"},
            )
            screen.on_daemon_event(event)

        cop_widget.apply_snapshot.assert_called_once()
        snap = cop_widget.apply_snapshot.call_args[0][0]
        assert any("PQC session with relay-east" in l.message for l in snap.lines)

    @pytest.mark.asyncio
    async def test_activity_subscription_posts_daemon_event(self):
        """Activity subscription posts DaemonEvent; no longer calls add_ephemeral."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        from styrened.ipc.protocol import IPCMessageType
        from styrened.tui.screens.dashboard import DashboardScreen

        screen = DashboardScreen()
        bridge = MagicMock()
        bridge.subscribe_activity = AsyncMock(return_value=True)

        async def _iter_events(_event_type):
            yield (IPCMessageType.EVENT_ACTIVITY, {"type": "pqc_established", "peer_name": "test"})

        bridge.iter_events = _iter_events
        screen.post_message = MagicMock()

        with patch.object(
            DashboardScreen, "_ipc_bridge",
            new_callable=PropertyMock, return_value=bridge,
        ):
            await screen._subscribe_activity()

        screen.post_message.assert_called_once()
        posted = screen.post_message.call_args[0][0]
        assert isinstance(posted, DaemonEvent)
        assert posted.event_type == "link_changed"
        assert posted.action == "pqc_established"
