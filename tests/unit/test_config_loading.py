"""Unit tests for config loading and _parse_bool() function.

Tests the critical bool() coercion fix that prevents string "false"
from being incorrectly parsed as True.

Also tests config_path_override parsing for RNS configuration.
"""

import tempfile
from pathlib import Path

from styrened.models.config import AutoReplyMode
from styrened.services.config import _parse_bool, load_core_config, save_core_config


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
  auto_reply_mode: "disabled"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.chat.enabled is False
        assert config.chat.auto_reply_mode == AutoReplyMode.DISABLED

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
        """Missing config sections should use operator profile defaults."""
        yaml_content = """
# Empty config
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Check operator profile defaults are preserved
        assert config.rpc.enabled is True
        assert config.discovery.enabled is True
        assert config.chat.auto_reply_mode == AutoReplyMode.DISABLED  # Operator profile: human is present

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
  auto_reply_mode: "disabled"
  persist_messages: "false"
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
        assert config.chat.auto_reply_mode == AutoReplyMode.DISABLED
        assert config.chat.persist_messages is False
        assert config.api.enabled is False

    def test_load_config_persist_messages_default(self) -> None:
        """Test that persist_messages defaults to True when not specified."""
        yaml_content = """
chat:
  enabled: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.chat.persist_messages is True  # Default value


class TestSaveCoreConfig:
    """Tests for save_core_config() serialization."""

    def test_save_config_roundtrip_preserves_config_path_override(self) -> None:
        """config_path_override should be preserved through save/load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            # Load a config with config_path_override set
            yaml_content = """
reticulum:
  config_path_override: /custom/rns/path
  mode: standalone
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(yaml_content)
                f.flush()
                original = load_core_config(Path(f.name))

            # Save it
            save_core_config(original, config_path)

            # Load it back
            reloaded = load_core_config(config_path)

            assert reloaded.reticulum.config_path_override == Path("/custom/rns/path")

    def test_save_config_without_config_path_override(self) -> None:
        """Config without config_path_override should save without that field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            # Load a config without config_path_override
            yaml_content = """
reticulum:
  mode: standalone
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(yaml_content)
                f.flush()
                original = load_core_config(Path(f.name))

            # Save it
            save_core_config(original, config_path)

            # Load it back - should not have config_path_override
            reloaded = load_core_config(config_path)

            assert reloaded.reticulum.config_path_override is None

    def test_save_config_preserves_mode(self) -> None:
        """Mode should be preserved through save/load cycle."""
        from styrened.models.config import DeploymentMode

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            yaml_content = """
reticulum:
  mode: hub
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(yaml_content)
                f.flush()
                original = load_core_config(Path(f.name))

            save_core_config(original, config_path)
            reloaded = load_core_config(config_path)

            assert reloaded.reticulum.mode == DeploymentMode.HUB


class TestConfigPathOverride:
    """Tests for reticulum.config_path_override parsing."""

    def test_config_path_override_not_set_defaults_to_none(self) -> None:
        """When config_path_override is not set, should default to None."""
        yaml_content = """
reticulum:
  mode: standalone
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None

    def test_config_path_override_with_absolute_path(self) -> None:
        """Absolute path should be parsed correctly."""
        yaml_content = """
reticulum:
  config_path_override: /etc/reticulum
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override == Path("/etc/reticulum")

    def test_config_path_override_with_home_expansion(self) -> None:
        """Tilde path should be expanded to home directory."""
        yaml_content = """
reticulum:
  config_path_override: ~/.config/reticulum
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        expected = Path.home() / ".config" / "reticulum"
        assert config.reticulum.config_path_override == expected

    def test_config_path_override_with_legacy_path(self) -> None:
        """Legacy ~/.reticulum path should work."""
        yaml_content = """
reticulum:
  config_path_override: ~/.reticulum
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        expected = Path.home() / ".reticulum"
        assert config.reticulum.config_path_override == expected

    def test_config_path_override_null_string_becomes_none(self) -> None:
        """String 'null' should be treated as None."""
        yaml_content = """
