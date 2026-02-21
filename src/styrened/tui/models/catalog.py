"""Catalog data models for Styrene TUI.

This module defines the data models for hardware, roles, and profiles as
defined in the YAML catalogs. These represent the provisioning taxonomy:
- Hardware: Specific device models we can provision
- Role: Functional capability a device provides
- Profile: Deployable unit composed of roles
"""

from dataclasses import dataclass


@dataclass
class Hardware:
    """Represents a specific hardware device model.

    Hardware definitions are the concrete devices we know how to provision.
    Each hardware entry specifies its architecture, boot method, provisioning
    activity (workflow), and traits (capabilities).

    Attributes:
        id: Unique identifier (e.g., "rpi4", "t100ta").
        label: Human-readable name (e.g., "Raspberry Pi 4").
        arch: CPU architecture (e.g., "aarch64", "x86_64").
        boot: Boot method (e.g., "uboot", "uefi64", "uefi32").
        activity: Provisioning workflow (e.g., "nixos-direct", "nixos-installer").
        traits: List of capabilities (e.g., ["low_power", "gpio", "wifi"]).
        type: Optional device type classification (e.g., "router").
    """

    id: str
    label: str
    arch: str
    boot: str
    activity: str
    traits: list[str]
    type: str | None = None

    def has_trait(self, trait: str) -> bool:
        """Check if hardware has a specific trait.

        Args:
            trait: Trait name to check.

        Returns:
            True if hardware has the trait.
        """
        return trait in self.traits

    def has_all_traits(self, traits: list[str]) -> bool:
        """Check if hardware has all specified traits.

        Args:
            traits: List of trait names to check.

        Returns:
            True if hardware has all traits.
        """
        return all(self.has_trait(t) for t in traits)


@dataclass
class Role:
    """Represents a functional role a device can fulfill.

    Roles define capabilities that devices provide. A role specifies which
    provisioning activity (or activities) it requires and what services it
    provides to the fleet.

    Attributes:
        id: Unique identifier (e.g., "styrene-node", "mesh-router").
        label: Human-readable name (e.g., "Styrene Node").
        description: Detailed description of role purpose.
        activity: Required provisioning activity or list of activities.
        provides: List of services/capabilities this role provides.
    """

    id: str
    label: str
    description: str
    activity: str | list[str]
    provides: list[str]

    def supports_activity(self, activity: str) -> bool:
        """Check if role supports a specific provisioning activity.

        Args:
            activity: Activity name to check.

        Returns:
            True if role supports the activity.
        """
        if isinstance(self.activity, str):
            return self.activity == activity
        return activity in self.activity


@dataclass
class Profile:
    """Represents a deployable profile composed of roles.

    Profiles are the top-level provisioning units. A profile specifies
    which roles it requires, what traits the hardware must have, and
    which hardware combinations have been verified to work.

    Attributes:
        id: Unique identifier (e.g., "node", "edge-router").
        label: Human-readable name (e.g., "Edge Router").
        description: Detailed description of profile purpose.
        roles: List of role IDs that compose this profile.
        verified: List of verified hardware combinations (each is a list of hardware IDs).
        requires_traits: Optional list of traits hardware must have.
    """

    id: str
    label: str
    description: str
    roles: list[str]
    verified: list[list[str]]
    requires_traits: list[str] | None = None

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


@dataclass
class Catalog:
    """Complete catalog of hardware, roles, and profiles.

    Attributes:
        hardware: Dictionary of hardware ID to Hardware objects.
        roles: Dictionary of role ID to Role objects.
        profiles: Dictionary of profile ID to Profile objects.
    """

    hardware: dict[str, Hardware]
    roles: dict[str, Role]
    profiles: dict[str, Profile]
