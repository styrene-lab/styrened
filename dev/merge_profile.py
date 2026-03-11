#!/usr/bin/env python3
"""Merge dev profile overlays into a target core-config.yaml.

Usage:
    python dev/merge_profile.py <profile> <output_path>

Loads dev/profiles/_base.yaml, then deep-merges dev/profiles/<profile>.yaml
on top, writing the result to <output_path>.  Lists are replaced wholesale
(not appended) so peer lists in profiles are authoritative.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not available — run inside the project venv")

PROFILES_DIR = Path(__file__).parent / "profiles"


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay onto base. Lists are replaced, not extended."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} <profile> <output_path>")

    profile_name = sys.argv[1]
    output_path = Path(sys.argv[2])

    base_path = PROFILES_DIR / "_base.yaml"
    profile_path = PROFILES_DIR / f"{profile_name}.yaml"

    if not base_path.exists():
        sys.exit(f"Base profile not found: {base_path}")
    if not profile_path.exists():
        available = [p.stem for p in PROFILES_DIR.glob("*.yaml") if not p.stem.startswith("_")]
        sys.exit(f"Profile '{profile_name}' not found. Available: {', '.join(sorted(available))}")

    base = load_yaml(base_path)
    overlay = load_yaml(profile_path)
    merged = deep_merge(base, overlay)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)

    print(f"✓ Profile '{profile_name}' merged → {output_path}")


if __name__ == "__main__":
    main()
