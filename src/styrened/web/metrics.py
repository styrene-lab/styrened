"""Prometheus metrics endpoint for styrened.

Exposes runtime counters and snapshot gauges in Prometheus text exposition
format via a ``GET /metrics`` route.  All objects use a **custom
CollectorRegistry** (not the process-global default) so the module is safe
for library embedding and test isolation.

Counter objects are importable from this module by call-site code using the
lazy ``try/except ImportError`` pattern — keeping ``prometheus_client`` a
truly optional dependency.

Snapshot gauges are computed on scrape (not periodically) via a custom
``Collector`` class, so no wasted DB queries when nothing is scraping.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from prometheus_client import CollectorRegistry, Counter
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom isolated registry
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry()

# ---------------------------------------------------------------------------
# Event counters — incremented at call sites via lazy imports
# ---------------------------------------------------------------------------

messages_total = Counter(
    "styrened_messages_total",
    "Total LXMF messages processed",
    labelnames=["direction", "status"],
    registry=REGISTRY,
)

rpc_requests_total = Counter(
    "styrened_rpc_requests_total",
    "Total RPC requests handled",
    labelnames=["type", "result"],
    registry=REGISTRY,
)

announces_total = Counter(
    "styrened_announces_total",
    "Total RNS announces attempted",
    labelnames=["result"],
    registry=REGISTRY,
)

auto_replies_total = Counter(
    "styrened_auto_replies_total",
    "Total auto-replies processed",
    labelnames=["result"],
    registry=REGISTRY,
)

security_events_total = Counter(
    "styrened_security_events_total",
    "Total security events (auth rejections, rate limits, replays)",
    labelnames=["type"],
    registry=REGISTRY,
)

devices_discovered_total = Counter(
    "styrened_devices_discovered_total",
    "Total devices discovered via announces",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Snapshot gauge collector — computed on scrape
# ---------------------------------------------------------------------------


class StyreneCollector:
    """Custom Prometheus ``Collector`` yielding snapshot gauges.

    Each call to :meth:`collect` queries the daemon's live services and
    yields ``GaugeMetricFamily`` objects.  Missing/None services produce
    zero-valued gauges rather than errors.
    """

    def __init__(self, daemon: StyreneDaemon) -> None:
        self._daemon = daemon

    # -- Collector interface --------------------------------------------------

    def describe(self) -> list[Any]:
        """Return empty list — metrics are described at collect time."""
        return []

    def collect(self) -> list[GaugeMetricFamily]:
        """Yield snapshot gauges by querying daemon services."""
        metrics: list[GaugeMetricFamily] = []

        # Uptime
        uptime = GaugeMetricFamily(
            "styrened_uptime_seconds",
            "Seconds since daemon start",
        )
        uptime.add_metric([], time.time() - self._daemon._start_time)
        metrics.append(uptime)

        # Devices
        devices = GaugeMetricFamily(
            "styrened_devices",
            "Number of known mesh devices",
            labels=["status", "type"],
        )
        try:
            node_store = self._daemon._node_store
            if node_store is not None:
                for node in node_store.get_all_nodes():
                    status = getattr(node, "status", None)
                    status_val = status.value if status else "unknown"
                    dtype = getattr(node, "device_type", None)
                    dtype_val = dtype.value if dtype else "unknown"
                    devices.add_metric([status_val, dtype_val], 1)
        except Exception:
            logger.debug("Failed to collect device metrics", exc_info=True)
        metrics.append(devices)

        # Paths
        paths = GaugeMetricFamily(
            "styrened_paths",
            "Number of known mesh paths",
            labels=["hops"],
        )
        try:
            node_store = self._daemon._node_store
            if node_store is not None:
                for path in node_store.get_all_paths():
                    hops = str(getattr(path, "hops", 0))
                    paths.add_metric([hops], 1)
        except Exception:
            logger.debug("Failed to collect path metrics", exc_info=True)
        metrics.append(paths)

        # Conversations
        conversations = GaugeMetricFamily(
            "styrened_conversations",
            "Number of conversations",
        )
        unread = GaugeMetricFamily(
            "styrened_unread_messages",
            "Total unread message count",
        )
        try:
            conv_service = self._daemon._conversation_service
            if conv_service is not None:
                convos = conv_service.list_conversations()
                conversations.add_metric([], len(convos))
                total_unread = sum(getattr(c, "unread_count", 0) for c in convos)
                unread.add_metric([], total_unread)
            else:
                conversations.add_metric([], 0)
                unread.add_metric([], 0)
        except Exception:
            logger.debug("Failed to collect conversation metrics", exc_info=True)
            conversations.add_metric([], 0)
            unread.add_metric([], 0)
        metrics.append(conversations)
        metrics.append(unread)

        # Pending RPCs
        pending_rpcs = GaugeMetricFamily(
            "styrened_pending_rpcs",
            "Number of pending outbound RPC requests",
        )
        try:
            rpc_client = self._daemon._rpc_client
            if rpc_client is not None:
                pending_rpcs.add_metric([], getattr(rpc_client, "pending_count", 0))
            else:
                pending_rpcs.add_metric([], 0)
        except Exception:
            logger.debug("Failed to collect RPC metrics", exc_info=True)
            pending_rpcs.add_metric([], 0)
        metrics.append(pending_rpcs)

        return metrics


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


def create_metrics_router() -> Any:
    """Create a FastAPI ``APIRouter`` with a single ``GET /metrics`` route.

    Returns:
        Configured APIRouter.
    """
    from fastapi import APIRouter
    from fastapi.responses import Response

    router = APIRouter()

    @router.get("/metrics")
    async def metrics_endpoint() -> Response:
        body = generate_latest(REGISTRY)
        return Response(content=body, media_type=CONTENT_TYPE_LATEST)

    return router


# ---------------------------------------------------------------------------
# Initialization helper
# ---------------------------------------------------------------------------


def init_metrics(daemon: StyreneDaemon) -> None:
    """Register the :class:`StyreneCollector` with :data:`REGISTRY`.

    Safe to call multiple times — duplicate registrations are silently
    ignored.

    Args:
        daemon: Running StyreneDaemon instance.
    """
    collector = StyreneCollector(daemon)
    try:
        REGISTRY.register(collector)
    except ValueError:
        # Already registered (e.g. hot-reload during development)
        pass
