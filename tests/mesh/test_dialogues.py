"""IPC-native dialogue tests over 2-node Docker mesh.

Runs YAML-driven dialogue scripts between two containerized styrened nodes
using the async IPC dialogue primitives. Uses the existing discovered_mesh
fixture for topology setup.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from styrened.ipc.client import ControlClient
from tests.dialogues.models import load_dialogue_scripts
from tests.dialogues.primitives_ipc import execute_dialogue_ipc

pytestmark = [pytest.mark.mesh, pytest.mark.asyncio(loop_scope="session")]

SCRIPTS_DIR = Path(__file__).parent.parent / "dialogues" / "scripts"


def _load_2node_scripts():
    """Load 2-node dialogue scripts (exclude multi-node)."""
    return [s for s in load_dialogue_scripts(SCRIPTS_DIR) if s.turns]


class TestDialogueSmoke:
    """Smoke test: run each dialogue script once, assert >= 50% turn success."""

    @pytest.fixture(scope="class")
    def scripts(self):
        return _load_2node_scripts()

    async def test_scripts_discovered(self, scripts):
        """At least one dialogue script exists."""
        assert len(scripts) > 0, f"No dialogue scripts found in {SCRIPTS_DIR}"

    async def test_each_script_passes_smoke(
        self,
        scripts,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Each script achieves >= 50% turn success rate."""
        _, _, a_lxmf, b_lxmf = discovered_mesh

        for script in scripts:
            result = await execute_dialogue_ipc(
                script=script,
                client_a=node_a_client,
                client_b=node_b_client,
                lxmf_a=a_lxmf,
                lxmf_b=b_lxmf,
                cycle_id="smoke",
            )

            total = len(result.turns)
            success_rate = result.turns_succeeded / total if total > 0 else 0.0
            assert success_rate >= 0.5, (
                f"Dialogue '{script.name}' smoke: {result.turns_succeeded}/{total} "
                f"turns passed ({success_rate:.0%}), need >= 50%"
            )


@pytest.mark.slow
class TestDialogueExtended:
    """Extended test: 3 cycles per script, assert >= 90% overall success."""

    CYCLES = 3

    @pytest.fixture(scope="class")
    def scripts(self):
        return _load_2node_scripts()

    async def test_each_script_passes_extended(
        self,
        scripts,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Each script achieves >= 90% turn success rate over 3 cycles."""
        _, _, a_lxmf, b_lxmf = discovered_mesh

        for script in scripts:
            total_turns = 0
            total_succeeded = 0

            for cycle in range(self.CYCLES):
                result = await execute_dialogue_ipc(
                    script=script,
                    client_a=node_a_client,
                    client_b=node_b_client,
                    lxmf_a=a_lxmf,
                    lxmf_b=b_lxmf,
                    cycle_id=f"ext-{cycle:04d}",
                    cycle_index=cycle,
                )
                total_turns += len(result.turns)
                total_succeeded += result.turns_succeeded

            success_rate = total_succeeded / total_turns if total_turns > 0 else 0.0
            assert success_rate >= 0.9, (
                f"Dialogue '{script.name}' extended: {total_succeeded}/{total_turns} "
                f"turns passed ({success_rate:.0%}), need >= 90%"
            )
