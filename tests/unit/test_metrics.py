"""Unit tests for Prometheus metrics endpoint.

Tests the StyreneCollector snapshot gauges, event counter label
acceptance, and the /metrics FastAPI route.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (web extra)")

from unittest.mock import MagicMock

from styrened.web.metrics import (
    StyreneCollector,
    announces_total,
    auto_replies_total,
    create_metrics_router,
    devices_discovered_total,
    init_metrics,
    messages_total,
    rpc_requests_total,
    security_events_total,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_daemon(
    *,
    start_time: float = 1_000_000.0,
    nodes: list | None = None,
    paths: list | None = None,
    conversations: list | None = None,
    pending_count: int = 0,
    node_store: object | None = "auto",
    conversation_service: object | None = "auto",
    rpc_client: object | None = "auto",
) -> MagicMock:
    """Build a mock StyreneDaemon with configurable service stubs."""
    daemon = MagicMock()
    daemon._start_time = start_time

    # Node store
    if node_store == "auto":
        ns = MagicMock()
        ns.get_all_nodes.return_value = nodes or []
        ns.get_all_paths.return_value = paths or []
        daemon._node_store = ns
    else:
        daemon._node_store = node_store

    # Conversation service
    if conversation_service == "auto":
        cs = MagicMock()
        cs.list_conversations.return_value = conversations or []
        daemon._conversation_service = cs
    else:
        daemon._conversation_service = conversation_service

    # RPC client
    if rpc_client == "auto":
        rc = MagicMock()
        rc.pending_count = pending_count
        daemon._rpc_client = rc
    else:
        daemon._rpc_client = rpc_client

    return daemon


def _make_node(status: str = "online", device_type: str = "node") -> MagicMock:
    """Create a mock node with status and device_type enums."""
    node = MagicMock()
    node.status.value = status
    node.device_type.value = device_type
    return node


def _make_path(hops: int = 1) -> MagicMock:
    """Create a mock path entry."""
    path = MagicMock()
    path.hops = hops
    return path


def _make_conversation(unread: int = 0) -> MagicMock:
    """Create a mock conversation."""
    conv = MagicMock()
    conv.unread_count = unread
    return conv


# ---------------------------------------------------------------------------
# TestStyreneCollector
# ---------------------------------------------------------------------------


class TestStyreneCollector:
    """Snapshot gauge collection with mock daemon."""

    def test_uptime_gauge(self) -> None:
        """Uptime gauge reflects time since daemon start."""
        daemon = _make_mock_daemon(start_time=0.0)
        collector = StyreneCollector(daemon)

        metrics = collector.collect()
        uptime_metric = next(m for m in metrics if m.name == "styrened_uptime_seconds")

        # Should be a positive number (current time minus epoch 0)
        assert uptime_metric.samples[0].value > 0

    def test_devices_gauge(self) -> None:
        """Devices gauge counts each node with status/type labels."""
        nodes = [
            _make_node("online", "node"),
            _make_node("online", "hub"),
            _make_node("offline", "node"),
        ]
        daemon = _make_mock_daemon(nodes=nodes)
        collector = StyreneCollector(daemon)

        metrics = collector.collect()
        devices_metric = next(m for m in metrics if m.name == "styrened_devices")

        # 3 samples — one per node
        assert len(devices_metric.samples) == 3

    def test_paths_gauge(self) -> None:
        """Paths gauge counts each path with hops label."""
        paths = [_make_path(1), _make_path(2), _make_path(1)]
        daemon = _make_mock_daemon(paths=paths)
        collector = StyreneCollector(daemon)

        metrics = collector.collect()
        paths_metric = next(m for m in metrics if m.name == "styrened_paths")

        assert len(paths_metric.samples) == 3

    def test_conversations_and_unread(self) -> None:
        """Conversation and unread gauges reflect service data."""
        convos = [_make_conversation(3), _make_conversation(0), _make_conversation(5)]
        daemon = _make_mock_daemon(conversations=convos)
        collector = StyreneCollector(daemon)

        metrics = collector.collect()
        conv_metric = next(m for m in metrics if m.name == "styrened_conversations")
        unread_metric = next(m for m in metrics if m.name == "styrened_unread_messages")

        assert conv_metric.samples[0].value == 3
        assert unread_metric.samples[0].value == 8

    def test_pending_rpcs(self) -> None:
        """Pending RPCs gauge reflects rpc_client.pending_count."""
        daemon = _make_mock_daemon(pending_count=7)
        collector = StyreneCollector(daemon)

        metrics = collector.collect()
        pending = next(m for m in metrics if m.name == "styrened_pending_rpcs")

        assert pending.samples[0].value == 7

    def test_none_services_yield_zero(self) -> None:
        """When services are None, gauges should be zero (not crash)."""
        daemon = _make_mock_daemon(
            node_store=None,
            conversation_service=None,
            rpc_client=None,
        )
        collector = StyreneCollector(daemon)

        metrics = collector.collect()

        # Should not raise, and all gauges should have samples
        names = {m.name for m in metrics}
        assert "styrened_uptime_seconds" in names
        assert "styrened_devices" in names
        assert "styrened_conversations" in names
        assert "styrened_pending_rpcs" in names

    def test_service_exception_handled(self) -> None:
        """If a service raises, the gauge still appears with zero/empty."""
        daemon = _make_mock_daemon()
        daemon._node_store.get_all_nodes.side_effect = RuntimeError("db gone")
        daemon._conversation_service.list_conversations.side_effect = RuntimeError("db gone")

        collector = StyreneCollector(daemon)
        metrics = collector.collect()

        # Should not raise
        names = {m.name for m in metrics}
        assert "styrened_devices" in names
        assert "styrened_conversations" in names


# ---------------------------------------------------------------------------
# TestEventCounters
# ---------------------------------------------------------------------------


class TestEventCounters:
    """Verify counter label acceptance — catches label mismatches early."""

    def test_messages_total_labels(self) -> None:
        messages_total.labels(direction="incoming", status="received")

    def test_rpc_requests_total_labels(self) -> None:
        rpc_requests_total.labels(type="STATUS_REQUEST", result="dispatched")

    def test_announces_total_labels(self) -> None:
        announces_total.labels(result="success")
        announces_total.labels(result="failure")

    def test_auto_replies_total_labels(self) -> None:
        auto_replies_total.labels(result="sent")
        auto_replies_total.labels(result="cooldown_skip")
        auto_replies_total.labels(result="no_path_skip")

    def test_security_events_total_labels(self) -> None:
        security_events_total.labels(type="auth_rejected")
        security_events_total.labels(type="rate_limited")
        security_events_total.labels(type="replay_detected")

    def test_devices_discovered_total(self) -> None:
        # No labels — just verify inc() works
        devices_discovered_total.inc(0)


# ---------------------------------------------------------------------------
# TestMetricsEndpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """FastAPI TestClient tests for /metrics route."""

    @pytest.fixture
    def client(self):
        """Create a TestClient with metrics router mounted."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_metrics_router()
        app.include_router(router)
        return TestClient(app)

    def test_metrics_returns_200(self, client) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type(self, client) -> None:
        response = client.get("/metrics")
        ct = response.headers["content-type"]
        assert "text/plain" in ct or "text/openmetrics" in ct

    def test_metrics_contains_counter(self, client) -> None:
        """Response body should contain at least the counter HELP lines."""
        response = client.get("/metrics")
        body = response.text
        assert "styrened_messages_total" in body
        assert "styrened_rpc_requests_total" in body

    def test_metrics_contains_gauge_after_init(self, client) -> None:
        """After init_metrics, snapshot gauges appear in output."""
        daemon = _make_mock_daemon()

        # Use a fresh registry to avoid cross-test pollution
        # (init_metrics registers on the module-level REGISTRY which
        #  the router also references, so this works end-to-end)
        init_metrics(daemon)

        response = client.get("/metrics")
        body = response.text

        assert "styrened_uptime_seconds" in body


# ---------------------------------------------------------------------------
# TestInitMetrics
# ---------------------------------------------------------------------------


class TestInitMetrics:
    """init_metrics registration behaviour."""

    def test_double_init_does_not_raise(self) -> None:
        """Calling init_metrics twice should not raise ValueError."""
        daemon = _make_mock_daemon()
        init_metrics(daemon)
        init_metrics(daemon)  # should not raise
