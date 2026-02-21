"""Tests for asset resolver service."""

import pytest

from styrened.tui.services.asset_resolver import (
    AssetNotFoundError,
    resolve_nixos_image,
    resolve_provisioning_script,
)


@pytest.mark.asyncio
async def test_resolve_nixos_image_aarch64():
    """Test resolving NixOS image for aarch64."""
    image_path = await resolve_nixos_image("aarch64")
    assert image_path
    assert "aarch64" in image_path


@pytest.mark.asyncio
async def test_resolve_nixos_image_x86_64():
    """Test resolving NixOS image for x86_64."""
    image_path = await resolve_nixos_image("x86_64")
    assert image_path
    assert "x86_64" in image_path


@pytest.mark.asyncio
async def test_resolve_nixos_image_unsupported():
    """Test resolving NixOS image for unsupported architecture."""
    with pytest.raises(AssetNotFoundError):
        await resolve_nixos_image("unsupported_arch")


@pytest.mark.asyncio
async def test_resolve_provisioning_script():
    """Test resolving provisioning script."""
    script_path = await resolve_provisioning_script()
    assert script_path
    assert "styrene-media" in script_path
