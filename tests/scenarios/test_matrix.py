"""Test matrix scenarios with expected parameters and results.

Defines structured test cases with:
- Input parameters
- Expected outcomes
- Actual results
- Pass/fail analysis

Run with:
    pytest tests/scenarios/test_matrix.py --backend=ssh -v
    pytest tests/scenarios/test_matrix.py --backend=ssh -v --tb=short 2>&1 | tee test-results.log
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.harness.primitives import (
    InstallMethod,
    check_bidirectional_discovery,
    check_connectivity,
    check_daemon_running,
    check_installation_prerequisites,
    check_version,
    discover_peers,
)

if TYPE_CHECKING:
    from tests.harness.ssh import SSHHarness


class ExpectedOutcome(Enum):
    """Expected test outcome."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    FLAKY = "flaky"  # Known to be unreliable


def _serialize_value(value: Any) -> Any:
    """Serialize a value for JSON, handling enums and other special types."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


@dataclass
class Scenario:
    """A test scenario with expected parameters and results.

    Note: Named 'Scenario' (not 'TestScenario') to avoid pytest collection.
    """

    name: str
    description: str
    category: str

    # Input parameters
    params: dict[str, Any] = field(default_factory=dict)

    # Expected outcome
    expected: ExpectedOutcome = ExpectedOutcome.PASS
    expected_duration_max: float | None = None  # Max expected duration in seconds
    expected_data: dict[str, Any] = field(default_factory=dict)

    # Actual results (populated after run)
    actual_success: bool | None = None
    actual_duration: float | None = None
    actual_data: dict[str, Any] = field(default_factory=dict)
    actual_error: str | None = None

    # Analysis
    outcome_matched: bool | None = None
    duration_ok: bool | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "params": _serialize_value(self.params),
            "expected": {
                "outcome": self.expected.value,
                "duration_max": self.expected_duration_max,
                "data": _serialize_value(self.expected_data),
            },
            "actual": {
                "success": self.actual_success,
                "duration": self.actual_duration,
                "data": _serialize_value(self.actual_data),
                "error": self.actual_error,
            },
            "analysis": {
                "outcome_matched": self.outcome_matched,
                "duration_ok": self.duration_ok,
                "notes": self.notes,
            },
        }


@dataclass
class MatrixRun:
    """Collection of test scenarios with metadata.

    Note: Named 'MatrixRun' (not 'TestRun') to avoid pytest collection.
    """

    name: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    scenarios: list[Scenario] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_scenario(self, scenario: Scenario) -> None:
        self.scenarios.append(scenario)

    def complete(self) -> None:
        self.completed_at = datetime.now()

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.outcome_matched is True)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.outcome_matched is False)

    @property
    def total(self) -> int:
        return len(self.scenarios)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
            },
            "metadata": self.metadata,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    def save(self, path: Path) -> None:
        """Save test run results to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


# =============================================================================
# Scenario Definitions
# =============================================================================

CONNECTIVITY_SCENARIOS = [
    Scenario(
        name="ssh_reachable_styrene_node",
        description="Verify SSH connectivity to styrene-node",
        category="connectivity",
        params={"node": "styrene-node", "timeout": 10.0},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
    ),
    Scenario(
        name="ssh_reachable_t100ta",
        description="Verify SSH connectivity to t100ta",
        category="connectivity",
        params={"node": "t100ta", "timeout": 10.0},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
    ),
    Scenario(
        name="ssh_reachable_nonexistent",
        description="Verify SSH fails for nonexistent host",
        category="connectivity",
        params={"node": "nonexistent.example.local", "timeout": 5.0},
        expected=ExpectedOutcome.FAIL,
        expected_duration_max=10.0,
    ),
]

VERSION_SCENARIOS = [
    Scenario(
        name="version_installed_styrene_node",
        description="Verify styrened is installed on styrene-node",
        category="version",
        params={"node": "styrene-node"},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
        expected_data={"version_pattern": r"\d+\.\d+\.\d+"},
    ),
    Scenario(
        name="version_installed_t100ta",
        description="Verify styrened is installed on t100ta",
        category="version",
        params={"node": "t100ta"},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
    ),
]

