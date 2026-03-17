"""Tests for group-thread footprint policy helpers."""
from __future__ import annotations

from styrened.models.config import GroupThreadFeatureTierConfig
from styrened.services.group_threads import (
    HardwareFootprintInputs,
    choose_group_thread_feature_tier,
)


class TestChooseGroupThreadFeatureTier:
    def test_low_memory_defaults_to_minimal(self) -> None:
        tier = choose_group_thread_feature_tier(HardwareFootprintInputs(memory_mb=512, storage_gb=64))
        assert tier is GroupThreadFeatureTierConfig.MINIMAL

    def test_small_storage_defaults_to_minimal(self) -> None:
        tier = choose_group_thread_feature_tier(HardwareFootprintInputs(memory_mb=8192, storage_gb=4))
        assert tier is GroupThreadFeatureTierConfig.MINIMAL

    def test_lowpower_profile_defaults_to_minimal(self) -> None:
        tier = choose_group_thread_feature_tier(HardwareFootprintInputs(device_profile="lora", memory_mb=4096, storage_gb=64))
        assert tier is GroupThreadFeatureTierConfig.MINIMAL

    def test_midrange_defaults_to_balanced(self) -> None:
        tier = choose_group_thread_feature_tier(HardwareFootprintInputs(memory_mb=2048, storage_gb=16))
        assert tier is GroupThreadFeatureTierConfig.BALANCED

    def test_large_system_defaults_to_full(self) -> None:
        tier = choose_group_thread_feature_tier(HardwareFootprintInputs(memory_mb=8192, storage_gb=256, device_profile="desktop"))
        assert tier is GroupThreadFeatureTierConfig.FULL
