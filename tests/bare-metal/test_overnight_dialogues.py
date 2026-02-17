"""Overnight dialogue tests for bare-metal styrened instances.

Exercises multi-turn conversation flows between physical devices using
the dialogue framework. Requires at least 2 devices with daemons running
and identity_hash configured.
"""

from __future__ import annotations

import json
import logging
import random
import sys
import time
from pathlib import Path

import pytest

from tests.dialogues.models import load_dialogue_scripts, load_multi_node_dialogue_scripts
from tests.dialogues.primitives import (
    ensure_daemons_healthy,
    execute_dialogue,
    execute_multi_node_dialogue,
    resolve_lxmf_hashes,
    resolve_multi_node_lxmf_hashes,
)
from tests.dialogues.results import OvernightSummary
from tests.harness.ssh import SSHHarness

# Import metrics collector (bare-metal dir is on sys.path via conftest)
sys.path.insert(0, str(Path(__file__).parent))
from metrics import BareMetalMetricsCollector  # noqa: E402

logger = logging.getLogger(__name__)

# Scripts directories
SCRIPTS_DIR = Path(__file__).parent.parent / "dialogues" / "scripts"
MULTI_NODE_SCRIPTS_DIR = SCRIPTS_DIR / "multi_node"

# Output directory for test results
RESULTS_DIR = Path("test-results/bare-metal/overnight-dialogues")


@pytest.fixture(scope="module")
def dialogue_pair(harness: SSHHarness):
    """Fixture providing a pair of devices for dialogue testing.

    Selects the first two devices with identity_hash configured.
    Ensures daemons are running on both.

    Returns:
        Tuple of (node_a, node_b, identity_a, identity_b).
    """
    devices_with_id = [
        name for name, config in harness.registry.items()
        if config.identity_hash
    ]
    if len(devices_with_id) < 2:
        pytest.skip("Need at least 2 devices with identity_hash for dialogue tests")

    node_a = devices_with_id[0]
    node_b = devices_with_id[1]

    # Ensure daemons are running
    for node in [node_a, node_b]:
        if not harness.is_daemon_running(node):
            result = harness.start_daemon(node)
            assert result.success, f"Failed to start daemon on {node}: {result.stderr}"
            assert harness.wait_for_daemon(node, timeout=30), f"{node} daemon not responsive"

    identity_a = harness.registry[node_a].identity_hash
    identity_b = harness.registry[node_b].identity_hash

    return node_a, node_b, identity_a, identity_b


@pytest.fixture(scope="module")
def lxmf_hashes(harness: SSHHarness, dialogue_pair):
    """Fixture resolving LXMF destination hashes for the dialogue pair.

    Returns:
        Tuple of (b_hash_as_seen_by_a, a_hash_as_seen_by_b).
    """
    node_a, node_b, _, _ = dialogue_pair
    return resolve_lxmf_hashes(harness, node_a, node_b, wait=20)


@pytest.fixture(scope="module")
def dialogue_trio(harness: SSHHarness):
    """Fixture providing three devices for multi-node dialogue testing.

    Returns:
        Tuple of (role_to_node, node_identities) dicts.
    """
    devices_with_id = [
        name for name, config in harness.registry.items()
        if config.identity_hash
    ]
    if len(devices_with_id) < 3:
        pytest.skip("Need at least 3 devices with identity_hash for multi-node dialogue tests")

    nodes = devices_with_id[:3]
    roles = ["A", "B", "C"]

    # Ensure daemons are running
    for node in nodes:
        if not harness.is_daemon_running(node):
            result = harness.start_daemon(node)
            assert result.success, f"Failed to start daemon on {node}: {result.stderr}"
            assert harness.wait_for_daemon(node, timeout=30), f"{node} daemon not responsive"

    role_to_node = dict(zip(roles, nodes))
    node_identities = {
        name: harness.registry[name].identity_hash
        for name in nodes
    }

    return role_to_node, node_identities


