"""Unit tests for StyreneDaemon._build_announce_data().

Verifies that announce data uses the real version from __init__.py
and includes the system fingerprint as the 7th field.
"""
from __future__ import annotations


from unittest.mock import patch

import pytest

from styrened import __version__
from styrened.daemon import StyreneDaemon
from styrened.models.config import CoreConfig, ReticulumConfig


@pytest.fixture
def daemon() -> StyreneDaemon:
    """Create a daemon instance with minimal config."""
    config = CoreConfig(reticulum=ReticulumConfig())
    return StyreneDaemon(config)


class TestBuildAnnounceData:
    """Tests for _build_announce_data() method."""

    def test_version_matches_package_version(self, daemon):
        """Announce version must match __version__, not hardcoded '0.1.0'."""
        with patch(
            "styrened.services.system_info.get_system_fingerprint", return_value="test|1.0|x86_64|"
        ):
            data = daemon._build_announce_data()
        decoded = data.decode("utf-8")
        parts = decoded.split(":")
        version = parts[2]
        assert version == __version__
        assert version != "0.1.0"

    def test_announce_has_eight_fields(self, daemon):
        """Announce must have 7 colon-delimited fields (prefix + 6 values)."""
        with patch(
            "styrened.services.system_info.get_system_fingerprint",
            return_value="nixos|24.11|x86_64|zah57xw",
        ):
            data = daemon._build_announce_data()
        decoded = data.decode("utf-8")
        parts = decoded.split(":")
        assert len(parts) == 8, f"Expected 8 fields, got {len(parts)}: {parts}"

    def test_fingerprint_is_7th_field(self, daemon):
        """System fingerprint is the 7th colon-delimited field."""
        with patch(
            "styrened.services.system_info.get_system_fingerprint",
            return_value="nixos|24.11|x86_64|zah57xw",
        ):
            data = daemon._build_announce_data()
        decoded = data.decode("utf-8")
        parts = decoded.split(":")
        assert parts[6] == "nixos|24.11|x86_64|zah57xw"

    def test_starts_with_styrene_prefix(self, daemon):
        """Announce data must start with 'styrene:' prefix."""
        with patch(
            "styrened.services.system_info.get_system_fingerprint", return_value="test|1.0|x86_64|"
        ):
            data = daemon._build_announce_data()
        assert data.startswith(b"styrene:")
