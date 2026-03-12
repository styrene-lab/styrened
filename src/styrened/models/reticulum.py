"""Reticulum identity and configuration models.

These models represent the data parsed from Reticulum's configuration
files without requiring the RNS library itself.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from pathlib import Path


class ReticulumNotConfiguredError(Exception):
    """Raised when Reticulum is not configured on the system.

    This error indicates that the ~/.reticulum directory or required
    configuration files are missing. A setup wizard should guide the
    user through initial Reticulum configuration.

    TODO: Future implementation will include a setup wizard that can
    initialize Reticulum configuration when this error is encountered.
    """

    def __init__(self, message: str | None = None) -> None:
        if message is None:
            message = (
                "Reticulum is not configured. "
                "Expected configuration directory at ~/.reticulum/ with config and identity files. "
                "Please run 'rnsd' or 'python -m RNS' to initialize Reticulum."
            )
        super().__init__(message)


@dataclass(frozen=True)
class ReticulumIdentity:
    """Represents a Reticulum identity.

    The identity is derived from the cryptographic key stored in
    ~/.reticulum/storage/identity. The address is the hex-encoded
    representation of the identity hash.

    Attributes:
        address: Hex-encoded identity address string.
        created: Unix timestamp of identity creation, if available.
    """

    address: str
    created: int | None = None

    def truncated_address(self, prefix_len: int = 4, suffix_len: int = 4) -> str:
        """Return a truncated version of the address for display.

        Args:
            prefix_len: Number of characters to show at the start.
            suffix_len: Number of characters to show at the end.

        Returns:
            Truncated address in format "xxxx...yyyy".
        """
        if len(self.address) <= prefix_len + suffix_len + 3:
            return self.address
        return f"{self.address[:prefix_len]}...{self.address[-suffix_len:]}"


@dataclass(frozen=True)
class ReticulumInterface:
    """Represents a configured Reticulum network interface.

    Interfaces define how Reticulum communicates with the network.
    Common types include AutoInterface (local discovery), TCPClientInterface,
    TCPServerInterface, and UDPInterface.

    Attributes:
        name: Human-readable interface name from config.
        interface_type: The interface type (e.g., AutoInterface, TCPClientInterface).
        enabled: Whether the interface is enabled in the configuration.
    """

    name: str
    interface_type: str
    enabled: bool = True


@dataclass
class ReticulumState:
    """Complete Reticulum configuration state.

    This combines the identity, configured interfaces, and configuration
    path into a single object representing the current Reticulum setup.

    Note: This represents the actual parsed RNS state, different from
    ReticulumConfig in models/config.py which is Styrene's configuration.

    Attributes:
        identity: The local Reticulum identity.
        interfaces: List of configured interfaces.
        config_path: Path to the Reticulum configuration directory.
    """

    identity: ReticulumIdentity
    interfaces: list[ReticulumInterface] = field(default_factory=list)
    config_path: Path = field(default_factory=lambda: Path.home() / ".reticulum")

    @property
    def enabled_interface_count(self) -> int:
        """Return the number of enabled interfaces."""
        return sum(1 for i in self.interfaces if i.enabled)

    @property
    def total_interface_count(self) -> int:
        """Return the total number of configured interfaces."""
        return len(self.interfaces)
