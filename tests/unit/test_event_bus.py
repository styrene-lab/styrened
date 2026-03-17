"""Tests for the EventBus — styrened's central nervous system."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from styrened.services.event_bus import (
    _MAX_CONSECUTIVE_FAILURES,
    _SLOW_SUBSCRIBER_MS,
    TRACE,
    Event,
    EventBus,
)

# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


class TestEvent:
    def test_defaults(self) -> None:
        e = Event(event_type="node_changed", action="announced")
        assert e.event_type == "node_changed"
        assert e.action == "announced"
        assert e.data == {}
        assert e.timestamp <= time.time()

    def test_data_payload(self) -> None:
        e = Event(event_type="node_changed", action="announced", data={"dest_hash": "abc"})
        assert e.data["dest_hash"] == "abc"


# ---------------------------------------------------------------------------
# Core subscribe / emit / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribeAndEmit:
    @pytest.mark.asyncio
    async def test_subscriber_receives_event(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("node_changed", handler)
        await bus.emit("node_changed", action="announced", dest_hash="abc123")
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].event_type == "node_changed"
        assert received[0].action == "announced"
        assert received[0].data["dest_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_fan_out_to_multiple_subscribers(self) -> None:
        bus = EventBus()
        calls_a: list[Event] = []
        calls_b: list[Event] = []

        async def handler_a(event: Event) -> None:
            calls_a.append(event)

        async def handler_b(event: Event) -> None:
            calls_b.append(event)

        bus.subscribe("node_changed", handler_a)
        bus.subscribe("node_changed", handler_b)
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        assert len(calls_a) == 1
        assert len(calls_b) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        calls: list[Event] = []

        async def handler(event: Event) -> None:
            calls.append(event)

        bus.subscribe("node_changed", handler)
        bus.unsubscribe("node_changed", handler)
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_is_noop(self) -> None:
        bus = EventBus()

        async def handler(event: Event) -> None:
            pass

        bus.unsubscribe("node_changed", handler)  # Should not raise

    @pytest.mark.asyncio
    async def test_emit_no_subscribers_is_noop(self) -> None:
        bus = EventBus()
        await bus.emit("hub_changed", action="disconnected")  # Should not raise

    @pytest.mark.asyncio
    async def test_emit_does_not_block_caller(self) -> None:
        bus = EventBus()

        async def slow_handler(event: Event) -> None:
            await asyncio.sleep(1.0)

        bus.subscribe("node_changed", slow_handler)

        start = time.monotonic()
        await bus.emit("node_changed", action="announced")
        elapsed = time.monotonic() - start

        assert elapsed < 0.1  # emit returned immediately

    @pytest.mark.asyncio
    async def test_different_event_types_isolated(self) -> None:
        bus = EventBus()
        node_calls: list[Event] = []
        hub_calls: list[Event] = []

        async def node_handler(event: Event) -> None:
            node_calls.append(event)

        async def hub_handler(event: Event) -> None:
            hub_calls.append(event)

        bus.subscribe("node_changed", node_handler)
        bus.subscribe("hub_changed", hub_handler)

        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        assert len(node_calls) == 1
        assert len(hub_calls) == 0

    @pytest.mark.asyncio
    async def test_duplicate_subscribe_ignored(self) -> None:
        bus = EventBus()
        calls: list[Event] = []

        async def handler(event: Event) -> None:
            calls.append(event)

        bus.subscribe("node_changed", handler)
        bus.subscribe("node_changed", handler)  # Duplicate
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Subscriber isolation
# ---------------------------------------------------------------------------


class TestSubscriberIsolation:
    @pytest.mark.asyncio
    async def test_exception_does_not_kill_other_subscribers(self) -> None:
        bus = EventBus()
        calls: list[Event] = []

        async def bad_handler(event: Event) -> None:
            raise RuntimeError("boom")

        async def good_handler(event: Event) -> None:
            calls.append(event)

        bus.subscribe("node_changed", bad_handler)
        bus.subscribe("node_changed", good_handler)
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_exception_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()

        async def bad_handler(event: Event) -> None:
            raise ValueError("test error")

        bus.subscribe("node_changed", bad_handler)
        with caplog.at_level(logging.ERROR, logger="styrened.services.event_bus"):
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep(0.05)

        assert any("failed" in r.message and "test error" in r.message for r in caplog.records) or \
               any("failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_auto_remove_after_max_failures(self) -> None:
        """Subscriber is auto-removed after MAX_CONSECUTIVE_FAILURES."""
        bus = EventBus()

        async def always_fails(event: Event) -> None:
            raise RuntimeError("persistent failure")

        bus.subscribe("node_changed", always_fails)
        assert bus.subscriber_count.get("node_changed") == 1

        # Emit enough times to trigger auto-removal
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep(0.05)

        assert bus.subscriber_count.get("node_changed", 0) == 0

    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(self) -> None:
        """A successful dispatch resets the failure counter."""
        bus = EventBus()
        call_count = 0

        async def flaky_handler(event: Event) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("transient")
            # Third call succeeds

        bus.subscribe("node_changed", flaky_handler)

        # Two failures
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        # Third succeeds — counter resets
        await bus.emit("node_changed", action="announced")
        await asyncio.sleep(0.05)

        # Subscriber should still be registered (counter reset)
        assert bus.subscriber_count.get("node_changed") == 1

    @pytest.mark.asyncio
    async def test_recovery_logged_at_info(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()
        call_count = 0

        async def recovers(event: Event) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")

        bus.subscribe("node_changed", recovers)

        with caplog.at_level(logging.INFO, logger="styrened.services.event_bus"):
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep(0.05)
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep(0.05)

        assert any("recovered" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Slow subscriber warning
# ---------------------------------------------------------------------------


class TestSlowSubscriberWarning:
    @pytest.mark.asyncio
    async def test_slow_subscriber_logged_at_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = EventBus()

        async def slow_handler(event: Event) -> None:
            await asyncio.sleep((_SLOW_SUBSCRIBER_MS + 100) / 1000)

        bus.subscribe("node_changed", slow_handler)
        with caplog.at_level(logging.WARNING, logger="styrened.services.event_bus"):
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep((_SLOW_SUBSCRIBER_MS + 200) / 1000)

        assert any("slow subscriber" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Stats and diagnostics
# ---------------------------------------------------------------------------


class TestStats:
    def test_subscriber_count(self) -> None:
        bus = EventBus()

        async def h1(e: Event) -> None:
            pass

        async def h2(e: Event) -> None:
            pass

        bus.subscribe("node_changed", h1)
        bus.subscribe("node_changed", h2)
        bus.subscribe("hub_changed", h1)

        counts = bus.subscriber_count
        assert counts == {"node_changed": 2, "hub_changed": 1}

    @pytest.mark.asyncio
    async def test_emit_counts_tracked(self) -> None:
        bus = EventBus()
        await bus.emit("node_changed", action="announced")
        await bus.emit("node_changed", action="stale")
        await bus.emit("hub_changed", action="connected")

        stats = bus.stats
        assert stats["emit_counts"]["node_changed"] == 2
        assert stats["emit_counts"]["hub_changed"] == 1

    def test_log_summary_does_not_raise(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()
        with caplog.at_level(logging.INFO, logger="styrened.services.event_bus"):
            bus.log_summary()
        assert any("EventBus:" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Trace-level logging
# ---------------------------------------------------------------------------


class TestTraceLogging:
    @pytest.mark.asyncio
    async def test_trace_logs_payload(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()

        async def noop(e: Event) -> None:
            pass

        bus.subscribe("node_changed", noop)
        with caplog.at_level(TRACE, logger="styrened.services.event_bus"):
            await bus.emit("node_changed", action="announced", dest_hash="abc")
            await asyncio.sleep(0.05)

        trace_records = [r for r in caplog.records if r.levelno == TRACE]
        assert len(trace_records) >= 1
        assert any("payload" in r.message for r in trace_records)

    @pytest.mark.asyncio
    async def test_trace_logs_dispatch_timing(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()

        async def noop(e: Event) -> None:
            pass

        bus.subscribe("node_changed", noop)
        with caplog.at_level(TRACE, logger="styrened.services.event_bus"):
            await bus.emit("node_changed", action="announced")
            await asyncio.sleep(0.05)

        trace_records = [r for r in caplog.records if r.levelno == TRACE]
        assert any("handled" in r.message and "ms" in r.message for r in trace_records)


# ---------------------------------------------------------------------------
# _bridge_to_event_bus mapping (daemon-level integration)
# ---------------------------------------------------------------------------


class TestNotificationToBusMapping:
    """Test the daemon's notification type → EventBus type mapping."""

    def test_known_mappings(self) -> None:
        """All known notification types should map to bus types."""
        from styrened.daemon import StyreneDaemon

        mapping = StyreneDaemon._NOTIFICATION_TO_BUS
        # node events
        assert mapping["device_discovered"] == ("node_changed", "announced")
        assert mapping["announce_sent"] == ("node_changed", "announce_sent")
        # message events
        assert mapping["new_message"] == ("message_changed", "received")
        assert mapping["delivery_status"] == ("message_changed", "delivery_status")
        # link events
        assert mapping["pqc_established"] == ("link_changed", "pqc_established")
        assert mapping["link_established"] == ("link_changed", "established")
        # hub events
        assert mapping["hub_connected"] == ("hub_changed", "connected")
        # config events
        assert mapping["config_saved"] == ("config_changed", "saved")

    def test_all_five_bus_types_covered(self) -> None:
        """The mapping should cover all 5 coarse bus types."""
        from styrened.daemon import StyreneDaemon

        bus_types = {v[0] for v in StyreneDaemon._NOTIFICATION_TO_BUS.values()}
        assert bus_types == {
            "node_changed",
            "message_changed",
            "link_changed",
            "hub_changed",
            "config_changed",
        }