reticulum:
  config_path_override: "null"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None

    def test_config_path_override_yaml_null_becomes_none(self) -> None:
        """YAML null should result in None."""
        yaml_content = """
reticulum:
  config_path_override: null
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None

    def test_config_path_override_empty_string_becomes_none(self) -> None:
        """Empty string should be treated as None."""
        yaml_content = """
reticulum:
  config_path_override: ""
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None

    def test_config_path_override_with_relative_path(self) -> None:
        """Relative path should be preserved (not recommended but allowed)."""
        yaml_content = """
reticulum:
  config_path_override: ./local-reticulum
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override == Path("./local-reticulum")

    def test_config_path_override_whitespace_only_becomes_none(self) -> None:
        """Whitespace-only string should be treated as None."""
        yaml_content = """
reticulum:
  config_path_override: "   "
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None

    def test_config_path_override_integer_ignored_gracefully(self) -> None:
        """Integer value should be ignored with warning, resulting in None."""
        yaml_content = """
reticulum:
  config_path_override: 0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Should not crash, should result in None
        assert config.reticulum.config_path_override is None

    def test_config_path_override_float_ignored_gracefully(self) -> None:
        """Float value should be ignored with warning, resulting in None."""
        yaml_content = """
reticulum:
  config_path_override: 3.14
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Should not crash, should result in None
        assert config.reticulum.config_path_override is None

    def test_config_path_override_null_with_padding_becomes_none(self) -> None:
        """String ' null ' with whitespace should be treated as None."""
        yaml_content = """
reticulum:
  config_path_override: " null "
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.reticulum.config_path_override is None


class TestLXMFConfigLoading:
    """Tests for LXMF configuration loading."""

    def test_lxmf_config_defaults(self) -> None:
        """LXMF config should have sensible defaults when not specified."""
        yaml_content = """
reticulum:
  mode: standalone
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Check defaults
        assert config.lxmf.autopeer is True
        assert config.lxmf.autopeer_maxdepth == 4
        assert config.lxmf.max_peers == 20
        assert config.lxmf.propagation_limit == 256
        assert config.lxmf.sync_limit == 10240
        assert config.lxmf.delivery_limit == 1000
        assert config.lxmf.propagation_node.enabled is False
        assert config.lxmf.propagation_node.name is None
        assert config.lxmf.propagation_destination is None
        assert config.lxmf.static_peers == []
        assert config.lxmf.from_static_only is False

    def test_lxmf_propagation_node_enabled(self) -> None:
        """Propagation node can be enabled via config."""
        yaml_content = """
lxmf:
  propagation_node:
    enabled: true
    name: "Central Hub"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_node.enabled is True
        assert config.lxmf.propagation_node.name == "Central Hub"

    def test_lxmf_propagation_destination(self) -> None:
        """Propagation destination hash is parsed correctly."""
        yaml_content = """
lxmf:
  propagation_destination: "abcdef0123456789abcdef0123456789"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_destination == "abcdef0123456789abcdef0123456789"

    def test_lxmf_propagation_destination_invalid_length_ignored(self) -> None:
        """Invalid length propagation destination is ignored."""
        yaml_content = """
lxmf:
  propagation_destination: "tooshort"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_destination is None

    def test_lxmf_sync_limits(self) -> None:
        """Sync limits are parsed correctly."""
        yaml_content = """
lxmf:
  propagation_limit: 512
  sync_limit: 20480
  delivery_limit: 2000
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_limit == 512
        assert config.lxmf.sync_limit == 20480
        assert config.lxmf.delivery_limit == 2000

    def test_lxmf_peer_management(self) -> None:
        """Peer management settings are parsed correctly."""
        yaml_content = """
lxmf:
  autopeer: false
  autopeer_maxdepth: 8
  max_peers: 50
  from_static_only: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.autopeer is False
        assert config.lxmf.autopeer_maxdepth == 8
        assert config.lxmf.max_peers == 50
        assert config.lxmf.from_static_only is True

    def test_lxmf_static_peers(self) -> None:
        """Static peers list is parsed correctly."""
        yaml_content = """
