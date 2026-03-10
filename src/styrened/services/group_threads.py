"""Group-thread footprint policy helpers.

This module chooses safe defaults for room storage/feature tiers based on
coarse local hardware signals while keeping the result operator-overridable.
"""

from __future__ import annotations

from dataclasses import dataclass

from styrened.models.config import GroupThreadFeatureTierConfig


@dataclass(frozen=True)
class HardwareFootprintInputs:
    """Coarse hardware signals for choosing initial group-thread defaults."""

    memory_mb: int | None = None
    storage_gb: int | None = None
    device_profile: str | None = None


def choose_group_thread_feature_tier(
    inputs: HardwareFootprintInputs,
) -> GroupThreadFeatureTierConfig:
    """Choose a conservative default tier from coarse hardware signals.

    Rules intentionally bias toward lower footprint on tiny devices.
    Operators can override the result later in config/UI.
    """
    profile = (inputs.device_profile or "").lower()
    memory_mb = inputs.memory_mb or 0
    storage_gb = inputs.storage_gb or 0

    if profile in {"lora", "field", "tiny", "micro", "endpoint-lowpower"}:
        return GroupThreadFeatureTierConfig.MINIMAL
    if memory_mb and memory_mb <= 1024:
        return GroupThreadFeatureTierConfig.MINIMAL
    if storage_gb and storage_gb <= 8:
        return GroupThreadFeatureTierConfig.MINIMAL
    if memory_mb and memory_mb <= 4096:
        return GroupThreadFeatureTierConfig.BALANCED
    if storage_gb and storage_gb <= 32:
        return GroupThreadFeatureTierConfig.BALANCED
    return GroupThreadFeatureTierConfig.FULL