@pytest.fixture(scope="module")
def multi_node_lxmf_hashes(harness: SSHHarness, dialogue_trio):
    """Fixture resolving LXMF hashes for all 3-node directional pairs."""
    role_to_node, _ = dialogue_trio
    nodes = list(role_to_node.values())
    return resolve_multi_node_lxmf_hashes(harness, nodes, wait=20)


@pytest.mark.smoke
@pytest.mark.dialogue
class TestDialogueSmoke:
    """Quick dialogue validation -- runs each script once."""

    def test_dialogue_smoke(self, harness, dialogue_pair, lxmf_hashes):
        """Run each dialogue script once and assert >= 50% turn success rate.

        This is a quick validation (~5-10 min) before committing to an
        overnight run.
        """
        node_a, node_b, identity_a, identity_b = dialogue_pair
        b_lxmf, a_lxmf = lxmf_hashes

        scripts = load_dialogue_scripts(SCRIPTS_DIR)
        assert len(scripts) > 0, f"No dialogue scripts found in {SCRIPTS_DIR}"

        for script in scripts:
            result = execute_dialogue(
                harness=harness,
                script=script,
                node_a=node_a,
                node_b=node_b,
                identity_a=identity_a,
                identity_b=identity_b,
                lxmf_a=a_lxmf,
                lxmf_b=b_lxmf,
            )

            total = len(result.turns)
            success_rate = result.turns_succeeded / total if total > 0 else 0.0

            logger.info(
                "Smoke: %s -- %d/%d turns (%.0f%%)",
                script.name, result.turns_succeeded, total, success_rate * 100,
            )

            assert success_rate >= 0.5, (
                f"Script '{script.name}' success rate {success_rate:.0%} < 50%: "
                f"{result.turns_succeeded}/{total} turns passed"
            )


@pytest.mark.slow_extended
@pytest.mark.dialogue
class TestOvernightDialogues:
    """8-hour overnight dialogue test with metrics collection."""

    DURATION_HOURS = 8
    MIN_SUCCESS_RATE = 0.90
    MAX_MEMORY_GROWTH_KB_PER_HOUR = 10240  # 10 MB/hour

    def test_overnight_2node_dialogues(self, harness, dialogue_pair, lxmf_hashes):
        """Loop through all dialogue scripts for 8 hours.

        Success criteria:
        - >= 90% turn success rate overall
        - Memory growth < 10 MB/hour per device
        """
        node_a, node_b, identity_a, identity_b = dialogue_pair
        b_lxmf, a_lxmf = lxmf_hashes

        scripts = load_dialogue_scripts(SCRIPTS_DIR)
        assert len(scripts) > 0, f"No dialogue scripts found in {SCRIPTS_DIR}"

        # Setup metrics collection
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        collector = BareMetalMetricsCollector(
            harness=harness,
            output_dir=RESULTS_DIR / "metrics",
            devices=[node_a, node_b],
            device_count_interval=10,
        )
        collector.start(interval=60)

        # Run dialogues in a loop
        duration_seconds = self.DURATION_HOURS * 3600
        start_time = time.time()
        all_results = []
        cycle = 0

        try:
            while time.time() - start_time < duration_seconds:
                cycle += 1
                cycle_id = f"c{cycle:04d}"
                logger.info("=== Dialogue cycle %d (elapsed: %.0fm) ===",
                            cycle, (time.time() - start_time) / 60)

                # Health check with recovery
                health = ensure_daemons_healthy(harness, [node_a, node_b])
                if health.restarted:
                    logger.info("Daemons restarted on %s, re-resolving LXMF hashes",
                                health.restarted)
                    b_lxmf, a_lxmf = resolve_lxmf_hashes(
                        harness, node_a, node_b, wait=20,
                    )

                # Randomize script order each cycle
                cycle_scripts = list(scripts)
                random.shuffle(cycle_scripts)

                for script in cycle_scripts:
                    if time.time() - start_time >= duration_seconds:
                        break

                    result = execute_dialogue(
                        harness=harness,
                        script=script,
                        node_a=node_a,
                        node_b=node_b,
                        identity_a=identity_a,
                        identity_b=identity_b,
                        lxmf_a=a_lxmf,
                        lxmf_b=b_lxmf,
                        cycle_id=cycle_id,
                        cycle_index=cycle,
                    )
                    all_results.append(result)

                    logger.info(
                        "Cycle %d: %s -- %d/%d turns",
                        cycle, script.name,
                        result.turns_succeeded, len(result.turns),
                    )

                # Brief pause between cycles
                time.sleep(10)

        finally:
            # Stop metrics and get summary
            metrics_summary = collector.stop()

            # Build overnight summary
            elapsed = time.time() - start_time
            summary = OvernightSummary.from_dialogue_results(all_results, elapsed)

            # Write summary
            summary_file = RESULTS_DIR / "overnight_summary.json"
            with open(summary_file, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)

            logger.info(
                "Overnight test complete: %d dialogues, %d/%d turns (%.1f%%), %.1f hours",
                summary.total_dialogues,
                summary.turns_succeeded,
                summary.total_turns,
                (summary.turns_succeeded / summary.total_turns * 100)
                if summary.total_turns > 0 else 0,
                elapsed / 3600,
            )

        # Assertions
        if summary.total_turns > 0:
            overall_rate = summary.turns_succeeded / summary.total_turns
            assert overall_rate >= self.MIN_SUCCESS_RATE, (
                f"Overall success rate {overall_rate:.1%} < {self.MIN_SUCCESS_RATE:.0%}: "
                f"{summary.turns_succeeded}/{summary.total_turns} turns"
            )

        # Memory growth assertion
        for device, stats in metrics_summary.devices.items():
            growth_rate = stats.get("rss_growth_rate_kb_per_hour", 0)
            assert growth_rate < self.MAX_MEMORY_GROWTH_KB_PER_HOUR, (
                f"{device} memory growth {growth_rate:.0f} KB/hour "
                f"> {self.MAX_MEMORY_GROWTH_KB_PER_HOUR} KB/hour limit"
            )


