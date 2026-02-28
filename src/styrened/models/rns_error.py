"""RNS initialization error states.

Provides a structured model for capturing and categorizing Reticulum
initialization failures to enable informative UX for degraded states.
"""

from dataclasses import dataclass
from enum import Enum


class RNSErrorCategory(Enum):
    """Categories of RNS initialization failures.

    Each category maps to a user-facing explanation and suggested
    recovery action in the TUI.
    """

    # Not a failure - clean state
    NONE = "none"

    # Configuration issues
    NOT_CONFIGURED = "not_configured"  # No config file exists
    CONFIG_PARSE_ERROR = "config_parse_error"  # Config file malformed
    CONFIG_PERMISSION = "config_permission"  # Can't read config

    # Identity issues
    IDENTITY_CORRUPT = "identity_corrupt"  # Identity file invalid
    IDENTITY_PERMISSION = "identity_permission"  # Can't read identity

    # Runtime issues
    PORT_CONFLICT = "port_conflict"  # Interface can't bind
    INTERFACE_FAILURE = "interface_failure"  # Interface failed to start

    # Unknown/catch-all
    UNKNOWN = "unknown"


# User-facing descriptions and recovery guidance
RNS_ERROR_INFO: dict[RNSErrorCategory, dict[str, str]] = {
    RNSErrorCategory.NONE: {
        "title": "Online",
        "description": "Reticulum is running normally.",
        "recovery": "",
    },
    RNSErrorCategory.NOT_CONFIGURED: {
        "title": "Not Configured",
        "description": "Reticulum configuration not found.",
        "recovery": "Run the setup wizard to initialize Reticulum.",
    },
    RNSErrorCategory.CONFIG_PARSE_ERROR: {
        "title": "Config Error",
        "description": "Reticulum config file is malformed.",
        "recovery": "Check ~/.reticulum/config for syntax errors or delete to regenerate.",
    },
    RNSErrorCategory.CONFIG_PERMISSION: {
        "title": "Permission Denied",
        "description": "Cannot read Reticulum configuration.",
        "recovery": "Check permissions on ~/.reticulum/ directory.",
    },
    RNSErrorCategory.IDENTITY_CORRUPT: {
        "title": "Identity Corrupt",
        "description": "Operator identity file is invalid.",
        "recovery": "Delete ~/.config/styrene/identity to regenerate identity.",
    },
    RNSErrorCategory.IDENTITY_PERMISSION: {
        "title": "Identity Permission",
        "description": "Cannot read operator identity file.",
        "recovery": "Check permissions on ~/.config/styrene/identity",
    },
    RNSErrorCategory.PORT_CONFLICT: {
        "title": "Port Conflict",
        "description": "Interface cannot bind to configured port.",
        "recovery": "Check for other Reticulum instances or adjust interface config.",
    },
    RNSErrorCategory.INTERFACE_FAILURE: {
        "title": "Interface Failed",
        "description": "One or more network interfaces failed to start.",
        "recovery": "Check network connectivity and interface configuration.",
    },
    RNSErrorCategory.UNKNOWN: {
        "title": "Error",
        "description": "Reticulum initialization failed.",
        "recovery": "Check logs for details: ~/.styrene/styrene.log",
    },
}


@dataclass
class RNSErrorState:
    """Captures the state of an RNS initialization failure.

    Attributes:
        category: The error category for UI display.
        exception_type: The exception class name if available.
        message: The exception message or description.
    """

    category: RNSErrorCategory
    exception_type: str | None = None
    message: str | None = None

    @property
    def title(self) -> str:
        """Get the user-facing title for this error."""
        return RNS_ERROR_INFO[self.category]["title"]

    @property
    def description(self) -> str:
        """Get the user-facing description for this error."""
        return RNS_ERROR_INFO[self.category]["description"]

    @property
    def recovery(self) -> str:
        """Get the recovery guidance for this error."""
        return RNS_ERROR_INFO[self.category]["recovery"]

    @property
    def is_error(self) -> bool:
        """Check if this represents an actual error state."""
        return self.category != RNSErrorCategory.NONE

    @classmethod
    def none(cls) -> "RNSErrorState":
        """Create a non-error state (healthy)."""
        return cls(category=RNSErrorCategory.NONE)

    @classmethod
    def from_exception(cls, exc: Exception) -> "RNSErrorState":
        """Categorize an exception into an error state.

        Examines the exception type and message to determine the most
        appropriate error category for user-facing display.

        Args:
            exc: The exception that occurred during initialization.

        Returns:
            An RNSErrorState with appropriate category and details.
        """
        exc_type = type(exc).__name__
        message = str(exc)
        message_lower = message.lower()

        # Identity file issues
        if (
            "ed25519" in message_lower
            or "private key" in message_lower
            or "operator identity" in message_lower
            or ("identity" in message_lower and "corrupt" in message_lower)
        ):
            return cls(
                category=RNSErrorCategory.IDENTITY_CORRUPT,
                exception_type=exc_type,
                message=message,
            )

        # Permission errors
        if isinstance(exc, PermissionError) or "permission" in message_lower:
            # Try to determine if it's config or identity based on path
            if ".styrene" in message_lower or "operator" in message_lower:
                return cls(
                    category=RNSErrorCategory.IDENTITY_PERMISSION,
                    exception_type=exc_type,
                    message=message,
                )
            return cls(
                category=RNSErrorCategory.CONFIG_PERMISSION,
                exception_type=exc_type,
                message=message,
            )

        # Config file issues
        if "config" in message_lower and ("parse" in message_lower or "syntax" in message_lower):
            return cls(
                category=RNSErrorCategory.CONFIG_PARSE_ERROR,
                exception_type=exc_type,
                message=message,
            )

        # Port/binding issues
        if "address already in use" in message_lower or "bind" in message_lower:
            return cls(
                category=RNSErrorCategory.PORT_CONFLICT,
                exception_type=exc_type,
                message=message,
            )

        # Interface issues
        if "interface" in message_lower:
            return cls(
                category=RNSErrorCategory.INTERFACE_FAILURE,
                exception_type=exc_type,
                message=message,
            )

        # File not found for config
        if (isinstance(exc, FileNotFoundError) or "not found" in message_lower) and (
            ".reticulum" in message_lower or "config" in message_lower
        ):
            return cls(
                category=RNSErrorCategory.NOT_CONFIGURED,
                exception_type=exc_type,
                message=message,
            )

        # Fallback to unknown
        return cls(
            category=RNSErrorCategory.UNKNOWN,
            exception_type=exc_type,
            message=message,
        )
