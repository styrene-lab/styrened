"""System information detection for announces and status responses.

Provides OS identification, architecture detection, and NixOS generation
extraction. Used by daemon announces (compact fingerprint) and RPC status
responses (full detail).
"""

from __future__ import annotations

import os
import platform


def get_os_info() -> dict[str, str]:
    """Detect OS identity, architecture, and NixOS generation.

    Returns:
        Dictionary with keys:
        - os_id: OS identifier (e.g., "nixos", "debian", "darwin")
        - os_version: OS version (e.g., "24.11", "13", "15.3")
        - arch: CPU architecture (e.g., "x86_64", "aarch64")
        - nixos_generation: First 7 chars of NixOS store hash, or ""
    """
    os_id = ""
    os_version = ""
    arch = platform.machine()
    nixos_generation = ""

    # Detect OS from /etc/os-release (Linux)
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    os_id = line.strip().split("=", 1)[1].strip('"')
                elif line.startswith("VERSION_ID="):
                    os_version = line.strip().split("=", 1)[1].strip('"')
    except FileNotFoundError:
        # Not Linux or no os-release — fall back to platform module
        system = platform.system().lower()
        os_id = system
        if system == "darwin":
            mac_ver = platform.mac_ver()[0]
            os_version = mac_ver if mac_ver else platform.release()
        else:
            os_version = platform.release()

    # NixOS generation: /run/current-system -> /nix/store/<hash>-nixos-system-...
    try:
        target = os.readlink("/run/current-system")
        # Extract store hash: /nix/store/<32-char-hash>-nixos-system-...
        store_name = target.split("/")[-1]
        nixos_generation = store_name[:7]
    except OSError:
        pass

    return {
        "os_id": os_id,
        "os_version": os_version,
        "arch": arch,
        "nixos_generation": nixos_generation,
    }


def get_system_fingerprint() -> str:
    """Build compact system fingerprint for announce data.

    Format: {os_id}|{os_version}|{arch}|{nixos_generation}

    Examples:
        - "nixos|24.11|x86_64|zah57xw" (Styrix node)
        - "debian|13|x86_64|" (non-NixOS Linux)
        - "darwin|15.3|aarch64|" (macOS)

    Returns:
        Pipe-delimited fingerprint string (~25-35 bytes).
    """
    info = get_os_info()
    return f"{info['os_id']}|{info['os_version']}|{info['arch']}|{info['nixos_generation']}"
