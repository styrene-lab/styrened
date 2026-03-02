"""Tests for identity migration from legacy config.yaml to core-config.yaml.

The TUI config (config.yaml) historically held identity settings. After the
_overlay_core_config() change, core-config.yaml is the source of truth.
These tests verify that identity migrates correctly from legacy config and
that _parse_config_dict reads identity from config.yaml.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from styrened.models.config import CoreConfig, IdentityConfig
from styrened.tui.models.config import StyreneConfig
from styrened.tui.services.config import _parse_config_dict


class TestParseIdentityFromLegacyConfig:
    """_parse_config_dict should read identity from config.yaml."""

    def test_parses_identity_display_name(self):
        data = {"identity": {"display_name": "Operator One", "icon": "🛰️", "provider": "file"}}
        config = _parse_config_dict(data)
        assert config.core.identity.display_name == "Operator One"
        assert config.core.identity.icon == "🛰️"

    def test_empty_display_name_keeps_default(self):
        data = {"identity": {"display_name": "", "icon": "🔗"}}
        config = _parse_config_dict(data)
        # Empty string should not override default
        assert config.core.identity.display_name == "Anonymous Styrene"

    def test_parses_identity_short_name(self):
        data = {"identity": {"display_name": "Op", "short_name": "op-one"}}
        config = _parse_config_dict(data)
        assert config.core.identity.short_name == "op-one"

    def test_no_identity_section_keeps_default(self):
        data = {"tui": {"theme": "dark"}}
        config = _parse_config_dict(data)
        assert config.core.identity.display_name == "Anonymous Styrene"

    def test_parses_lxmf_propagation_destination(self):
        data = {"lxmf": {"propagation_destination": "abcd1234" * 4}}
        config = _parse_config_dict(data)
        assert config.core.identity.display_name == "Anonymous Styrene"  # untouched
        assert config.core.lxmf.propagation_destination == "abcd1234" * 4


class TestOverlayCoreConfigIdentityMigration:
    """_overlay_core_config should preserve legacy identity when core has defaults."""

    def test_migrates_legacy_identity_to_core(self, tmp_path):
        """If legacy config has real identity but core-config.yaml doesn't, migrate."""
        from styrened.tui.services.config import _overlay_core_config

        config = StyreneConfig()
        config.core.identity.display_name = "Legacy Operator"
        config.core.identity.icon = "🛰️"

        # Mock load_core_config to return default (no identity section)
        default_core = CoreConfig()
        assert default_core.identity.display_name == "Anonymous Styrene"

        saved_configs = []

        def mock_save(cfg, **kw):
            saved_configs.append(cfg)

        with (
            patch("styrened.services.config.load_core_config", return_value=default_core),
            patch("styrened.services.config.save_core_config", mock_save),
        ):
            _overlay_core_config(config)

        # Identity should be preserved from legacy
        assert config.core.identity.display_name == "Legacy Operator"
        assert config.core.identity.icon == "🛰️"
        # Should have persisted migration
        assert len(saved_configs) == 1
        assert saved_configs[0].identity.display_name == "Legacy Operator"

    def test_core_identity_wins_over_legacy(self):
        """If core-config.yaml has a real identity, it takes precedence."""
        from styrened.tui.services.config import _overlay_core_config

        config = StyreneConfig()
        config.core.identity.display_name = "Legacy Name"

        core = CoreConfig()
        core.identity.display_name = "Core Name"

        with patch("styrened.services.config.load_core_config", return_value=core):
            _overlay_core_config(config)

        assert config.core.identity.display_name == "Core Name"

    def test_both_default_stays_default(self):
        """If neither has identity, stays Anonymous Styrene."""
        from styrened.tui.services.config import _overlay_core_config

        config = StyreneConfig()
        core = CoreConfig()

        with patch("styrened.services.config.load_core_config", return_value=core):
            _overlay_core_config(config)

        assert config.core.identity.display_name == "Anonymous Styrene"