lxmf:
  static_peers:
    - "abcdef0123456789abcdef0123456789"
    - "fedcba9876543210fedcba9876543210"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert len(config.lxmf.static_peers) == 2
        assert "abcdef0123456789abcdef0123456789" in config.lxmf.static_peers
        assert "fedcba9876543210fedcba9876543210" in config.lxmf.static_peers

    def test_lxmf_static_peers_invalid_length_filtered(self) -> None:
        """Invalid length static peers are filtered out."""
        yaml_content = """
lxmf:
  static_peers:
    - "abcdef0123456789abcdef0123456789"
    - "tooshort"
    - "fedcba9876543210fedcba9876543210"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        # Only valid 32-char hashes should be included
        assert len(config.lxmf.static_peers) == 2
        assert "tooshort" not in config.lxmf.static_peers

    def test_lxmf_cost_settings(self) -> None:
        """Cost settings are parsed correctly."""
        yaml_content = """
lxmf:
  propagation_cost: 32
  propagation_cost_flexibility: 5
  peering_cost: 24
  max_peering_cost: 48
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_cost == 32
        assert config.lxmf.propagation_cost_flexibility == 5
        assert config.lxmf.peering_cost == 24
        assert config.lxmf.max_peering_cost == 48

    def test_lxmf_full_config(self) -> None:
        """Full LXMF configuration is parsed correctly."""
        yaml_content = """
lxmf:
  propagation_node:
    enabled: true
    name: "Test Hub"
  propagation_destination: "1234567890abcdef1234567890abcdef"
  propagation_limit: 512
  sync_limit: 20480
  delivery_limit: 2000
  autopeer: true
  autopeer_maxdepth: 6
  max_peers: 30
  static_peers:
    - "abcdef0123456789abcdef0123456789"
  from_static_only: false
  propagation_cost: 20
  propagation_cost_flexibility: 4
  peering_cost: 22
  max_peering_cost: 30
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.lxmf.propagation_node.enabled is True
        assert config.lxmf.propagation_node.name == "Test Hub"
        assert config.lxmf.propagation_destination == "1234567890abcdef1234567890abcdef"
        assert config.lxmf.propagation_limit == 512
        assert config.lxmf.sync_limit == 20480
        assert config.lxmf.delivery_limit == 2000
        assert config.lxmf.autopeer is True
        assert config.lxmf.autopeer_maxdepth == 6
        assert config.lxmf.max_peers == 30
        assert len(config.lxmf.static_peers) == 1
        assert config.lxmf.from_static_only is False
        assert config.lxmf.propagation_cost == 20
        assert config.lxmf.propagation_cost_flexibility == 4
        assert config.lxmf.peering_cost == 22
        assert config.lxmf.max_peering_cost == 30


class TestYubiKeyConfigParsing:
    """Tests for YubiKey identity provider configuration parsing."""

    def test_provider_defaults_to_file(self) -> None:
        """Identity provider should default to 'file' when not specified."""
        yaml_content = """
identity:
  display_name: "Test Node"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "file"

    def test_provider_set_to_yubikey(self) -> None:
        """Identity provider can be set to 'yubikey'."""
        yaml_content = """
identity:
  provider: "yubikey"
  display_name: "Secure Operator"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "yubikey"
        assert config.identity.display_name == "Secure Operator"

    def test_yubikey_section_parsed(self) -> None:
        """YubiKey section should be parsed with all fields."""
        yaml_content = """
