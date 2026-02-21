"""Device hardware models.

Data models for hardware specifications used in provisioning.
"""

from dataclasses import dataclass


@dataclass
class Hardware:
    """Hardware specification.

    Attributes:
        id: Unique hardware identifier (e.g., "rpi4").
        label: Human-readable label (e.g., "Raspberry Pi 4").
        arch: Architecture (e.g., "aarch64", "x86_64").
        boot: Boot method (e.g., "uefi", "bios", "sd").
        activity: Expected activity level (e.g., "low", "medium", "high").
        traits: List of hardware traits (e.g., "wifi", "bluetooth", "gpio").
        type: Optional hardware type classification.
    """

    id: str
    label: str
    arch: str
    boot: str
    activity: str
    traits: list[str]
    type: str | None = None

    def has_trait(self, trait: str) -> bool:
        """Check if hardware has a specific trait."""
        return trait in self.traits

    def has_all_traits(self, traits: list[str]) -> bool:
        """Check if hardware has all specified traits."""
        return all(self.has_trait(t) for t in traits)
