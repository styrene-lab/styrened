"""Styrened's central nervous system — a minimal async event bus.

Simple observer pattern: subscribe/unsubscribe/emit.  Events are
fire-and-forget via ``asyncio.create_task`` — emit never blocks the
caller.  One subscriber exception does not affect others.

Event types are coarse strings with an ``action`` field for granularity:
  - node_changed    / announced, stale, lost, updated
  - message_changed / received, delivered, read
  - hub_changed     / connected, disconnected, disabled
  - link_changed    / established, lost
  - config_changed  / saved, adapter_toggled
  - adapter_changed / ready, warming, degraded, probing, disabled

Events carry minimal payload — consumers re-read from stores for full state.

Logging escalation:
  ERROR   — subscriber exception (with traceback)
  WARNING — slow subscriber (>500ms), repeated failures trigger removal
  INFO    — bus lifecycle (started, periodic subscriber summary)
  DEBUG   — every emit (type/action), subscribe/unsubscribe
  TRACE   — full payload dump, per-subscriber dispatch timing
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# TRACE level for deep debugging (below DEBUG=10)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# Thresholds
_SLOW_SUBSCRIBER_MS = 500  # Warn if a subscriber takes longer than this
_MAX_CONSECUTIVE_FAILURES = 5  # Auto-unsubscribe after this many failures

# Type alias for subscriber callbacks
Subscriber = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """A lightweight notification event.

    Attributes:
        event_type: Coarse event category (e.g. ``node_changed``).
        action: Specific action within the type (e.g. ``announced``).
        timestamp: Unix epoch of when the event occurred.
        data: Minimal payload dict — identity keys, not full objects.
    """

    event_type: str
    action: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Async publish-subscribe event bus.

    Usage::

        bus = EventBus()
        bus.subscribe("node_changed", my_handler)
        await bus.emit("node_changed", action="announced", dest_hash="abc")
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._failure_counts: dict[int, int] = defaultdict(int)  # id(callback) → count
        self._emit_counts: dict[str, int] = defaultdict(int)  # event_type → count
        logger.info("EventBus initialized")

    def subscribe(self, event_type: str, callback: Subscriber) -> None:
        """Register a callback for an event type.

        Args:
            event_type: Event type string to listen for.
            callback: Async callable receiving an ``Event`` instance.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)
            # Reset failure count on (re)subscribe
            self._failure_counts.pop(id(callback), None)
            logger.debug(
                "EventBus: +subscriber %s → %s (total: %d)",
                callback.__qualname__,
                event_type,
                len(self._subscribers[event_type]),
            )

    def unsubscribe(self, event_type: str, callback: Subscriber) -> None:
        """Remove a callback from an event type.

        Args:
            event_type: Event type string.
            callback: Previously registered callback.
        """
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
                self._failure_counts.pop(id(callback), None)
                logger.debug(
                    "EventBus: -subscriber %s ← %s (remaining: %d)",
                    callback.__qualname__,
                    event_type,
                    len(self._subscribers[event_type]),
                )
            except ValueError:
                pass

    async def emit(self, event_type: str, action: str, **data: Any) -> None:
        """Emit an event to all subscribers of the given type.

        Returns immediately — subscriber callbacks run as detached tasks.
        Exceptions in individual subscribers are logged but do not propagate.

        Args:
            event_type: Event type string.
            action: Specific action within the type.
            **data: Additional payload fields.
        """
        callbacks = self._subscribers.get(event_type, [])
        self._emit_counts[event_type] += 1

        if not callbacks:
            logger.debug(
                "EventBus: emit %s/%s → 0 subscribers",
                event_type, action,
            )
            return

        event = Event(event_type=event_type, action=action, data=data)

        logger.debug(
            "EventBus: emit %s/%s → %d subscriber(s)",
            event_type, action, len(callbacks),
        )
        if logger.isEnabledFor(TRACE):
            logger.log(TRACE, "EventBus: payload %s/%s: %r", event_type, action, data)

        for callback in list(callbacks):  # Copy list in case of mutation
            asyncio.create_task(
                self._safe_dispatch(callback, event, event_type)
            )

    async def _safe_dispatch(
        self, callback: Subscriber, event: Event, event_type: str
    ) -> None:
        """Invoke a subscriber callback with exception isolation and timing."""
        name = callback.__qualname__
        start = time.monotonic()

        try:
            await callback(event)
        except Exception:
            cb_id = id(callback)
            self._failure_counts[cb_id] += 1
            count = self._failure_counts[cb_id]

            logger.error(
                "EventBus: subscriber %s failed on %s/%s (failure %d/%d)",
                name,
                event.event_type,
                event.action,
                count,
                _MAX_CONSECUTIVE_FAILURES,
                exc_info=True,
            )

            if count >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "EventBus: auto-removing %s from %s after %d consecutive failures",
                    name, event_type, count,
                )
                self.unsubscribe(event_type, callback)
            return
        else:
            # Reset failure count on success
            cb_id = id(callback)
            if cb_id in self._failure_counts:
                prev = self._failure_counts.pop(cb_id)
                if prev > 0:
                    logger.info(
                        "EventBus: subscriber %s recovered after %d failure(s)",
                        name, prev,
                    )

        elapsed_ms = (time.monotonic() - start) * 1000

        if logger.isEnabledFor(TRACE):
            logger.log(
                TRACE,
                "EventBus: %s handled %s/%s in %.1fms",
                name, event.event_type, event.action, elapsed_ms,
            )

        if elapsed_ms > _SLOW_SUBSCRIBER_MS:
            logger.warning(
                "EventBus: slow subscriber %s took %.0fms on %s/%s (threshold: %dms)",
                name, elapsed_ms, event.event_type, event.action, _SLOW_SUBSCRIBER_MS,
            )

    @property
    def subscriber_count(self) -> dict[str, int]:
        """Return a snapshot of subscriber counts per event type."""
        return {k: len(v) for k, v in self._subscribers.items() if v}

    @property
    def stats(self) -> dict[str, Any]:
        """Return bus statistics for diagnostics."""
        return {
            "subscribers": self.subscriber_count,
            "emit_counts": dict(self._emit_counts),
            "active_failure_tracking": len(self._failure_counts),
        }

    def log_summary(self) -> None:
        """Log a summary of bus state at INFO level.

        Call periodically (e.g. from daemon health check) for operational
        visibility without enabling DEBUG.
        """
        subs = self.subscriber_count
        emits = dict(self._emit_counts)
        logger.info(
            "EventBus: subscribers=%s emits=%s",
            subs or "(none)", emits or "(none)",
        )
