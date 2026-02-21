"""Provisioner service.

Orchestrates device provisioning by invoking styrene-media.sh or mock subprocess.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.profiles import Profile
from styrened.tui.services.asset_resolver import resolve_nixos_image, resolve_provisioning_script
from styrened.tui.services.storage import StorageDevice


@dataclass
class ProvisionResult:
    """Result of a provisioning operation.

    Attributes:
        success: Whether provisioning completed successfully.
        device: Storage device path that was provisioned.
        profile: Profile ID that was used.
        hardware: Hardware ID that was used.
        errors: List of error messages if provisioning failed.
        log: Full output log from provisioning process.
    """

    success: bool
    device: str
    profile: str
    hardware: str
    errors: list[str]
    log: str


class ProvisioningError(Exception):
    """Raised when provisioning fails."""

    pass


class ProvisioningAbortedError(Exception):
    """Raised when provisioning is aborted by user."""

    pass


async def provision_device(
    profile: Profile,
    hardware: Hardware,
    storage: StorageDevice,
    config: dict[str, str],
    progress_callback: Callable[[str], None] | None = None,
    mock: bool = True,
) -> ProvisionResult:
    """Provision device to storage with given configuration.

    Args:
        profile: Profile to provision.
        hardware: Hardware specification.
        storage: Target storage device.
        config: Configuration dictionary with keys:
            - hostname: Device hostname
            - wifi_ssid: WiFi SSID (optional)
            - wifi_password: WiFi password (optional)
            - ssh_key_path: Path to SSH public key (optional)
            - mesh_enabled: Whether to enable mesh networking (optional)
        progress_callback: Optional callback for progress updates.
        mock: If True, runs mock provisioning instead of real subprocess.

    Returns:
        ProvisionResult with provisioning outcome.

    Raises:
        ProvisioningError: If provisioning fails.
        ProvisioningAbortedError: If provisioning is aborted.
    """
    log_lines: list[str] = []

    def log(message: str) -> None:
        """Log a message and send to progress callback."""
        log_lines.append(message)
        if progress_callback:
            progress_callback(message)

    try:
        log(f"Starting provisioning for {storage.device}")
        log(f"Profile: {profile.label} ({profile.id})")
        log(f"Hardware: {hardware.label} ({hardware.id})")
        log(f"Architecture: {hardware.arch}")
        log("")

        # Validate storage is not mounted
        if storage.mounted:
            error = f"Storage device {storage.device} is mounted. Please unmount first."
            log(f"ERROR: {error}")
            return ProvisionResult(
                success=False,
                device=storage.device,
                profile=profile.id,
                hardware=hardware.id,
                errors=[error],
                log="\n".join(log_lines),
            )

        # Resolve assets
        log("Resolving provisioning assets...")
        nixos_image = await resolve_nixos_image(hardware.arch)
        log(f"NixOS image: {nixos_image}")

        provisioning_script = await resolve_provisioning_script()
        log(f"Provisioning script: {provisioning_script}")
        log("")

        if mock:
            # Run mock provisioning
            result = await _mock_provision(profile, hardware, storage, config, nixos_image, log)
        else:
            # Run real provisioning
            result = await _real_provision(
                profile,
                hardware,
                storage,
                config,
                nixos_image,
                provisioning_script,
                log,
            )

        if result:
            log("")
            log("Provisioning completed successfully!")
            return ProvisionResult(
                success=True,
                device=storage.device,
                profile=profile.id,
                hardware=hardware.id,
                errors=[],
                log="\n".join(log_lines),
            )
        else:
            error = "Provisioning failed"
            log(f"ERROR: {error}")
            return ProvisionResult(
                success=False,
                device=storage.device,
                profile=profile.id,
                hardware=hardware.id,
                errors=[error],
                log="\n".join(log_lines),
            )

    except Exception as e:
        error = f"Provisioning error: {e}"
        log(f"ERROR: {error}")
        return ProvisionResult(
            success=False,
            device=storage.device,
            profile=profile.id,
            hardware=hardware.id,
            errors=[error],
            log="\n".join(log_lines),
        )


async def _mock_provision(
    profile: Profile,
    hardware: Hardware,
    storage: StorageDevice,
    config: dict[str, str],
    nixos_image: str,
    log: Callable[[str], None],
) -> bool:
    """Run mock provisioning with simulated progress.

    Args:
        profile: Profile to provision.
        hardware: Hardware specification.
        storage: Target storage device.
        config: Configuration dictionary.
        nixos_image: Path to NixOS image.
        log: Logging function.

    Returns:
        True if mock provisioning succeeds.
    """
    log("Running mock provisioning...")
    log("")

    # Simulate provisioning steps
    steps = [
        ("Validating configuration", 0.5),
        ("Partitioning storage device", 1.0),
        ("Creating filesystems", 0.8),
        (f"Writing NixOS image to {storage.device}", 2.0),
        ("Configuring hostname and network", 0.5),
        ("Installing SSH keys", 0.3),
        ("Setting up mesh networking", 0.7),
        ("Syncing and unmounting", 0.5),
    ]

    for step, duration in steps:
        log(f"[*] {step}...")
        await asyncio.sleep(duration)
        log("    ✓ Complete")

    return True


async def _real_provision(
    profile: Profile,
    hardware: Hardware,
    storage: StorageDevice,
    config: dict[str, str],
    nixos_image: str,
    provisioning_script: str,
    log: Callable[[str], None],
) -> bool:
    """Run real provisioning using styrene-media.sh.

    Args:
        profile: Profile to provision.
        hardware: Hardware specification.
        storage: Target storage device.
        config: Configuration dictionary.
        nixos_image: Path to NixOS image.
        provisioning_script: Path to provisioning script.
        log: Logging function.

    Returns:
        True if provisioning succeeds.

    Raises:
        ProvisioningError: If script execution fails.
    """
    log("Running provisioning script...")
    log("")

    # Build command arguments
    cmd = [
        provisioning_script,
        "--device",
        storage.device,
        "--image",
        nixos_image,
        "--profile",
        profile.id,
        "--hardware",
        hardware.id,
        "--hostname",
        config.get("hostname", "styrene-device"),
    ]

    # Add optional arguments
    if config.get("wifi_ssid"):
        cmd.extend(["--wifi-ssid", config["wifi_ssid"]])
    if config.get("wifi_password"):
        cmd.extend(["--wifi-password", config["wifi_password"]])
    if config.get("ssh_key_path"):
        cmd.extend(["--ssh-key", config["ssh_key_path"]])
    if config.get("mesh_enabled") == "true":
        cmd.append("--enable-mesh")

    # Run subprocess and stream output
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Stream output
        if proc.stdout:
            async for line in proc.stdout:
                log(line.decode().rstrip())

        # Wait for completion
        returncode = await proc.wait()

        if returncode != 0:
            raise ProvisioningError(f"Provisioning script exited with code {returncode}")

        return True

    except FileNotFoundError as e:
        raise ProvisioningError(f"Provisioning script not found: {provisioning_script}") from e
    except Exception as e:
        raise ProvisioningError(f"Failed to run provisioning script: {e}") from e


async def abort_provision() -> None:
    """Abort an in-progress provisioning operation.

    Note:
        Future implementation will track running subprocesses and
        send termination signals.
    """
    # Mock implementation - no-op
    pass