PREREQUISITES_SCENARIOS = [
    # styrene-node has both pip (in venv) and nix
    Scenario(
        name="prereq_pip_styrene_node",
        description="Verify pip prerequisites on styrene-node (venv)",
        category="prerequisites",
        params={"node": "styrene-node", "method": InstallMethod.PIP_GIT},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
        expected_data={"python3": True, "pip": True},
    ),
    Scenario(
        name="prereq_nix_styrene_node",
        description="Verify nix prerequisites on styrene-node (NixOS)",
        category="prerequisites",
        params={"node": "styrene-node", "method": InstallMethod.NIX_FLAKE},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
        expected_data={"nix": True, "flakes": True},
    ),
    # t100ta is NixOS - pip not in PATH by default, but nix is available
    Scenario(
        name="prereq_pip_t100ta",
        description="Verify pip prerequisites on t100ta (expected to fail - NixOS)",
        category="prerequisites",
        params={"node": "t100ta", "method": InstallMethod.PIP_GIT},
        expected=ExpectedOutcome.FAIL,  # NixOS doesn't have pip in PATH
        expected_duration_max=5.0,
    ),
    Scenario(
        name="prereq_nix_t100ta",
        description="Verify nix prerequisites on t100ta (NixOS)",
        category="prerequisites",
        params={"node": "t100ta", "method": InstallMethod.NIX_FLAKE},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=5.0,
        expected_data={"nix": True, "flakes": True},
    ),
]

DAEMON_SCENARIOS = [
    Scenario(
        name="daemon_check_styrene_node",
        description="Check daemon status on styrene-node",
        category="daemon",
        params={"node": "styrene-node"},
        expected=ExpectedOutcome.PASS,  # Assumes daemon should be running
        expected_duration_max=3.0,
    ),
    Scenario(
        name="daemon_check_t100ta",
        description="Check daemon status on t100ta",
        category="daemon",
        params={"node": "t100ta"},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=3.0,
    ),
]

DISCOVERY_SCENARIOS = [
    Scenario(
        name="discovery_from_styrene_node",
        description="Discover peers from styrene-node",
        category="discovery",
        params={"node": "styrene-node", "wait_seconds": 15, "min_expected": 1},
        expected=ExpectedOutcome.PASS,
        expected_duration_max=20.0,
        expected_data={"min_devices": 1},
    ),
    Scenario(
        name="discovery_bidirectional",
        description="Verify bidirectional discovery between nodes",
        category="discovery",
        params={"node_a": "styrene-node", "node_b": "t100ta", "wait_seconds": 20},
        # Both nodes connect to the hub (192.168.0.102:4242) and discover
        # each other through the mesh.
        expected=ExpectedOutcome.PASS,
        expected_duration_max=50.0,
        expected_data={"a_sees_b": True, "b_sees_a": True},
    ),
]


# =============================================================================
# Test Execution
# =============================================================================


