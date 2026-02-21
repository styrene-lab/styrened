"""First-run setup status service.

Checks whether the styrened instance has been configured for first use.
"""

from __future__ import annotations

from dataclasses import dataclass

from styrened.services.config import get_config_dir
from styrened.services.reticulum import get_operator_identity, is_reticulum_configured


@dataclass
class SetupStatus:
    """Status of first-run setup completion.

    Attributes:
        identity_configured: Whether an operator identity exists.
        config_file_exists: Whether the core config file has been created.
        display_name_set: Whether display_name differs from the default.
        rns_initialized: Whether a Reticulum config directory exists.
    """

    identity_configured: bool
    config_file_exists: bool
    display_name_set: bool
    rns_initialized: bool

    @property
    def is_complete(self) -> bool:
        """Return True if all setup steps are done."""
        return all([
            self.identity_configured,
            self.config_file_exists,
            self.display_name_set,
            self.rns_initialized,
        ])


def get_setup_status() -> SetupStatus:
    """Check first-run setup conditions.

    Returns:
        SetupStatus with the state of each setup step.
    """
    from styrened.services.config import load_core_config

    # Identity check
    identity_hash = get_operator_identity()
    identity_configured = identity_hash is not None

    # Config file check
    config_path = get_config_dir() / "core-config.yaml"
    config_file_exists = config_path.exists()

    # Display name check — load config to see if customized
    config = load_core_config()
    display_name_set = config.identity.display_name != "Anonymous Styrene"

    # RNS initialized check
    rns_initialized = is_reticulum_configured()

    return SetupStatus(
        identity_configured=identity_configured,
        config_file_exists=config_file_exists,
        display_name_set=display_name_set,
        rns_initialized=rns_initialized,
    )
