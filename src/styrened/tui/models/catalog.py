"""Catalog data models for Styrene TUI.

Convenience re-export of Hardware, Role, and Profile from their
individual modules, plus the aggregate Catalog container.

Use this module when you want all three types in a single import:

    from styrened.tui.models.catalog import Hardware, Role, Profile, Catalog

Individual modules are preferred for explicit imports:

    from styrened.tui.models.device_hardware import Hardware
    from styrened.tui.models.profiles import Profile
    from styrened.tui.models.roles import Role
"""

from dataclasses import dataclass

from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.profiles import Profile
from styrened.tui.models.roles import Role

__all__ = ["Hardware", "Role", "Profile", "Catalog"]


@dataclass
class Catalog:
    """Complete catalog of hardware, roles, and profiles.

    Returned by :func:`styrened.tui.services.catalog.load_catalog`.

    Attributes:
        hardware: Mapping of hardware ID to :class:`Hardware`.
        roles: Mapping of role ID to :class:`Role`.
        profiles: Mapping of profile ID to :class:`Profile`.
    """

    hardware: dict[str, Hardware]
    roles: dict[str, Role]
    profiles: dict[str, Profile]
