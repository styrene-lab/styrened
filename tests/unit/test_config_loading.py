"""Unit tests for config loading and _parse_bool() function.

Tests the critical bool() coercion fix that prevents string "false"
from being incorrectly parsed as True.
"""

import tempfile
from pathlib import Path

from styrened.services.config import _parse_bool, load_core_config


class TestParseBool:
    """Tests for _parse_bool() helper function."""

    def test_parse_bool_with_true_bool(self) -> None:
        """Actual True bool should return True."""
        assert _parse_bool(True) is True

    def test_parse_bool_with_false_bool(self) -> None:
        """Actual False bool should return False."""
        assert _parse_bool(False) is False

    def test_parse_bool_with_string_true(self) -> None:
        """String 'true' should return True."""
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("TRUE") is True

    def test_parse_bool_with_string_false(self) -> None:
        """String 'false' should return False (the critical fix)."""
        assert _parse_bool("false") is False
        assert _parse_bool("False") is False
        assert _parse_bool("FALSE") is False

    def test_parse_bool_with_yes_no(self) -> None:
        """String 'yes'/'no' should work correctly."""
        assert _parse_bool("yes") is True
        assert _parse_bool("Yes") is True
        assert _parse_bool("no") is False
        assert _parse_bool("No") is False

    def test_parse_bool_with_one_zero(self) -> None:
        """String '1'/'0' should work correctly."""
        assert _parse_bool("1") is True
        assert _parse_bool("0") is False

    def test_parse_bool_with_on_off(self) -> None:
        """String 'on'/'off' should work correctly."""
        assert _parse_bool("on") is True
        assert _parse_bool("On") is True
        assert _parse_bool("off") is False
        assert _parse_bool("Off") is False

    def test_parse_bool_with_empty_string(self) -> None:
        """Empty string should return False."""
        assert _parse_bool("") is False

    def test_parse_bool_with_integer(self) -> None:
        """Integer values should use Python's bool() behavior."""
        assert _parse_bool(1) is True
        assert _parse_bool(0) is False
        assert _parse_bool(42) is True

    def test_parse_bool_with_none(self) -> None:
        """None should return False."""
        assert _parse_bool(None) is False


class TestLoadConfigBoolHandling:
    """Tests for load_core_config() with string boolean values."""

    def test_load_config_with_string_false_rpc_disabled(self) -> None:
        """Config with string 'false' should correctly disable RPC."""
        yaml_content = """
rpc:
  enabled: "false"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.rpc.enabled is False

    def test_load_config_with_string_true_rpc_enabled(self) -> None:
        """Config with string 'true' should correctly enable RPC."""
        yaml_content = """
rpc:
  enabled: "true"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.rpc.enabled is True

    def test_load_config_with_actual_bool_values(self) -> None:
        """Config with actual YAML booleans should work correctly."""
        yaml_content = """
rpc:
  enabled: true
  relay_mode: false
discovery:
  enabled: true
  auto_announce: false
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.rpc.enabled is True
        assert config.rpc.relay_mode is False
        assert config.discovery.enabled is True
        assert config.discovery.auto_announce is False

    def test_load_config_with_string_no_for_disabled(self) -> None:
        """Config with string 'no' should disable feature."""
        yaml_content = """
chat:
  enabled: "no"
  auto_reply_enabled: "no"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.chat.enabled is False
        assert config.chat.auto_reply_enabled is False

    def test_load_config_with_string_yes_for_enabled(self) -> None:
        """Config with string 'yes' should enable feature."""
        yaml_content = """
api:
  enabled: "yes"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.api.enabled is True

    def test_load_config_preserves_defaults_on_missing(self) -> None:
        """Missing config sections should use defaults."""
        yaml_content = """
# Empty config
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Check defaults are preserved
        assert config.rpc.enabled is True  # Default
        assert config.discovery.enabled is True  # Default
        assert config.chat.auto_reply_enabled is True  # Default

    def test_load_config_with_all_string_bools(self) -> None:
        """Comprehensive test with all boolean fields as strings."""
        yaml_content = """
reticulum:
  enable_transport: "false"
  interfaces:
    auto: "true"
    server:
      enabled: "false"
rpc:
  enabled: "true"
  relay_mode: "false"
  allow_command_execution: "true"
discovery:
  enabled: "true"
  auto_announce: "false"
chat:
  enabled: "true"
  auto_reply_enabled: "false"
api:
  enabled: "false"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.enable_transport is False
        assert config.reticulum.interfaces.auto is True
        assert config.reticulum.interfaces.server.enabled is False
        assert config.rpc.enabled is True
        assert config.rpc.relay_mode is False
        assert config.rpc.allow_command_execution is True
        assert config.discovery.enabled is True
        assert config.discovery.auto_announce is False
        assert config.chat.enabled is True
        assert config.chat.auto_reply_enabled is False
        assert config.api.enabled is False
