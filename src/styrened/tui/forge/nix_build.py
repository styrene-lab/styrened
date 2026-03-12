"""Nix image resolution — builds or fetches a Nix-built SD image.

Extracted from styrene-edge. Runs ``nix build`` against the sbc flake
to produce a compressed SD image.
"""
from __future__ import annotations


import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

from styrened.tui.forge.models import MediaEvent


def _log(msg: str) -> MediaEvent:
    return MediaEvent(kind="log", message=msg)


def _error(msg: str) -> MediaEvent:
    return MediaEvent(kind="error", message=msg)


def _diagnose_nix_error(stderr: str, exit_code: int) -> str:
    """Parse nix build stderr and return an actionable error message."""
    if "Cannot build" in stderr and "required system" in stderr:
        return (
            "Image not in Cachix and cannot be built on this system "
            "(wrong architecture). Build on an aarch64-linux host and run: "
            "cachix push styrene /nix/store/<path>"
        )
    # Filter out Git tree warnings — not real errors
    lines = [
        ln for ln in stderr.splitlines()
        if ln.strip() and not ln.startswith("warning: Git tree")
    ]
    if not lines:
        return f"nix build failed (exit {exit_code}) with no actionable output"
    tail = "\n".join(lines[-5:])
    return f"nix build failed (exit {exit_code}):\n{tail}"


async def resolve_nix_image(
    flake_output: str,
    edge_dir: Path,
) -> AsyncIterator[tuple[MediaEvent, Path | None]]:
    """Resolve a Nix-built SD image, yielding progress events.

    Runs ``nix build ./sbc#<flake_output> --no-link --print-out-paths``
    and locates the ``.img.zst`` inside the resulting store path.

    Yields ``(event, path)`` tuples.  All tuples except the final one have
    ``path=None``.  The final tuple carries the resolved ``.img.zst`` path.

    Args:
        flake_output: Nix flake output reference.
        edge_dir: Path to styrene-edge repository root.
    """
    flake_ref = f"{edge_dir / 'sbc'}#{flake_output}"
    yield _log(f"Resolving Nix image: {flake_output}"), None

    cmd = [
        "nix", "build", flake_ref,
        "--no-link", "--print-out-paths",
    ]

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Stream heartbeat while waiting
    while True:
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=15.0,
            )
            break
        except TimeoutError:
            elapsed = int(time.monotonic() - start)
            yield _log(f"  nix build running ({elapsed}s elapsed...)"), None

    elapsed = int(time.monotonic() - start)

    if proc.returncode != 0:
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        msg = _diagnose_nix_error(stderr, proc.returncode)
        yield _error(msg), None
        return

    store_path = Path(stdout_bytes.decode().strip())
    yield _log(f"  Store path: {store_path} ({elapsed}s)"), None

    # Locate the .img.zst inside the store path
    sd_image_dir = store_path / "sd-image"
    if not sd_image_dir.is_dir():
        yield _error(f"Expected sd-image/ directory not found in {store_path}"), None
        return

    zst_files = list(sd_image_dir.glob("*.img.zst"))
    if not zst_files:
        yield _error(f"No .img.zst found in {sd_image_dir}"), None
        return

    img_path = zst_files[0]
    size_mb = img_path.stat().st_size / (1024 * 1024)
    yield _log(f"  Image: {img_path.name} ({size_mb:.0f} MB)"), img_path