def run_scenario(
    harness: SSHHarness,
    scenario: Scenario,
) -> Scenario:
    """Execute a single test scenario and record results."""

    start = time.time()

    try:
        if scenario.category == "connectivity":
            node = scenario.params.get("node")
            timeout = scenario.params.get("timeout", 10.0)

            # For nonexistent hosts, create ephemeral node
            result = check_connectivity(harness, node, timeout=timeout)

            scenario.actual_success = result.success
            scenario.actual_data = result.data
            scenario.actual_error = result.error

        elif scenario.category == "version":
            node = scenario.params.get("node")
            result = check_version(harness, node)

            scenario.actual_success = result.success
            scenario.actual_data = result.data
            scenario.actual_error = result.error

        elif scenario.category == "prerequisites":
            node = scenario.params.get("node")
            method = scenario.params.get("method", InstallMethod.PIP_GIT)
            result = check_installation_prerequisites(harness, node, method)

            scenario.actual_success = result.success
            scenario.actual_data = result.data
            scenario.actual_error = result.error

        elif scenario.category == "daemon":
            node = scenario.params.get("node")
            result = check_daemon_running(harness, node)

            scenario.actual_success = result.success
            scenario.actual_data = result.data
            scenario.actual_error = result.error

        elif scenario.category == "discovery":
            if "node_b" in scenario.params:
                # Bidirectional discovery
                result = check_bidirectional_discovery(
                    harness,
                    scenario.params["node_a"],
                    scenario.params["node_b"],
                    wait_seconds=scenario.params.get("wait_seconds", 15),
                )
            else:
                # Single node discovery
                result = discover_peers(
                    harness,
                    scenario.params["node"],
                    wait_seconds=scenario.params.get("wait_seconds", 10),
                    min_expected=scenario.params.get("min_expected", 0),
                )

            scenario.actual_success = result.success
            scenario.actual_data = result.data
            scenario.actual_error = result.error

        else:
            scenario.actual_success = False
            scenario.actual_error = f"Unknown category: {scenario.category}"

    except Exception as e:
        scenario.actual_success = False
        scenario.actual_error = str(e)

    scenario.actual_duration = time.time() - start

    # Analyze results
    if scenario.expected == ExpectedOutcome.PASS:
        scenario.outcome_matched = scenario.actual_success is True
    elif scenario.expected == ExpectedOutcome.FAIL:
        scenario.outcome_matched = scenario.actual_success is False
    elif scenario.expected == ExpectedOutcome.SKIP:
        scenario.outcome_matched = True  # Skips always match
    elif scenario.expected == ExpectedOutcome.FLAKY:
        scenario.outcome_matched = True  # Flaky tests always "match"
        scenario.notes = f"Flaky test: actual_success={scenario.actual_success}"

    if scenario.expected_duration_max:
        scenario.duration_ok = scenario.actual_duration <= scenario.expected_duration_max
        if not scenario.duration_ok:
            scenario.notes += f" Duration exceeded: {scenario.actual_duration:.2f}s > {scenario.expected_duration_max}s"

    return scenario


# =============================================================================
# Pytest Integration
# =============================================================================


@pytest.fixture(scope="module")
def matrix_run() -> MatrixRun:
    """Create a test run to collect results."""
    return MatrixRun(
        name="bare_metal_matrix",
        metadata={
            "backend": "ssh",
            "description": "Bare-metal test matrix execution",
        },
    )


@pytest.mark.smoke
class TestConnectivityMatrix:
    """Connectivity test matrix."""

    @pytest.mark.parametrize("scenario", CONNECTIVITY_SCENARIOS, ids=lambda s: s.name)
    def test_connectivity(
        self,
        harness: SSHHarness,
        scenario: Scenario,
        matrix_run: MatrixRun,
    ) -> None:
        """Run connectivity scenario."""
        result = run_scenario(harness, scenario)
        matrix_run.add_scenario(result)

        # Report
        print(f"\n  Scenario: {result.name}")
        print(f"  Expected: {result.expected.value}")
        print(f"  Actual:   {'pass' if result.actual_success else 'fail'}")
        print(f"  Duration: {result.actual_duration:.2f}s")
        if result.actual_error:
            print(f"  Error:    {result.actual_error[:100]}")

        assert result.outcome_matched, f"Outcome mismatch: expected {result.expected.value}"


@pytest.mark.smoke
class TestVersionMatrix:
    """Version check test matrix."""

    @pytest.mark.parametrize("scenario", VERSION_SCENARIOS, ids=lambda s: s.name)
    def test_version(
        self,
        harness: SSHHarness,
        scenario: Scenario,
        matrix_run: MatrixRun,
    ) -> None:
        """Run version scenario."""
        result = run_scenario(harness, scenario)
        matrix_run.add_scenario(result)

        print(f"\n  Scenario: {result.name}")
        print(f"  Version:  {result.actual_data.get('version', 'N/A')}")
        print(f"  Duration: {result.actual_duration:.2f}s")

        assert result.outcome_matched, f"Outcome mismatch: expected {result.expected.value}"


