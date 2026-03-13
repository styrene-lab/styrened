"""Catalog service for hardware, roles, and profiles.

This service loads and queries device hardware specifications, role definitions,
and provisioning profiles from YAML catalogs.
"""

from pathlib import Path
from typing import Any

import yaml

from styrened.tui.models.catalog import Catalog
from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.profiles import Profile
from styrened.tui.models.roles import Role


class CatalogLoadError(Exception):
    """Raised when catalog files cannot be loaded."""

    pass


def _get_default_catalog_dir() -> Path:
    """Get the default catalog directory.

    Returns:
        Path to the data directory containing catalog YAML files.
    """
    # Catalog files are in the package data directory
    return Path(__file__).parent.parent.parent / "data"


def _load_yaml_file(file_path: Path) -> dict[str, Any]:
    """Load and parse a YAML file.

    Args:
        file_path: Path to YAML file.

    Returns:
        Parsed YAML data.

    Raises:
        CatalogLoadError: If file doesn't exist or can't be parsed.
    """
    if not file_path.exists():
        raise CatalogLoadError(f"Catalog file not found: {file_path}")

    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise CatalogLoadError(f"Invalid YAML structure in {file_path}")
            return data
    except yaml.YAMLError as e:
        raise CatalogLoadError(f"Failed to parse YAML in {file_path}: {e}") from e
    except OSError as e:
        raise CatalogLoadError(f"Failed to read {file_path}: {e}") from e


def _parse_hardware(data: dict[str, Any]) -> dict[str, Hardware]:
    """Parse hardware entries from YAML data.

    Args:
        data: Parsed YAML data containing "hardware" key.

    Returns:
        Dictionary of hardware ID to Hardware objects.
    """
    hardware_dict: dict[str, Hardware] = {}
    hardware_data = data.get("hardware", {})

    for hw_id, hw_info in hardware_data.items():
        hardware = Hardware(
            id=hw_id,
            label=hw_info.get("label", hw_id),
            arch=hw_info.get("arch", ""),
            boot=hw_info.get("boot", ""),
            activity=hw_info.get("activity", ""),
            traits=hw_info.get("traits", []),
            type=hw_info.get("type"),
        )
        hardware_dict[hw_id] = hardware

    return hardware_dict


def _parse_roles(data: dict[str, Any]) -> dict[str, Role]:
    """Parse role entries from YAML data.

    Args:
        data: Parsed YAML data containing "roles" key.

    Returns:
        Dictionary of role ID to Role objects.
    """
    roles_dict: dict[str, Role] = {}
    roles_data = data.get("roles", {})

    for role_id, role_info in roles_data.items():
        role = Role(
            id=role_id,
            label=role_info.get("label", role_id),
            description=role_info.get("description", ""),
            activity=role_info.get("activity", ""),
            provides=role_info.get("provides", []),
        )
        roles_dict[role_id] = role

    return roles_dict


def _parse_profiles(data: dict[str, Any]) -> dict[str, Profile]:
    """Parse profile entries from YAML data.

    Args:
        data: Parsed YAML data containing "profiles" key.

    Returns:
        Dictionary of profile ID to Profile objects.
    """
    profiles_dict: dict[str, Profile] = {}
    profiles_data = data.get("profiles", {})

    for profile_id, profile_info in profiles_data.items():
        profile = Profile(
            id=profile_id,
            label=profile_info.get("label", profile_id),
            description=profile_info.get("description", ""),
            roles=profile_info.get("roles", []),
            verified=profile_info.get("verified", []),
            requires_traits=profile_info.get("requires_traits"),
        )
        profiles_dict[profile_id] = profile

    return profiles_dict


def load_catalog(data_dir: Path | None = None) -> Catalog:
    """Load hardware, roles, profiles from YAML files.

    Args:
        data_dir: Directory containing catalog YAML files.
            If None, uses the default package data directory.

    Returns:
        Catalog with loaded data.

    Raises:
        CatalogLoadError: If any catalog file is missing or invalid.
    """
    if data_dir is None:
        data_dir = _get_default_catalog_dir()

    # Load each catalog file
    hardware_data = _load_yaml_file(data_dir / "hardware.yaml")
    roles_data = _load_yaml_file(data_dir / "roles.yaml")
    profiles_data = _load_yaml_file(data_dir / "profiles.yaml")

    # Parse into model objects
    hardware = _parse_hardware(hardware_data)
    roles = _parse_roles(roles_data)
    profiles = _parse_profiles(profiles_data)

    return Catalog(hardware=hardware, roles=roles, profiles=profiles)


