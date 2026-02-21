"""Asset resolver service.

Resolves and manages provisioning assets (NixOS images, scripts, etc.).
Future implementation will support caching, downloading, and version management.
"""

from pathlib import Path


class AssetNotFoundError(Exception):
    """Raised when a required asset cannot be resolved."""

    pass


async def resolve_nixos_image(arch: str) -> str:
    """Resolve path to NixOS image for the given architecture.

    Args:
        arch: Target architecture (e.g., "aarch64", "x86_64").

    Returns:
        Path to the NixOS image (local file or URL).

    Raises:
        AssetNotFoundError: If no image is available for the architecture.

    Note:
        This is a mock implementation. Future versions will:
        - Check cache directory for existing images
        - Download from configured mirror if not cached
        - Verify checksums
        - Support version selection
    """
    # Mock implementation - return placeholder paths
    mock_images = {
        "aarch64": "/tmp/nixos-aarch64.img",
        "x86_64": "/tmp/nixos-x86_64.img",
    }

    if arch not in mock_images:
        raise AssetNotFoundError(f"No NixOS image available for architecture: {arch}")

    return mock_images[arch]


async def resolve_provisioning_script() -> str:
    """Resolve path to provisioning script (styrene-media.sh).

    Returns:
        Path to the provisioning script.

    Raises:
        AssetNotFoundError: If script cannot be found.

    Note:
        This is a mock implementation. Future versions will:
        - Search for script in package data
        - Check for user-provided overrides
        - Validate script contents
    """
    # Mock implementation - return placeholder
    return "/tmp/styrene-media.sh"


async def get_cache_dir() -> Path:
    """Get the cache directory for provisioning assets.

    Returns:
        Path to cache directory (created if it doesn't exist).

    Note:
        Future implementation will use platformdirs to get the proper
        cache directory for the current platform.
    """
    # Mock implementation
    cache_dir = Path("/tmp/styrene-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


async def clear_cache() -> None:
    """Clear the provisioning asset cache.

    Note:
        Future implementation will remove all cached images and verify
        they can be re-downloaded.
    """
    # Mock implementation - no-op
    pass
