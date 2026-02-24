"""Log capture fixture for bare-metal test failure diagnosis."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.harness.ssh import SSHHarness


def _results_dir() -> Path:
    """Get or create test results directory."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    base = Path(__file__).parents[2] / "test-results" / "bare-metal" / timestamp
    return base


# Module-level results path (shared across session)
_session_results_dir: Path | None = None


def get_session_results_dir() -> Path:
    """Get the session-level results directory (created once per session)."""
    global _session_results_dir
    if _session_results_dir is None:
        _session_results_dir = _results_dir()
    return _session_results_dir


@pytest.fixture(autouse=True)
def capture_logs_on_failure(request: pytest.FixtureRequest, harness: SSHHarness):
    """Capture daemon logs from all devices when a test fails."""
    yield

    # Only capture on failure
    if not hasattr(request.node, "rep_call") or not request.node.rep_call.failed:
        return

    results_dir = get_session_results_dir()
    logs_dir = results_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Capture logs from each device
    captured = {}
    for device_name in harness.registry:
        try:
            result = harness.get_logs(device_name, lines=200)
            log_file = logs_dir / f"{device_name}.log"
            # Append to log file (multiple failures may occur)
            with open(log_file, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Captured for: {request.node.nodeid}\n")
                f.write(f"Time: {datetime.now(UTC).isoformat()}\n")
                f.write(f"{'='*60}\n")
                f.write(result.stdout if result.success else f"Log capture failed: {result.stderr}\n")
            captured[device_name] = result.success
        except Exception:
            captured[device_name] = False

    # Write failure context
    context_file = results_dir / "failures.jsonl"
    with open(context_file, "a") as f:
        json.dump({
            "test": request.node.nodeid,
            "timestamp": datetime.now(UTC).isoformat(),
            "log_capture": captured,
        }, f)
        f.write("\n")