@pytest.mark.slow_extended
@pytest.mark.dialogue
class TestOvernightMultiNodeDialogues:
    """8-hour overnight multi-node dialogue test across 3 devices."""

    DURATION_HOURS = 8
    MIN_SUCCESS_RATE = 0.90
    MAX_MEMORY_GROWTH_KB_PER_HOUR = 10240  # 10 MB/hour

    def test_overnight_3node_dialogues(
        self,
        harness,
        dialogue_trio,
        multi_node_lxmf_hashes,
        dialogue_pair,
        lxmf_hashes,
    ):
        """Loop through multi-node + rotated 2-node scripts for 8 hours.

        Uses all 3 nodes: runs multi-node triangle/relay/simultaneous scripts
        plus rotates 2-node scripts across pairs (A-B, A-C, B-C).

        Success criteria:
        - >= 90% turn success rate overall
        - Memory growth < 10 MB/hour per device
        """
        role_to_node, node_identities = dialogue_trio
        mn_lxmf_hashes = multi_node_lxmf_hashes
        all_nodes = list(role_to_node.values())

        # Load scripts
        multi_scripts = load_multi_node_dialogue_scripts(MULTI_NODE_SCRIPTS_DIR)
        two_node_scripts = load_dialogue_scripts(SCRIPTS_DIR)

        if not multi_scripts and not two_node_scripts:
            pytest.skip("No dialogue scripts found")

        # Build 2-node pair configurations for rotation
        pairs = [
            (all_nodes[0], all_nodes[1]),
            (all_nodes[0], all_nodes[2]),
            (all_nodes[1], all_nodes[2]),
        ]

        # Setup metrics collection
        results_dir = RESULTS_DIR / "multi-node"
        results_dir.mkdir(parents=True, exist_ok=True)
        collector = BareMetalMetricsCollector(
            harness=harness,
            output_dir=results_dir / "metrics",
            devices=all_nodes,
            device_count_interval=10,
        )
        collector.start(interval=60)

        duration_seconds = self.DURATION_HOURS * 3600
        start_time = time.time()
        all_results = []
        cycle = 0

        try:
            while time.time() - start_time < duration_seconds:
                cycle += 1
                cycle_id = f"m{cycle:04d}"
                logger.info("=== Multi-node cycle %d (elapsed: %.0fm) ===",
                            cycle, (time.time() - start_time) / 60)

                # Health check with recovery
                health = ensure_daemons_healthy(harness, all_nodes)
                if health.restarted:
                    logger.info(
                        "Daemons restarted on %s, re-resolving LXMF hashes",
                        health.restarted,
                    )
                    mn_lxmf_hashes = resolve_multi_node_lxmf_hashes(
                        harness, all_nodes, wait=20,
                    )

                # Run multi-node scripts (shuffled)
                if multi_scripts:
                    cycle_multi = list(multi_scripts)
                    random.shuffle(cycle_multi)

                    for script in cycle_multi:
                        if time.time() - start_time >= duration_seconds:
                            break

                        result = execute_multi_node_dialogue(
                            harness=harness,
                            script=script,
                            role_to_node=role_to_node,
                            node_identities=node_identities,
                            lxmf_hashes=mn_lxmf_hashes,
                            cycle_id=cycle_id,
                            cycle_index=cycle,
                        )
                        all_results.append(result)

                        logger.info(
                            "Cycle %d: %s -- %d/%d turns",
                            cycle, script.name,
                            result.turns_succeeded, len(result.turns),
                        )

                # Rotate 2-node scripts across pairs
                if two_node_scripts:
                    pair = pairs[cycle % len(pairs)]
                    na, nb = pair
                    id_a = node_identities[na]
                    id_b = node_identities[nb]
                    b_lxmf = mn_lxmf_hashes.get((na, nb), "")
                    a_lxmf = mn_lxmf_hashes.get((nb, na), "")

                    cycle_2node = list(two_node_scripts)
                    random.shuffle(cycle_2node)

                    for script in cycle_2node:
                        if time.time() - start_time >= duration_seconds:
                            break

                        result = execute_dialogue(
                            harness=harness,
                            script=script,
                            node_a=na,
                            node_b=nb,
                            identity_a=id_a,
                            identity_b=id_b,
                            lxmf_a=a_lxmf,
                            lxmf_b=b_lxmf,
                            cycle_id=cycle_id,
                            cycle_index=cycle,
                        )
                        all_results.append(result)

                        logger.info(
                            "Cycle %d (pair %s-%s): %s -- %d/%d turns",
                            cycle, na, nb, script.name,
                            result.turns_succeeded, len(result.turns),
                        )

                time.sleep(10)

        finally:
            metrics_summary = collector.stop()

            elapsed = time.time() - start_time
            summary = OvernightSummary.from_dialogue_results(all_results, elapsed)

            summary_file = results_dir / "overnight_summary.json"
            with open(summary_file, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)

            logger.info(
                "Multi-node overnight complete: %d dialogues, %d/%d turns (%.1f%%), %.1f hours",
                summary.total_dialogues,
                summary.turns_succeeded,
                summary.total_turns,
                (summary.turns_succeeded / summary.total_turns * 100)
                if summary.total_turns > 0 else 0,
                elapsed / 3600,
            )

        # Assertions
        if summary.total_turns > 0:
            overall_rate = summary.turns_succeeded / summary.total_turns
            assert overall_rate >= self.MIN_SUCCESS_RATE, (
                f"Overall success rate {overall_rate:.1%} < {self.MIN_SUCCESS_RATE:.0%}: "
                f"{summary.turns_succeeded}/{summary.total_turns} turns"
            )

        for device, stats in metrics_summary.devices.items():
            growth_rate = stats.get("rss_growth_rate_kb_per_hour", 0)
            assert growth_rate < self.MAX_MEMORY_GROWTH_KB_PER_HOUR, (
                f"{device} memory growth {growth_rate:.0f} KB/hour "
                f"> {self.MAX_MEMORY_GROWTH_KB_PER_HOUR} KB/hour limit"
            )
