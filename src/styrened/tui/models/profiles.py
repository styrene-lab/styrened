"""Profile models.

Data models for device provisioning profiles.
"""

from dataclasses import dataclass


@dataclass
class Profile:
    """Device provisioning profile.

    Attributes:
        id: Unique profile identifier (e.g., "node").
        label: Human-readable label.
        description: Profile description.
        roles: List of role IDs this profile implements.
        verified: List of verified hardware combinations (list of hardware IDs).
        requires_traits: Optional list of required hardware traits.
    """

    id: str
    label: str
    description: str
    roles: list[str]
    verified: list[list[str]]
    requires_traits: list[str] | None = None

    def is_verified_for_hardware(self, hardware_ids: list[str]) -> bool:
        """Check if this hardware combination is verified for this profile."""
        hardware_set = set(hardware_ids)
        return any(hardware_set == set(combo) for combo in self.verified)

    def requires_hardware_count(self) -> int:
        """Return the number of hardware devices required.

        For single-device profiles, returns 1. For multi-device profiles
        (like edge-router), returns the number of devices.

        Returns:
            Number of hardware devices needed.
        """
        if not self.verified:
            return len(self.roles)  # Fallback to role count
        # Return the most common hardware count from verified combinations
        return max((len(combo) for combo in self.verified), default=1)

    def is_multi_device(self) -> bool:
        """Check if profile requires multiple devices.

        Returns:
            True if profile spans multiple devices.
        """
        return self.requires_hardware_count() > 1

    def is_verified_combination(self, hardware_ids: list[str]) -> bool:
        """Check if a hardware combination is verified for this profile.

        Args:
            hardware_ids: List of hardware IDs to check.

        Returns:
            True if this exact combination is verified.
        """
        # Sort both for comparison (order shouldn't matter)
        sorted_input = sorted(hardware_ids)
        return any(sorted(combo) == sorted_input for combo in self.verified)
