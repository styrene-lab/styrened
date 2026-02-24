"""Mesh convergence time measurement tests.

Measures wall-clock time from daemon start to full mesh discovery.
Results written to test-results/bare-metal/ for baseline tracking.
"""

from __future__ import annotations

import itertools
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.harness.ssh import SSHHarness

RESULTS_DIR = Path(__file__).parents[2] / "test-results" / "bare-metal"


@pytest.mark.mesh
class TestMeshConvergence:
    """Measure mesh convergence time across the fleet."""

    def test_full_mesh_convergence(self, harness: SSHHarness, all_devices: list[str]) -> None:
        """Measure time for all devices to discover all others.

        Starts daemons on all devices, then polls until each device
        sees all others. Records wall-clock convergence time.
        """
        devices_with_identity = [
            d for d in all_devices if harness.registry[d].identity_hash
        ]
        if len(devices_with_identity) < 2:
            pytest.skip("Need at least 2 devices with identity for convergence test")

        # Stop all daemons first for clean start
        for device in devices_with_identity:
            harness.stop_daemon(device)
            time.sleep(1)

        # Start all daemons and record start time
        start_time = time.time()
        for device in devices_with_identity:
            result = harness.start_daemon(device)
            assert result.success, f"Failed to start daemon on {device}"

        # Wait for all daemons to become responsive
        for device in devices_with_identity:
            responsive = harness.wait_for_daemon(device, timeout=60)
            assert responsive, f"Daemon on {device} not responsive"

        daemon_ready_time = time.time() - start_time

        # Poll for full mesh convergence
        max_wait = 120  # 2 minutes max
        poll_interval = 5
        converged = False
        convergence_log: list[dict[str, Any]] = []

        expected_pairs = list(itertools.combinations(devices_with_identity, 2))

        while time.time() - start_time < max_wait:
            snapshot: dict[str, list[str]] = {}

            for device in devices_with_identity:
                discovered = harness.discover_devices(device, wait_seconds=3)
                discovered_hashes = [
                    d.get("identity_hash", d.get("destination", ""))[:16]
                    for d in discovered
                ]
                snapshot[device] = discovered_hashes

            # Check all pairs
            all_found = True
            for a, b in expected_pairs:
                a_hash = harness.registry[a].identity_hash[:16]
                b_hash = harness.registry[b].identity_hash[:16]
                a_sees_b = any(h.startswith(b_hash) for h in snapshot.get(a, []))
                b_sees_a = any(h.startswith(a_hash) for h in snapshot.get(b, []))
                if not (a_sees_b and b_sees_a):
                    all_found = False
                    break

            elapsed = time.time() - start_time
            convergence_log.append({
                "elapsed_seconds": round(elapsed, 1),
                "snapshot": {k: len(v) for k, v in snapshot.items()},
                "converged": all_found,
            })

            if all_found:
                converged = True
                break

            time.sleep(poll_interval)

        convergence_time = time.time() - start_time

        # Write results
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "devices": devices_with_identity,
            "device_count": len(devices_with_identity),
            "pair_count": len(expected_pairs),
            "daemon_ready_seconds": round(daemon_ready_time, 1),
            "convergence_seconds": round(convergence_time, 1),
            "converged": converged,
            "log": convergence_log,
        }

        results_file = RESULTS_DIR / "convergence.json"
        with open(results_file, "w") as f:
            json.dump(result_data, f, indent=2)

        # Cleanup: stop daemons we started
        for device in devices_with_identity:
            harness.stop_daemon(device)

        assert converged, (
            f"Mesh did not converge after {convergence_time:.0f}s. "
            f"Log: {json.dumps(convergence_log[-3:], indent=2)}"
        )

    def test_pairwise_discovery_latency(self, harness: SSHHarness, all_devices: list[str]) -> None:
        """Measure discovery latency for each device pair.

        Records per-pair discovery times for detailed analysis.
        """
        devices_with_identity = [
            d for d in all_devices if harness.registry[d].identity_hash
        ]
        if len(devices_with_identity) < 2:
            pytest.skip("Need at least 2 devices with identity")

        # Ensure daemons running
        for device in devices_with_identity:
            if not harness.is_daemon_running(device):
                result = harness.start_daemon(device)
                if not result.success:
                    pytest.skip(f"Could not start daemon on {device}")
                harness.wait_for_daemon(device, timeout=30)

        pairs = list(itertools.combinations(devices_with_identity, 2))
        pair_results: list[dict[str, Any]] = []

        for a, b in pairs:
            b_hash = harness.registry[b].identity_hash

            start = time.time()
            discovered = harness.discover_devices(a, wait_seconds=20)
            duration = time.time() - start

            found = any(
                d.get("identity_hash", d.get("destination", "")).startswith(b_hash[:16])
                for d in discovered
            )

            pair_results.append({
                "from": a,
                "to": b,
                "found": found,
                "discovery_seconds": round(duration, 1),
                "total_discovered": len(discovered),
            })

        # Write results
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_DIR / "pairwise-discovery.json", "w") as f:
            json.dump({
                "timestamp": datetime.now(UTC).isoformat(),
                "pairs": pair_results,
            }, f, indent=2)

        # At least some pairs should discover each other
        found_count = sum(1 for p in pair_results if p["found"])
        assert found_count > 0, f"No pairs discovered each other: {pair_results}"