identity:
  provider: "yubikey"
  yubikey:
    credential_id: "SGVsbG8gV29ybGQ="
    rp_id: "custom.mesh"
    require_touch: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "yubikey"
        assert config.identity.yubikey.credential_id == "SGVsbG8gV29ybGQ="
        assert config.identity.yubikey.rp_id == "custom.mesh"
        assert config.identity.yubikey.require_touch is True

    def test_yubikey_section_defaults(self) -> None:
        """YubiKey section should have sensible defaults."""
        yaml_content = """
identity:
  provider: "yubikey"
  yubikey:
    credential_id: "dGVzdA=="
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.yubikey.rp_id == "styrene.mesh"
        assert config.identity.yubikey.require_touch is False

    def test_unknown_provider_warns_and_falls_back(self) -> None:
        """Unknown provider should warn and fall back to 'file'."""
        yaml_content = """
identity:
  provider: "smartcard"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "file"

    def test_no_identity_section_preserves_defaults(self) -> None:
        """Missing identity section should preserve all defaults."""
        yaml_content = """
reticulum:
  mode: standalone
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "file"
        assert config.identity.yubikey.credential_id == ""
        assert config.identity.yubikey.rp_id == "styrene.mesh"

    def test_provider_case_insensitive(self) -> None:
        """Provider field should be case-insensitive."""
        yaml_content = """
identity:
  provider: "YubiKey"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.identity.provider == "yubikey"


class TestWebAuthConfigLoading:
    """Tests for api.auth config section loading."""

    def test_auth_defaults_when_missing(self) -> None:
        """Missing auth section uses defaults."""
        yaml_content = """
api:
  enabled: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.api.auth.enabled is False
        assert config.api.auth.exempt_localhost is True
        assert config.api.auth.session_ttl == 86400
        assert config.api.auth.allow_unauthenticated is False
        assert config.api.auth.authorized_identities == set()

    def test_auth_full_config(self) -> None:
        """Full auth config is parsed correctly."""
        yaml_content = """
api:
  enabled: true
  auth:
    enabled: true
    exempt_localhost: false
    allow_unauthenticated: true
    session_ttl: 3600
    authorized_identities:
      - "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      - "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.api.auth.enabled is True
        assert config.api.auth.exempt_localhost is False
        assert config.api.auth.allow_unauthenticated is True
        assert config.api.auth.session_ttl == 3600
        assert config.api.auth.authorized_identities == {
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        }

    def test_auth_invalid_identity_length_filtered(self) -> None:
        """Identities with wrong length are filtered out."""
        yaml_content = """
api:
  auth:
    authorized_identities:
      - "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      - "tooshort"
      - "123"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.api.auth.authorized_identities == {
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }

    def test_auth_string_bools(self) -> None:
        """Auth bools handle string representations."""
        yaml_content = """
api:
  auth:
    enabled: "true"
    exempt_localhost: "false"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_core_config(Path(f.name))

        assert config.api.auth.enabled is True
        assert config.api.auth.exempt_localhost is False


