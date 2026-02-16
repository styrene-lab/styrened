"""Observability query helpers for VictoriaLogs, VictoriaMetrics, and Grafana.

Uses kubectl exec into monitoring namespace deployments — no new Python
dependencies required.  All public functions degrade to no-ops when the
observability stack is unreachable (e.g. kind/k3d clusters).
"""

from __future__ import annotations

import json
import logging
import subprocess
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)

# Module-level cache: None = not probed yet, True/False = cached result
_observability_available: bool | None = None

GRAFANA_BASE_URL = "https://grafana.styrene.io"


def is_observability_available() -> bool:
    """Check whether the VictoriaLogs/VictoriaMetrics stack is reachable.

    Probes for the victoria-logs-server deployment in the monitoring namespace.
    The result is cached for the lifetime of the process.

    Returns:
        True if the observability stack is reachable, False otherwise.
    """
    global _observability_available

    if _observability_available is not None:
        return _observability_available

    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deploy",
                "victoria-logs-server",
                "-n",
                "monitoring",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _observability_available = result.returncode == 0
    except Exception:
        _observability_available = False

    if _observability_available:
        logger.info("Observability stack detected in monitoring namespace")
    else:
        logger.debug("Observability stack not available — queries will be skipped")

    return _observability_available


def query_logs(
    namespace: str,
    start: float,
    end: float,
    query: str = "*",
    limit: int = 1000,
) -> list[dict]:
    """Query VictoriaLogs for log entries via kubectl exec.

    Args:
        namespace: Kubernetes namespace to filter logs for.
        start: Start time as Unix epoch seconds.
        end: End time as Unix epoch seconds.
        query: LogsQL query string (default: all logs).
        limit: Maximum number of log entries to return.

    Returns:
        List of parsed log entry dicts. Empty list on failure.
    """
    if not is_observability_available():
        return []

    # Build the logsql query — scope to the namespace
    full_query = f'kubernetes_namespace_name:"{namespace}"'
    if query != "*":
        full_query = f"{full_query} AND ({query})"

    params = urlencode(
        {
            "query": full_query,
            "start": str(int(start)),
            "end": str(int(end)),
            "limit": str(limit),
        }
    )
    url = f"http://localhost:9428/select/logsql/query?{params}"

    try:
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "-n",
                "monitoring",
                "deploy/victoria-logs-server",
                "--",
                "curl",
                "-s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"VictoriaLogs query failed: {result.stderr}")
            return []

        # VictoriaLogs returns newline-delimited JSON
        entries: list[dict] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        logger.info(f"VictoriaLogs returned {len(entries)} entries for {namespace}")
        return entries

    except Exception as e:
        logger.warning(f"VictoriaLogs query error: {e}")
        return []


def query_metrics_range(
    promql: str,
    start: float,
    end: float,
    step: str = "30s",
) -> dict:
    """Query VictoriaMetrics for a time-series range via kubectl exec.

    Args:
        promql: PromQL query string.
        start: Start time as Unix epoch seconds.
        end: End time as Unix epoch seconds.
        step: Query resolution step (default: 30s).

    Returns:
        Parsed Prometheus query_range response dict. Empty dict on failure.
    """
    if not is_observability_available():
        return {}

    params = urlencode(
        {
            "query": promql,
            "start": str(int(start)),
            "end": str(int(end)),
            "step": step,
        }
    )
    url = f"http://localhost:8428/api/v1/query_range?{params}"

    try:
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                "-n",
                "monitoring",
                "deploy/victoria-metrics-server",
                "--",
                "curl",
                "-s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"VictoriaMetrics query failed: {result.stderr}")
            return {}

        data = json.loads(result.stdout)
        return data

    except Exception as e:
        logger.warning(f"VictoriaMetrics query error: {e}")
        return {}


def collect_test_logs(
    namespace: str,
    start_time: float,
    end_time: float,
) -> list[dict]:
    """Collect all logs from a test namespace within the given time window.

    Convenience wrapper around :func:`query_logs` that fetches all log entries
    for the namespace.

    Args:
        namespace: Kubernetes namespace.
        start_time: Start time as Unix epoch seconds.
        end_time: End time as Unix epoch seconds.

    Returns:
        List of structured log entry dicts.
    """
    return query_logs(
        namespace=namespace,
        query="*",
        start=start_time,
        end=end_time,
        limit=5000,
    )


def collect_test_metrics(
    namespace: str,
    start_time: float,
    end_time: float,
) -> dict:
    """Collect resource metrics for a test namespace over the given time window.

    Queries VictoriaMetrics for memory, CPU, restarts, and network time-series.

    Args:
        namespace: Kubernetes namespace.
        start_time: Start time as Unix epoch seconds.
        end_time: End time as Unix epoch seconds.

    Returns:
        Dict mapping metric name to Prometheus range query results.
    """
    if not is_observability_available():
        return {}

    # Determine appropriate step based on time window
    duration = end_time - start_time
    if duration > 3600:
        step = "60s"
    elif duration > 600:
        step = "30s"
    else:
        step = "15s"

    queries = {
        "memory_bytes": (
            f'sum by (pod) (container_memory_working_set_bytes{{namespace="{namespace}"}})'
        ),
        "cpu_seconds": (
            f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[1m]))'
        ),
        "restarts": (
            f'sum by (pod) (kube_pod_container_status_restarts_total{{namespace="{namespace}"}})'
        ),
        "network_rx_bytes": (
            f'sum by (pod) (rate(container_network_receive_bytes_total{{namespace="{namespace}"}}[1m]))'
        ),
        "network_tx_bytes": (
            f'sum by (pod) (rate(container_network_transmit_bytes_total{{namespace="{namespace}"}}[1m]))'
        ),
    }

    results: dict[str, dict] = {}
    for name, promql in queries.items():
        data = query_metrics_range(
            promql=promql,
            start=start_time,
            end=end_time,
            step=step,
        )
        if data:
            results[name] = data

    return results


def generate_grafana_links(
    namespace: str,
    start_time: float,
    end_time: float,
) -> dict[str, str]:
    """Generate Grafana dashboard URLs with pre-filled namespace and time filters.

    Args:
        namespace: Kubernetes namespace.
        start_time: Start time as Unix epoch seconds.
        end_time: End time as Unix epoch seconds.

    Returns:
        Dict with keys ``logs`` and ``pod_resources`` pointing to Grafana URLs.
    """
    # Convert to milliseconds for Grafana
    from_ms = int(start_time * 1000)
    to_ms = int(end_time * 1000)

    # Grafana Explore URL for VictoriaLogs
    logs_query = quote(f'kubernetes_namespace_name:"{namespace}"')
    logs_url = (
        f"{GRAFANA_BASE_URL}/explore?"
        f"left=%5B%22{from_ms}%22,%22{to_ms}%22,"
        f"%22VictoriaLogs%22,"
        f"%7B%22expr%22:%22{logs_query}%22%7D%5D"
    )

    # Pod resources dashboard (assumes a standard k8s dashboard exists)
    resources_url = (
        f"{GRAFANA_BASE_URL}/d/k8s-pod-resources/pod-resources?"
        f"var-namespace={quote(namespace)}"
        f"&from={from_ms}&to={to_ms}"
    )

    return {
        "logs": logs_url,
        "pod_resources": resources_url,
    }
