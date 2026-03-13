"""Tests for forge model files: profiles and roles."""

import pytest

from styrened.tui.models.profiles import Profile
from styrened.tui.models.roles import Role


@pytest.fixture
def sample_profile() -> Profile:
    return Profile(
        id="node",
        label="Styrene Node",
        description="Single-device styrene node profile.",
        roles=["styrene-node"],
        verified=[["rpi4"], ["rpi-zero2w"], ["x86-generic"]],
        requires_traits=None,
    )


@pytest.fixture
def multi_device_profile() -> Profile:
    return Profile(
        id="cluster",
        label="Cluster",
        description="Multi-device cluster profile.",
        roles=["styrene-node", "mesh-router"],
        verified=[["rpi4", "rpi-zero2w"]],
        requires_traits=["low_power"],
    )


@pytest.fixture
def sample_role() -> Role:
    return Role(
        id="styrene-node",
        label="Styrene Node",
        description="Runs the styrened daemon.",
        activity="nixos-direct",
        provides=["mesh", "rpc", "lxmf"],
    )


@pytest.fixture
def multi_activity_role() -> Role:
    return Role(
        id="router",
        label="Router",
        description="Mesh router.",
        activity=["nixos-direct", "nixos-installer"],
        provides=["mesh", "routing"],
    )


class TestProfileIsVerifiedForHardware:
    def test_single_verified_hardware(self, sample_profile: Profile) -> None:
        assert sample_profile.is_verified_for_hardware(["rpi4"]) is True

    def test_unverified_hardware(self, sample_profile: Profile) -> None:
        assert sample_profile.is_verified_for_hardware(["odroid"]) is False

    def test_order_independent(self, multi_device_profile: Profile) -> None:
        assert multi_device_profile.is_verified_for_hardware(["rpi-zero2w", "rpi4"]) is True

    def test_partial_match_fails(self, multi_device_profile: Profile) -> None:
        assert multi_device_profile.is_verified_for_hardware(["rpi4"]) is False

    def test_empty_list(self, sample_profile: Profile) -> None:
        assert sample_profile.is_verified_for_hardware([]) is False


class TestProfileRequiresHardwareCount:
    def test_single_device_profile(self, sample_profile: Profile) -> None:
        assert sample_profile.requires_hardware_count() == 1

    def test_multi_device_profile(self, multi_device_profile: Profile) -> None:
        assert multi_device_profile.requires_hardware_count() == 2

    def test_empty_verified_falls_back_to_roles(self) -> None:
        profile = Profile(
            id="x",
            label="X",
            description="",
            roles=["a", "b"],
            verified=[],
        )
        assert profile.requires_hardware_count() == 2


class TestProfileIsMultiDevice:
    def test_single_device_is_not_multi(self, sample_profile: Profile) -> None:
        assert sample_profile.is_multi_device() is False

    def test_multi_device_is_multi(self, multi_device_profile: Profile) -> None:
        assert multi_device_profile.is_multi_device() is True


class TestRoleSupportsActivity:
    def test_string_activity_match(self, sample_role: Role) -> None:
        assert sample_role.supports_activity("nixos-direct") is True

    def test_string_activity_no_match(self, sample_role: Role) -> None:
        assert sample_role.supports_activity("nixos-installer") is False

    def test_list_activity_match(self, multi_activity_role: Role) -> None:
        assert multi_activity_role.supports_activity("nixos-installer") is True

    def test_list_activity_no_match(self, multi_activity_role: Role) -> None:
        assert multi_activity_role.supports_activity("custom-boot") is False
