"""Error types for binary provisioning and verification."""

from __future__ import annotations


class BinaryIntegrityError(Exception):
    """Raised when a binary fails SHA-256 integrity verification in strict mode."""

    def __init__(self, adapter_name: str, expected: str, actual: str) -> None:
        self.adapter_name = adapter_name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{adapter_name} binary integrity check failed: "
            f"expected SHA-256 {expected}, got {actual}"
        )


class UnsupportedPlatformError(Exception):
    """Raised when the current platform is not in the binary manifest."""

    def __init__(self, platform_key: str) -> None:
        self.platform_key = platform_key
        super().__init__(f"Unsupported platform: {platform_key}")