class TestPQCConfigLoading:
    """Tests for PQC configuration loading."""

    def test_pqc_config_defaults(self) -> None:
        """Default PQCConfig values are correct."""
        from styrened.models.config import PQCConfig

        pqc = PQCConfig()
        assert pqc.enabled is True
        assert pqc.rekey_interval_hours == 24
        assert pqc.require_pqc_for_rpc is False
        assert pqc.auto_initiate is True

    def test_pqc_config_in_core_config(self) -> None:
        """CoreConfig has PQC section with defaults."""
        from styrened.models.config import CoreConfig

        config = CoreConfig()
        assert config.pqc.enabled is True
        assert config.pqc.rekey_interval_hours == 24

    def test_pqc_config_from_yaml(self, tmp_path: Path) -> None:
        """PQC config round-trips through YAML correctly."""
        from styrened.models.config import CoreConfig, PQCConfig

        config = CoreConfig()
        config.pqc = PQCConfig(
            enabled=False,
            rekey_interval_hours=12,
            require_pqc_for_rpc=True,
            auto_initiate=False,
        )

        config_file = tmp_path / "config.yaml"
        save_core_config(config, config_file)
        loaded = load_core_config(config_file)

        assert loaded.pqc.enabled is False
        assert loaded.pqc.rekey_interval_hours == 12
        assert loaded.pqc.require_pqc_for_rpc is True
        assert loaded.pqc.auto_initiate is False

    def test_pqc_config_missing_uses_defaults(self, tmp_path: Path) -> None:
        """Missing pqc section uses defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("profile: operator\n")
        loaded = load_core_config(config_file)
        assert loaded.pqc.enabled is True
        assert loaded.pqc.rekey_interval_hours == 24

    def test_pqc_rekey_interval_string_value_falls_back_to_default(
        self, tmp_path: Path
    ) -> None:
        """W12: Non-numeric rekey_interval_hours falls back to 24."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "pqc:\n  rekey_interval_hours: 'not_a_number'\n"
        )
        loaded = load_core_config(config_file)
        assert loaded.pqc.rekey_interval_hours == 24

    def test_pqc_rekey_interval_none_value_falls_back_to_default(
        self, tmp_path: Path
    ) -> None:
        """W12: null rekey_interval_hours falls back to 24."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("pqc:\n  rekey_interval_hours: null\n")
        loaded = load_core_config(config_file)
        # null resolves to None in YAML, int(None) raises TypeError
        assert loaded.pqc.rekey_interval_hours == 24

    def test_pqc_rekey_interval_valid_int_preserved(
        self, tmp_path: Path
    ) -> None:
        """W12: Valid integer rekey_interval_hours is preserved."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("pqc:\n  rekey_interval_hours: 48\n")
        loaded = load_core_config(config_file)
        assert loaded.pqc.rekey_interval_hours == 48

    def test_pqc_rekey_interval_float_string_falls_back_to_default(
        self, tmp_path: Path
    ) -> None:
        """W12: Float-string rekey_interval_hours falls back to 24."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "pqc:\n  rekey_interval_hours: '3.14'\n"
        )
        loaded = load_core_config(config_file)
        assert loaded.pqc.rekey_interval_hours == 24


class TestAuthorizedIdentitiesHexValidation:
    """Tests for hex validation of api.auth.authorized_identities (W11)."""

    def test_valid_hex_identity_accepted(self, tmp_path: Path) -> None:
        """A valid 32-char hex identity is accepted."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
api:
  auth:
    authorized_identities:
      - "aabbccdd11223344aabbccdd11223344"
""")
        config = load_core_config(config_file)
        assert "aabbccdd11223344aabbccdd11223344" in config.api.auth.authorized_identities

    def test_non_hex_identity_rejected(self, tmp_path: Path) -> None:
        """A 32-char string with non-hex characters is rejected (W11)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
api:
  auth:
    authorized_identities:
      - "zzzzzzzz11223344aabbccdd11223344"
""")
        config = load_core_config(config_file)
        assert len(config.api.auth.authorized_identities) == 0

    def test_mixed_valid_invalid_identities(self, tmp_path: Path) -> None:
        """Only valid hex identities are kept; non-hex are filtered out (W11)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
api:
  auth:
    authorized_identities:
      - "aabbccdd11223344aabbccdd11223344"
      - "not_valid_hex_but_len_is_32char"
      - "1234567890abcdef1234567890abcdef"
""")
        config = load_core_config(config_file)
        assert "aabbccdd11223344aabbccdd11223344" in config.api.auth.authorized_identities
        assert "1234567890abcdef1234567890abcdef" in config.api.auth.authorized_identities
        assert len(config.api.auth.authorized_identities) == 2

    def test_uppercase_hex_identity_accepted(self, tmp_path: Path) -> None:
        """Uppercase hex characters are accepted (W11)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
api:
  auth:
    authorized_identities:
      - "AABBCCDD11223344AABBCCDD11223344"
""")
        config = load_core_config(config_file)
        assert "AABBCCDD11223344AABBCCDD11223344" in config.api.auth.authorized_identities
