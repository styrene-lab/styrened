"""IPC-native dialogue tests over 3-node multi-hop Docker mesh.

Runs 2-node dialogue scripts between edge nodes A and C, which must relay
through transport node B. Uses the existing discovered_multihop fixture.
"""

from pathlib import Path

import pytest

from styrened.ipc.client import ControlClient
from tests.dialogues.models import load_dialogue_scripts
from tests.dialogues.primitives_ipc import execute_dialogue_ipc

pytestmark = [pytest.mark.multihop, pytest.mark.asyncio(loop_scope="session")]

SCRIPTS_DIR = Path(__file__).parent.parent / "dialogues" / "scripts"


def _load_2node_scripts():
    """Load 2-node dialogue scripts (exclude multi-node)."""
    return [s for s in load_dialogue_scripts(SCRIPTS_DIR) if s.turns]


class TestMultihopDialogueSmoke:
    """Smoke test: run each dialogue between A<->C through transport B."""

    @pytest.fixture(scope="class")
    def scripts(self):
        return _load_2node_scripts()

    async def test_scripts_discovered(self, scripts):
        """At least one dialogue script exists."""
        assert len(scripts) > 0, f"No dialogue scripts found in {SCRIPTS_DIR}"

    async def test_each_script_passes_smoke(
        self,
        scripts,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Each script achieves >= 50% turn success rate over multi-hop."""
        a_lxmf = discovered_multihop["a_lxmf"]
        c_lxmf = discovered_multihop["c_lxmf"]

        for script in scripts:
            # A is "node A", C is "node B" in dialogue terms (edge-to-edge)
            result = await execute_dialogue_ipc(
                script=script,
                client_a=multihop_node_a,
                client_b=multihop_node_c,
                lxmf_a=a_lxmf,
                lxmf_b=c_lxmf,
                cycle_id="multihop-smoke",
            )

            total = len(result.turns)
            success_rate = result.turns_succeeded / total if total > 0 else 0.0
            assert success_rate >= 0.5, (
                f"Multihop dialogue '{script.name}' smoke: "
                f"{result.turns_succeeded}/{total} turns passed "
                f"({success_rate:.0%}), need >= 50%"
            )


@pytest.mark.slow
class TestMultihopDialogueExtended:
    """Extended test: 3 cycles per script over multi-hop."""

    CYCLES = 3

    @pytest.fixture(scope="class")
    def scripts(self):
        return _load_2node_scripts()

    async def test_each_script_passes_extended(
        self,
        scripts,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Each script achieves >= 90% turn success rate over 3 cycles."""
        a_lxmf = discovered_multihop["a_lxmf"]
        c_lxmf = discovered_multihop["c_lxmf"]

        for script in scripts:
            total_turns = 0
            total_succeeded = 0

            for cycle in range(self.CYCLES):
                result = await execute_dialogue_ipc(
                    script=script,
                    client_a=multihop_node_a,
                    client_b=multihop_node_c,
                    lxmf_a=a_lxmf,
                    lxmf_b=c_lxmf,
                    cycle_id=f"multihop-ext-{cycle:04d}",
                    cycle_index=cycle,
                )
                total_turns += len(result.turns)
                total_succeeded += result.turns_succeeded

            success_rate = total_succeeded / total_turns if total_turns > 0 else 0.0
            assert success_rate >= 0.9, (
                f"Multihop dialogue '{script.name}' extended: "
                f"{total_succeeded}/{total_turns} turns passed "
                f"({success_rate:.0%}), need >= 90%"
            )
