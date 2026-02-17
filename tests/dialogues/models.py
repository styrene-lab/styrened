"""Dialogue script data models.

Defines the structure of dialogue scripts that drive multi-turn
conversation testing between styrened instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class TurnDirection(Enum):
    """Direction of a dialogue turn."""

    A_TO_B = "a_to_b"
    B_TO_A = "b_to_a"


@dataclass
class DialogueTurn:
    """A single turn in a dialogue script."""

    direction: TurnDirection
    content: str
    delivery_timeout: float = 120.0
    verification_timeout: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogueScript:
    """A complete dialogue script with ordered turns."""

    name: str
    description: str
    turns: list[DialogueTurn]
    setup_delay: float = 5.0
    inter_turn_delay: float = 2.0

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> DialogueScript:
        """Create a DialogueScript from parsed YAML data.

        Args:
            data: Dict from YAML with name, description, turns, etc.

        Returns:
            DialogueScript instance.
        """
        turns = []
        for turn_data in data.get("turns", []):
            direction = TurnDirection(turn_data["direction"])
            turns.append(
                DialogueTurn(
                    direction=direction,
                    content=turn_data["content"],
                    delivery_timeout=turn_data.get("delivery_timeout", 120.0),
                    verification_timeout=turn_data.get("verification_timeout", 60.0),
                    metadata=turn_data.get("metadata", {}),
                )
            )

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            turns=turns,
            setup_delay=data.get("setup_delay", 5.0),
            inter_turn_delay=data.get("inter_turn_delay", 2.0),
        )


def load_dialogue_scripts(directory: Path) -> list[DialogueScript]:
    """Load all dialogue scripts from a directory.

    Args:
        directory: Path to directory containing YAML script files.

    Returns:
        List of DialogueScript instances, sorted by filename.
    """
    scripts = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data:
            scripts.append(DialogueScript.from_yaml(data))
    return scripts


# ---------------------------------------------------------------------------
# Multi-node types (Phase 5 — design only)
# ---------------------------------------------------------------------------


@dataclass
class MultiNodeDialogueTurn:
    """A turn in a multi-node dialogue script."""

    sender: str
    receiver: str
    content: str
    delivery_timeout: float = 120.0
    verification_timeout: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiNodeDialogueScript:
    """A dialogue script for multi-node topologies."""

    name: str
    description: str
    node_roles: list[str]
    turns: list[MultiNodeDialogueTurn]
    setup_delay: float = 5.0
    inter_turn_delay: float = 2.0

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> MultiNodeDialogueScript:
        """Create from parsed YAML data."""
        turns = []
        for turn_data in data.get("turns", []):
            turns.append(
                MultiNodeDialogueTurn(
                    sender=turn_data["sender"],
                    receiver=turn_data["receiver"],
                    content=turn_data["content"],
                    delivery_timeout=turn_data.get("delivery_timeout", 120.0),
                    verification_timeout=turn_data.get("verification_timeout", 60.0),
                    metadata=turn_data.get("metadata", {}),
                )
            )

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            node_roles=data.get("node_roles", []),
            turns=turns,
            setup_delay=data.get("setup_delay", 5.0),
            inter_turn_delay=data.get("inter_turn_delay", 2.0),
        )