def query_hardware(catalog: Catalog, filters: dict[str, Any] | None = None) -> list[Hardware]:
    """Query hardware by various filters.

    Supported filters:
    - arch: Filter by architecture (exact match)
    - activity: Filter by provisioning activity (exact match)
    - trait: Filter by single trait (hardware must have this trait)
    - traits: Filter by multiple traits (hardware must have all)

    Args:
        catalog: Catalog to query.
        filters: Dictionary of filter criteria.

    Returns:
        List of Hardware objects matching filters.
    """
    hardware_list = list(catalog.hardware.values())

    if not filters:
        return hardware_list

    # Apply filters
    if "arch" in filters:
        hardware_list = [hw for hw in hardware_list if hw.arch == filters["arch"]]

    if "activity" in filters:
        hardware_list = [hw for hw in hardware_list if hw.activity == filters["activity"]]

    if "trait" in filters:
        trait = filters["trait"]
        hardware_list = [hw for hw in hardware_list if hw.has_trait(trait)]

    if "traits" in filters:
        traits = filters["traits"]
        hardware_list = [hw for hw in hardware_list if hw.has_all_traits(traits)]

    return hardware_list


def query_roles(catalog: Catalog, filters: dict[str, Any] | None = None) -> list[Role]:
    """Query roles by various filters.

    Supported filters:
    - activity: Filter by provisioning activity (role must support it)
    - provides: Filter by provided service (role must provide it)

    Args:
        catalog: Catalog to query.
        filters: Dictionary of filter criteria.

    Returns:
        List of Role objects matching filters.
    """
    roles_list = list(catalog.roles.values())

    if not filters:
        return roles_list

    # Apply filters
    if "activity" in filters:
        activity = filters["activity"]
        roles_list = [role for role in roles_list if role.supports_activity(activity)]

    if "provides" in filters:
        service = filters["provides"]
        roles_list = [role for role in roles_list if service in role.provides]

    return roles_list


def query_profiles(catalog: Catalog, filters: dict[str, Any] | None = None) -> list[Profile]:
    """Query profiles by various filters.

    Supported filters:
    - role: Filter by role ID (profile must include this role)
    - multi_device: Filter by multi-device (bool)

    Args:
        catalog: Catalog to query.
        filters: Dictionary of filter criteria.

    Returns:
        List of Profile objects matching filters.
    """
    profiles_list = list(catalog.profiles.values())

    if not filters:
        return profiles_list

    # Apply filters
    if "role" in filters:
        role_id = filters["role"]
        profiles_list = [profile for profile in profiles_list if role_id in profile.roles]

    if "multi_device" in filters:
        multi = filters["multi_device"]
        if multi:
            profiles_list = [profile for profile in profiles_list if profile.is_multi_device()]
        else:
            profiles_list = [profile for profile in profiles_list if not profile.is_multi_device()]

    return profiles_list


def validate_profile_hardware(catalog: Catalog, profile: Profile, hardware_ids: list[str]) -> bool:
    """Validate that hardware list is compatible with profile.

    Checks:
    1. All hardware IDs exist in catalog
    2. Hardware combination is in profile's verified list
    3. Hardware has all required traits (if profile specifies)

    Args:
        catalog: Catalog containing hardware definitions.
        profile: Profile to validate against.
        hardware_ids: List of hardware IDs to validate.

    Returns:
        True if hardware is valid for profile, False otherwise.
    """
    # Check all hardware IDs exist
    for hw_id in hardware_ids:
        if hw_id not in catalog.hardware:
            return False

    # Check if combination is verified
    if not profile.is_verified_combination(hardware_ids):
        return False

    # Check required traits if specified
    if profile.requires_traits:
        hardware_list = [catalog.hardware[hw_id] for hw_id in hardware_ids]
        # At least one hardware must have all required traits
        # (for multi-device profiles, traits apply to the primary device)
        if not any(hw.has_all_traits(profile.requires_traits) for hw in hardware_list):
            return False

    return True
