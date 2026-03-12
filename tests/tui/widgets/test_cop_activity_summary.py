"""Tests for CopActivitySummary widget — coalesced COP situation lines."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from styrened.tui.widgets.cop_activity_summary import (
    CopActivitySummary,
    SituationPriority,
    _RESOLVED_TTL,
    transport_label,
)


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
        ("SomeNewInterface", "Some"),  # fallback: first 4 chars
    ])
    def test_transport_label(self, via, expected):
        assert transport_label(via) == expected

    def test_with_next_hop_suffix(self):
        assert transport_label("AutoInterface → deadbeef") == "Auto"


# ---------------------------------------------------------------------------
# Event coalescing
# ---------------------------------------------------------------------------

class TestUnreadCoalescing:

    def test_groups_by_peer(self):
        w = CopActivitySummary()
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.ingest_event("new_message", {"peer_name": "bravo", "is_outgoing": False})
        assert w._unread == {"alpha": 2, "bravo": 1}

    def test_ignores_outgoing(self):
        w = CopActivitySummary()
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": True})
        assert w._unread == {}

    def test_render_contains_count_and_names(self):
        w = CopActivitySummary()
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.ingest_event("new_message", {"peer_name": "bravo", "is_outgoing": False})
        output = w.render()
        assert "3 unread" in output
        assert "alpha" in output
        assert "bravo" in output

    def test_clear_unread_specific_peer(self):
        w = CopActivitySummary()
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.ingest_event("new_message", {"peer_name": "bravo", "is_outgoing": False})
        w.clear_unread("alpha")
        assert "alpha" not in w._unread
        assert "bravo" in w._unread

    def test_clear_unread_all(self):
        w = CopActivitySummary()
        w.ingest_event("new_message", {"peer_name": "alpha", "is_outgoing": False})
        w.clear_unread()
        assert w._unread == {}


class TestNodeDiscoveryCoalescing:

    def test_coalesces_per_transport(self):
        w = CopActivitySummary()
        w.ingest_event("device_discovered", {
            "peer_hash": "aaa", "metadata": {"discovered_via": "TCPClientInterface", "name": "n1", "status": "active"},
        })
        w.ingest_event("device_discovered", {
            "peer_hash": "bbb", "metadata": {"discovered_via": "TCPClientInterface", "name": "n2", "status": "active"},
        })
        w.ingest_event("device_discovered", {
            "peer_hash": "ccc", "metadata": {"discovered_via": "AutoInterface", "name": "n3", "status": "active"},
        })
        assert w._discoveries["TCP"][0] == 2
        assert w._discoveries["Auto"][0] == 1

    def test_render_shows_transport_tags(self):
        w = CopActivitySummary()
        w.ingest_event("device_discovered", {
            "peer_hash": "aaa", "metadata": {"discovered_via": "AutoInterface", "name": "n1", "status": "active"},
        })
        output = w.render()
        assert "[Auto]" in output
        assert "1 node discovered" in output

    def test_plural_nodes(self):
        w = CopActivitySummary()
        for i in range(3):
            w.ingest_event("device_discovered", {
                "peer_hash": f"h{i}", "metadata": {"discovered_via": "TCPClientInterface", "name": f"n{i}", "status": "active"},
            })
        output = w.render()
        assert "3 nodes discovered" in output


class TestNodeAnomaly:

    def test_offline_creates_anomaly(self):
        w = CopActivitySummary()
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        assert "relay-east" in w._anomalies
        assert not w._anomalies["relay-east"].is_resolved

    def test_online_resolves_anomaly(self):
        w = CopActivitySummary()
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "active"},
        })
        assert w._anomalies["relay-east"].is_resolved

    def test_anomaly_includes_transport_tag(self):
        w = CopActivitySummary()
        # First discover via Ygg, then lose
        w.ingest_event("device_discovered", {
            "peer_hash": "aaa", "metadata": {"discovered_via": "YggdrasilInterface", "name": "relay-east", "status": "active"},
        })
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        output = w.render()
        assert "[Ygg]" in output
        assert "relay-east" in output

    def test_rediscovery_resolves_anomaly(self):
        w = CopActivitySummary()
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        w.ingest_event("device_discovered", {
            "peer_hash": "aaa", "metadata": {"discovered_via": "TCPClientInterface", "name": "relay-east", "status": "active"},
        })
        assert w._anomalies["relay-east"].is_resolved


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:

    def test_anomaly_before_unread_before_discovery(self):
        w = CopActivitySummary()
        # Add discovery first
        w.ingest_event("device_discovered", {
            "peer_hash": "aaa", "metadata": {"discovered_via": "AutoInterface", "name": "n1", "status": "active"},
        })
        # Add unread
        w.ingest_event("new_message", {"peer_name": "alice", "is_outgoing": False})
        # Add anomaly
        w.ingest_event("device_updated", {
            "peer_hash": "bbb", "metadata": {"name": "relay-east", "status": "offline"},
        })

        output = w.render()
        lines = output.strip().split("\n")
        assert len(lines) == 3
        # Anomaly first (▲), then unread (✉), then discovery (●)
        assert "▲" in lines[0]
        assert "✉" in lines[1]
        assert "discovered" in lines[2]


# ---------------------------------------------------------------------------
# Aging
# ---------------------------------------------------------------------------

class TestAging:

    def test_resolved_anomaly_shows_checkmark(self):
        w = CopActivitySummary()
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "active"},
        })
        output = w.render()
        assert "✓" in output

    def test_expired_situations_removed(self):
        w = CopActivitySummary()
        w.ingest_event("device_updated", {
            "peer_hash": "aaa", "metadata": {"name": "relay-east", "status": "offline"},
        })
        w._anomalies["relay-east"].resolved_at = time.monotonic() - _RESOLVED_TTL - 1
        w._age_situations()
        assert "relay-east" not in w._anomalies


# ---------------------------------------------------------------------------
# Ignored events
# ---------------------------------------------------------------------------

class TestIgnoredEvents:

    @pytest.mark.parametrize("event_type", [
        "delivery_status",
        "announce_sent",
        "rpc_received",
        "contact_set",
        "contact_removed",
        "conversation_read",
        "conversation_deleted",
        "identity_changed",
        "auto_reply_changed",
    ])
    def test_ignored_events_create_no_situations(self, event_type):
        w = CopActivitySummary()
        w.ingest_event(event_type, {"peer_hash": "abc"})
        output = w.render()
        assert "no recent activity" in output


# ---------------------------------------------------------------------------
# Max situations
# ---------------------------------------------------------------------------

class TestMaxSituations:

    def test_caps_at_6(self):
        w = CopActivitySummary()
        # Create 8 anomalies
        for i in range(8):
            w.ingest_event("device_updated", {
                "peer_hash": f"h{i}", "metadata": {"name": f"node-{i}", "status": "offline"},
            })
        output = w.render()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 6


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:

    def test_empty_shows_no_recent_activity(self):
        w = CopActivitySummary()
        output = w.render()
        assert "no recent activity" in output
