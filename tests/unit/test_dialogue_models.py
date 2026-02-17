"""Unit tests for dialogue script models.

Tests YAML loading, default values, and TurnDirection enum.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.dialogues.models import (
    DialogueScript,
    DialogueTurn,
    MultiNodeDialogueScript,
    MultiNodeDialogueTurn,
    TurnDirection,
    load_dialogue_scripts,
)


class TestTurnDirection:
    """Tests for TurnDirection enum."""

    def test_a_to_b_value(self):
        """A_TO_B should have value 'a_to_b'."""
        assert TurnDirection.A_TO_B.value == "a_to_b"

    def test_b_to_a_value(self):
        """B_TO_A should have value 'b_to_a'."""
        assert TurnDirection.B_TO_A.value == "b_to_a"

    def test_from_string(self):
        """Should create enum from string value."""
        assert TurnDirection("a_to_b") == TurnDirection.A_TO_B
        assert TurnDirection("b_to_a") == TurnDirection.B_TO_A


class TestDialogueTurn:
    """Tests for DialogueTurn dataclass."""

    def test_default_timeouts(self):
        """Default timeouts should be delivery=120, verification=60."""
        turn = DialogueTurn(direction=TurnDirection.A_TO_B, content="test")
        assert turn.delivery_timeout == 120.0
        assert turn.verification_timeout == 60.0

    def test_default_metadata(self):
        """Default metadata should be empty dict."""
        turn = DialogueTurn(direction=TurnDirection.A_TO_B, content="test")
        assert turn.metadata == {}

    def test_custom_values(self):
        """Custom values should be preserved."""
        turn = DialogueTurn(
            direction=TurnDirection.B_TO_A,
            content="hello",
            delivery_timeout=30.0,
            verification_timeout=15.0,
            metadata={"tag": "custom"},
        )
        assert turn.direction == TurnDirection.B_TO_A
        assert turn.content == "hello"
        assert turn.delivery_timeout == 30.0
        assert turn.verification_timeout == 15.0
        assert turn.metadata == {"tag": "custom"}


class TestDialogueScript:
    """Tests for DialogueScript dataclass and YAML loading."""

    def test_default_delays(self):
        """Default delays should be setup=5.0, inter_turn=2.0."""
        script = DialogueScript(name="test", description="", turns=[])
        assert script.setup_delay == 5.0
        assert script.inter_turn_delay == 2.0

    def test_from_yaml_minimal(self):
        """from_yaml with minimal data should set defaults."""
        data = {
            "name": "simple",
            "turns": [
                {"direction": "a_to_b", "content": "ping"},
            ],
        }
        script = DialogueScript.from_yaml(data)
        assert script.name == "simple"
        assert script.description == ""
        assert len(script.turns) == 1
        assert script.turns[0].direction == TurnDirection.A_TO_B
        assert script.turns[0].content == "ping"
        assert script.setup_delay == 5.0
        assert script.inter_turn_delay == 2.0

    def test_from_yaml_full(self):
        """from_yaml with all fields should parse correctly."""
        data = {
            "name": "full_test",
            "description": "A complete test",
            "setup_delay": 10.0,
            "inter_turn_delay": 3.0,
            "turns": [
                {
                    "direction": "a_to_b",
                    "content": "hello",
                    "delivery_timeout": 60.0,
                    "verification_timeout": 30.0,
                    "metadata": {"seq": 1},
                },
                {
                    "direction": "b_to_a",
                    "content": "world",
                },
            ],
        }
        script = DialogueScript.from_yaml(data)
        assert script.name == "full_test"
        assert script.description == "A complete test"
        assert script.setup_delay == 10.0
        assert script.inter_turn_delay == 3.0
        assert len(script.turns) == 2
        assert script.turns[0].delivery_timeout == 60.0
        assert script.turns[0].metadata == {"seq": 1}
        assert script.turns[1].direction == TurnDirection.B_TO_A
        assert script.turns[1].delivery_timeout == 120.0  # default

    def test_from_yaml_empty_turns(self):
        """from_yaml with no turns should return empty list."""
        data = {"name": "empty", "turns": []}
        script = DialogueScript.from_yaml(data)
        assert script.turns == []


class TestLoadDialogueScripts:
    """Tests for load_dialogue_scripts function."""

    def test_load_from_scripts_directory(self):
        """Should load YAML files from the scripts directory."""
        scripts_dir = Path(__file__).parent.parent / "dialogues" / "scripts"
        if not scripts_dir.exists():
            pytest.skip("Scripts directory not found")

        scripts = load_dialogue_scripts(scripts_dir)
        assert len(scripts) > 0
        for script in scripts:
            assert script.name
            assert len(script.turns) > 0

    def test_load_from_empty_directory(self, tmp_path):
        """Should return empty list for directory with no YAML files."""
        scripts = load_dialogue_scripts(tmp_path)
        assert scripts == []

    def test_load_preserves_order(self, tmp_path):
        """Scripts should be sorted by filename."""
        import yaml

        for name in ["c_third.yaml", "a_first.yaml", "b_second.yaml"]:
            data = {"name": name.replace(".yaml", ""), "turns": []}
            with open(tmp_path / name, "w") as f:
                yaml.dump(data, f)

        scripts = load_dialogue_scripts(tmp_path)
        assert [s.name for s in scripts] == ["a_first", "b_second", "c_third"]


class TestMultiNodeDialogueTurn:
    """Tests for MultiNodeDialogueTurn (Phase 5 design)."""

    def test_defaults(self):
        """Default timeouts should match 2-node defaults."""
        turn = MultiNodeDialogueTurn(sender="A", receiver="B", content="test")
        assert turn.delivery_timeout == 120.0
        assert turn.verification_timeout == 60.0
        assert turn.metadata == {}


class TestMultiNodeDialogueScript:
    """Tests for MultiNodeDialogueScript (Phase 5 design)."""

    def test_from_yaml(self):
        """from_yaml should parse multi-node script."""
        data = {
            "name": "multi_test",
            "description": "Multi-node test",
            "node_roles": ["A", "B", "C"],
            "turns": [
                {"sender": "A", "receiver": "B", "content": "hello"},
                {"sender": "B", "receiver": "C", "content": "relay"},
            ],
        }
        script = MultiNodeDialogueScript.from_yaml(data)
        assert script.name == "multi_test"
        assert script.node_roles == ["A", "B", "C"]
        assert len(script.turns) == 2
        assert script.turns[0].sender == "A"
        assert script.turns[1].receiver == "C"
