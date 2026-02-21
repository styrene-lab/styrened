"""Role models.

Data models for device roles in the fleet.
"""

from dataclasses import dataclass


@dataclass
class Role:
    """Device role definition.

    Attributes:
        id: Unique role identifier (e.g., "styrene-node").
        label: Human-readable label.
        description: Role description.
        activity: Activity level (e.g., "low", "medium", "high") or list of levels.
        provides: List of services/capabilities this role provides.
    """

    id: str
    label: str
    description: str
    activity: str | list[str]
    provides: list[str]

    def supports_activity(self, activity: str) -> bool:
        """Check if this role supports a given activity level."""
        if isinstance(self.activity, str):
            return self.activity == activity
        return activity in self.activity