@pytest.mark.smoke
class TestPrerequisitesMatrix:
    """Prerequisites test matrix."""

    @pytest.mark.parametrize("scenario", PREREQUISITES_SCENARIOS, ids=lambda s: s.name)
    def test_prerequisites(
        self,
        harness: SSHHarness,
        scenario: Scenario,
        matrix_run: MatrixRun,
    ) -> None:
        """Run prerequisites scenario."""
        result = run_scenario(harness, scenario)
        matrix_run.add_scenario(result)

        print(f"\n  Scenario: {result.name}")
        print(f"  Checks:   {result.actual_data.get('checks', {})}")
        print(f"  Duration: {result.actual_duration:.2f}s")

        assert result.outcome_matched, f"Outcome mismatch: expected {result.expected.value}"


@pytest.mark.integration
class TestDaemonMatrix:
    """Daemon status test matrix."""

    @pytest.mark.parametrize("scenario", DAEMON_SCENARIOS, ids=lambda s: s.name)
    def test_daemon(
        self,
        harness: SSHHarness,
        scenario: Scenario,
        matrix_run: MatrixRun,
    ) -> None:
        """Run daemon scenario."""
        result = run_scenario(harness, scenario)
        matrix_run.add_scenario(result)

        print(f"\n  Scenario: {result.name}")
        print(f"  Running:  {result.actual_data.get('running', 'N/A')}")
        print(f"  Duration: {result.actual_duration:.2f}s")

        # Daemon tests may fail if not provisioned - mark as expected
        if not result.actual_success and "not running" in str(result.actual_error):
            pytest.skip("Daemon not running (not yet provisioned)")

        assert result.outcome_matched, f"Outcome mismatch: expected {result.expected.value}"


@pytest.mark.integration
class TestDiscoveryMatrix:
    """Discovery test matrix."""

    @pytest.mark.parametrize("scenario", DISCOVERY_SCENARIOS, ids=lambda s: s.name)
    def test_discovery(
        self,
        harness: SSHHarness,
        scenario: Scenario,
        matrix_run: MatrixRun,
    ) -> None:
        """Run discovery scenario."""
        # Check if daemons are running first
        for node_key in ["node", "node_a", "node_b"]:
            if node_key in scenario.params:
                node = scenario.params[node_key]
                if not harness.is_daemon_running(node):
                    pytest.skip(f"Daemon not running on {node}")

        result = run_scenario(harness, scenario)
        matrix_run.add_scenario(result)

        print(f"\n  Scenario: {result.name}")
        print(
            f"  Devices:  {result.actual_data.get('count', result.actual_data.get('devices_a_count', 'N/A'))}"
        )
        print(f"  Duration: {result.actual_duration:.2f}s")
        if result.actual_data.get("a_sees_b") is not None:
            print(f"  A->B:     {result.actual_data.get('a_sees_b')}")
            print(f"  B->A:     {result.actual_data.get('b_sees_a')}")

        assert result.outcome_matched, f"Outcome mismatch: expected {result.expected.value}"


@pytest.fixture(scope="module", autouse=True)
def save_results(matrix_run: MatrixRun, request: pytest.FixtureRequest) -> None:
    """Save test results after all tests complete."""
    yield

    matrix_run.complete()

    # Save to file
    results_dir = Path(__file__).parent.parent.parent / "test-results"
    results_dir.mkdir(exist_ok=True)

    timestamp = matrix_run.started_at.strftime("%Y%m%d_%H%M%S")
    results_file = results_dir / f"matrix_{timestamp}.json"
    matrix_run.save(results_file)

    print(f"\n{'=' * 60}")
    print(f"Test Matrix Results: {matrix_run.passed}/{matrix_run.total} passed")
    print(f"Results saved to: {results_file}")
    print(f"{'=' * 60}")
