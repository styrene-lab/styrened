"""Tests for service profile defaults.

Validates that operator, endpoint, and hub profiles produce correct service
defaults, that YAML loading respects profiles, and that explicit overrides
take precedence over profile defaults.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from styrened.models.config import CoreConfig, DeploymentMode, Profile
from styrened.services.config import (
    _parse_bool,
    _serialize_config,
    get_profile_defaults,
    load_core_config,
    save_core_config,
    validate_core_config,
)


class TestOperatorProfileDefaults:
    """Operator profile should be human-facing with safe defaults."""

    def test_operator_profile_is_set(self) -> None:
        """Profile field is set to OPERATOR."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.profile == Profile.OPERATOR

    def test_operator_rpc_enabled(self) -> None:
        """RPC enabled for LXMF init."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.rpc.enabled is True

    def test_operator_command_execution_disabled(self) -> None:
        """Operator sends commands, should not be remotely commanded."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.rpc.allow_command_execution is False

    def test_operator_chat_enabled_no_auto_reply(self) -> None:
        """Human reads/sends messages, no auto-reply needed."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.chat.enabled is True
        assert config.chat.auto_reply_enabled is False

    def test_operator_discovery_enabled(self) -> None:
        """Operator tracks fleet."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.discovery.enabled is True
        assert config.discovery.auto_announce is True

    def test_operator_ipc_enabled(self) -> None:
        """TUI access for operator."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.ipc.enabled is True

    def test_operator_terminal_disabled(self) -> None:
        """Operator should not accept inbound shells."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.terminal.enabled is False

    def test_operator_notifications_enabled(self) -> None:
        """Alerts the operator."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.notifications.enabled is True

    def test_operator_announce_interval(self) -> None:
        """Standard 5-minute presence."""
        config = get_profile_defaults(Profile.OPERATOR)
        assert config.reticulum.announce_interval == 300


class TestEndpointProfileDefaults:
    """Endpoint profile should be machine-facing, receive-oriented."""

    def test_endpoint_profile_is_set(self) -> None:
        """Profile field is set to ENDPOINT."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.profile == Profile.ENDPOINT

    def test_endpoint_rpc_enabled_with_exec(self) -> None:
        """Accepts commands — its purpose."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.rpc.enabled is True
        assert config.rpc.allow_command_execution is True

    def test_endpoint_chat_enabled_with_auto_reply(self) -> None:
        """Receives messages, auto-replies when unattended."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.chat.enabled is True
        assert config.chat.auto_reply_enabled is True

    def test_endpoint_discovery_enabled(self) -> None:
        """Must be discoverable."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.discovery.enabled is True
        assert config.discovery.auto_announce is True

    def test_endpoint_api_disabled(self) -> None:
        """No human looking at dashboard."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.api.enabled is False

    def test_endpoint_ipc_disabled(self) -> None:
        """No TUI operator."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.ipc.enabled is False

    def test_endpoint_terminal_enabled(self) -> None:
        """Remote shell for management."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.terminal.enabled is True

    def test_endpoint_notifications_disabled(self) -> None:
        """No human to notify."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.notifications.enabled is False

    def test_endpoint_announce_interval(self) -> None:
        """Less chatter, 10-minute interval."""
        config = get_profile_defaults(Profile.ENDPOINT)
        assert config.reticulum.announce_interval == 600


class TestProfileFromYAML:
    """Loading config with profile key applies correct defaults."""

    def test_profile_endpoint_from_yaml(self, tmp_path: Path) -> None:
        """Loading config with profile: endpoint applies endpoint defaults."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("profile: endpoint\n")

        config = load_core_config(config_path)
        assert config.profile == Profile.ENDPOINT
        assert config.rpc.allow_command_execution is True
        assert config.terminal.enabled is True
        assert config.ipc.enabled is False
        assert config.chat.auto_reply_enabled is True
        assert config.reticulum.announce_interval == 600

    def test_profile_operator_from_yaml(self, tmp_path: Path) -> None:
        """Loading config with profile: operator applies operator defaults."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("profile: operator\n")

        config = load_core_config(config_path)
        assert config.profile == Profile.OPERATOR
        assert config.rpc.allow_command_execution is False
        assert config.terminal.enabled is False
        assert config.ipc.enabled is True
        assert config.chat.auto_reply_enabled is False
        assert config.reticulum.announce_interval == 300


class TestProfileOverride:
    """Explicit YAML values override profile defaults."""

    def test_endpoint_with_ipc_enabled(self, tmp_path: Path) -> None:
        """Endpoint profile but IPC explicitly enabled in YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "endpoint",
            "ipc": {"enabled": True},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.ENDPOINT
        assert config.ipc.enabled is True  # Override wins

    def test_operator_with_command_execution_enabled(self, tmp_path: Path) -> None:
        """Operator profile but command execution explicitly enabled."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "operator",
            "rpc": {"allow_command_execution": True},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.OPERATOR
        assert config.rpc.allow_command_execution is True  # Override wins

    def test_endpoint_with_notifications_enabled(self, tmp_path: Path) -> None:
        """Endpoint profile but notifications explicitly enabled."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "endpoint",
            "notifications": {"enabled": True},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.ENDPOINT
        assert config.notifications.enabled is True  # Override wins

    def test_endpoint_with_custom_announce_interval(self, tmp_path: Path) -> None:
        """Endpoint profile but custom announce interval in YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "endpoint",
            "reticulum": {"announce_interval": 120},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.ENDPOINT
        assert config.reticulum.announce_interval == 120  # Override wins


class TestProfileBackwardCompat:
    """Backward compatibility when profile key is absent."""

    def test_missing_profile_defaults_to_operator(self, tmp_path: Path) -> None:
        """Config without profile key defaults to operator."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "rpc": {"enabled": True},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.OPERATOR

    def test_invalid_profile_keeps_operator(self, tmp_path: Path) -> None:
        """Invalid profile value falls back to operator."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "invalid_profile",
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.OPERATOR

    def test_no_config_file_returns_operator(self, tmp_path: Path) -> None:
        """Missing config file returns operator defaults."""
        config_path = tmp_path / "nonexistent.yaml"
        config = load_core_config(config_path)
        assert config.profile == Profile.OPERATOR


class TestProfileRoundTrip:
    """Serialize/deserialize preserves profile."""

    def test_operator_round_trip(self, tmp_path: Path) -> None:
        """Operator profile survives save → load."""
        config = get_profile_defaults(Profile.OPERATOR)
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.profile == Profile.OPERATOR
        assert loaded.rpc.allow_command_execution is False
        assert loaded.terminal.enabled is False

    def test_endpoint_round_trip(self, tmp_path: Path) -> None:
        """Endpoint profile survives save → load."""
        config = get_profile_defaults(Profile.ENDPOINT)
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.profile == Profile.ENDPOINT
        assert loaded.rpc.allow_command_execution is True
        assert loaded.terminal.enabled is True
        assert loaded.ipc.enabled is False
        assert loaded.reticulum.announce_interval == 600

    def test_profile_in_serialized_output(self) -> None:
        """Profile appears in serialized dict."""
        config = get_profile_defaults(Profile.ENDPOINT)
        output = _serialize_config(config)
        assert output["profile"] == "endpoint"

    def test_operator_profile_in_serialized_output(self) -> None:
        """Operator profile appears in serialized dict."""
        config = get_profile_defaults(Profile.OPERATOR)
        output = _serialize_config(config)
        assert output["profile"] == "operator"


class TestHubProfileDefaults:
    """Hub profile should be public infrastructure with read-only web dashboard."""

    def test_hub_profile_is_set(self) -> None:
        """Profile field is set to HUB."""
        config = get_profile_defaults(Profile.HUB)
        assert config.profile == Profile.HUB

    def test_hub_mode_is_hub(self) -> None:
        """Hub profile uses HUB deployment mode."""
        config = get_profile_defaults(Profile.HUB)
        assert config.reticulum.mode == DeploymentMode.HUB

    def test_hub_transport_enabled(self) -> None:
        """Hub acts as transport node."""
        config = get_profile_defaults(Profile.HUB)
        assert config.reticulum.enable_transport is True

    def test_hub_api_enabled_with_public_mode(self) -> None:
        """Hub enables web UI in read-only mode."""
        config = get_profile_defaults(Profile.HUB)
        assert config.api.enabled is True
        assert config.api.public_mode is True

    def test_hub_rpc_relay_no_exec(self) -> None:
        """Hub relays RPC but does not execute commands."""
        config = get_profile_defaults(Profile.HUB)
        assert config.rpc.enabled is True
        assert config.rpc.relay_mode is True
        assert config.rpc.allow_command_execution is False

    def test_hub_chat_auto_reply_with_long_cooldown(self) -> None:
        """Hub auto-replies with 10-minute cooldown."""
        config = get_profile_defaults(Profile.HUB)
        assert config.chat.enabled is True
        assert config.chat.auto_reply_enabled is True
        assert config.chat.auto_reply_cooldown == 600

    def test_hub_ipc_disabled(self) -> None:
        """No local TUI on a hub."""
        config = get_profile_defaults(Profile.HUB)
        assert config.ipc.enabled is False

    def test_hub_terminal_disabled(self) -> None:
        """No inbound shell sessions on a hub."""
        config = get_profile_defaults(Profile.HUB)
        assert config.terminal.enabled is False

    def test_hub_announce_interval(self) -> None:
        """Hub announces hourly — it's not going anywhere."""
        config = get_profile_defaults(Profile.HUB)
        assert config.reticulum.announce_interval == 3600

    def test_hub_propagation_node_enabled(self) -> None:
        """Hub acts as LXMF propagation node."""
        config = get_profile_defaults(Profile.HUB)
        assert config.lxmf.propagation_node.enabled is True


class TestHubProfileFromYAML:
    """Loading config with profile: hub applies correct defaults."""

    def test_profile_hub_from_yaml(self, tmp_path: Path) -> None:
        """Loading config with profile: hub applies hub defaults."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("profile: hub\n")

        config = load_core_config(config_path)
        assert config.profile == Profile.HUB
        assert config.reticulum.mode == DeploymentMode.HUB
        assert config.api.enabled is True
        assert config.api.public_mode is True
        assert config.rpc.relay_mode is True
        assert config.rpc.allow_command_execution is False
        assert config.ipc.enabled is False
        assert config.terminal.enabled is False

    def test_hub_with_public_mode_override_false(self, tmp_path: Path) -> None:
        """YAML override disables public_mode even on hub profile."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "hub",
            "api": {"public_mode": False},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.HUB
        assert config.api.public_mode is False  # Override wins

    def test_hub_round_trip(self, tmp_path: Path) -> None:
        """Hub profile survives save → load."""
        config = get_profile_defaults(Profile.HUB)
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.profile == Profile.HUB
        assert loaded.reticulum.mode == DeploymentMode.HUB
        assert loaded.api.enabled is True
        assert loaded.api.public_mode is True
        assert loaded.rpc.relay_mode is True
        assert loaded.ipc.enabled is False
        assert loaded.lxmf.propagation_node.enabled is True

    def test_hub_profile_in_serialized_output(self) -> None:
        """Hub profile appears in serialized dict."""
        config = get_profile_defaults(Profile.HUB)
        output = _serialize_config(config)
        assert output["profile"] == "hub"


class TestPublicModeConfig:
    """Tests for api.public_mode field in config serialization."""

    def test_public_mode_in_serialized_output(self) -> None:
        """public_mode appears in serialized API section."""
        config = get_profile_defaults(Profile.OPERATOR)
        output = _serialize_config(config)
        assert "public_mode" in output["api"]
        assert output["api"]["public_mode"] is False

    def test_public_mode_round_trip(self, tmp_path: Path) -> None:
        """public_mode survives save → load cycle."""
        config = get_profile_defaults(Profile.OPERATOR)
        config.api.public_mode = True
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.api.public_mode is True


class TestPublicModeEdgeCases:
    """Adversarial tests for public_mode parsing through _parse_bool and YAML loading."""

    # ---------------------------------------------------------------
    # 1. Truthy coercion: non-standard boolean representations in YAML
    # ---------------------------------------------------------------

    def test_parse_bool_string_yes(self) -> None:
        """_parse_bool handles 'yes' as True."""
        assert _parse_bool("yes") is True

    def test_parse_bool_string_YES_case_insensitive(self) -> None:
        """_parse_bool handles 'YES' case-insensitively."""
        assert _parse_bool("YES") is True

    def test_parse_bool_string_true_lowercase(self) -> None:
        """_parse_bool handles the string 'true' (not bool True) as True."""
        assert _parse_bool("true") is True

    def test_parse_bool_string_True_mixed_case(self) -> None:
        """_parse_bool handles 'True' (mixed case string) as True."""
        assert _parse_bool("True") is True

    def test_parse_bool_integer_1(self) -> None:
        """_parse_bool handles integer 1 as True via bool(1)."""
        assert _parse_bool(1) is True

    def test_parse_bool_integer_0(self) -> None:
        """_parse_bool handles integer 0 as False via bool(0)."""
        assert _parse_bool(0) is False

    def test_parse_bool_string_on(self) -> None:
        """_parse_bool handles 'on' as True."""
        assert _parse_bool("on") is True

    def test_parse_bool_string_off(self) -> None:
        """_parse_bool handles 'off' as False (not in truthy set)."""
        assert _parse_bool("off") is False

    def test_parse_bool_string_no(self) -> None:
        """_parse_bool handles 'no' as False (not in truthy set)."""
        assert _parse_bool("no") is False

    def test_parse_bool_string_false(self) -> None:
        """_parse_bool handles string 'false' as False."""
        assert _parse_bool("false") is False

    def test_parse_bool_empty_string(self) -> None:
        """_parse_bool handles empty string as False (not in truthy set)."""
        assert _parse_bool("") is False

    def test_public_mode_yaml_string_yes(self, tmp_path: Path) -> None:
        """public_mode: 'yes' in YAML is parsed as True."""
        config_path = tmp_path / "config.yaml"
        # Write raw YAML to avoid Python bool coercion by yaml.dump
        config_path.write_text("api:\n  public_mode: 'yes'\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is True

    def test_public_mode_yaml_integer_1(self, tmp_path: Path) -> None:
        """public_mode: 1 in YAML is parsed as True."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("api:\n  public_mode: 1\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is True

    def test_public_mode_yaml_string_true_quoted(self, tmp_path: Path) -> None:
        """public_mode: 'true' (quoted string in YAML) is parsed as True."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("api:\n  public_mode: 'true'\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is True

    def test_public_mode_yaml_integer_0(self, tmp_path: Path) -> None:
        """public_mode: 0 in YAML is parsed as False."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("api:\n  public_mode: 0\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is False

    # ---------------------------------------------------------------
    # 4. public_mode: null in YAML -- should become False
    # ---------------------------------------------------------------

    def test_parse_bool_none(self) -> None:
        """_parse_bool(None) returns False via bool(None)."""
        assert _parse_bool(None) is False

    def test_public_mode_yaml_null(self, tmp_path: Path) -> None:
        """public_mode: null in YAML becomes False (None -> bool(None) -> False)."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("api:\n  public_mode: null\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is False

    def test_public_mode_yaml_tilde_null(self, tmp_path: Path) -> None:
        """public_mode: ~ in YAML (YAML null shorthand) becomes False."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("api:\n  public_mode: ~\n")

        config = load_core_config(config_path)
        assert config.api.public_mode is False

    # ---------------------------------------------------------------
    # 5. Profile round-trip with overrides
    # ---------------------------------------------------------------

    def test_hub_profile_public_mode_override_false_round_trip(self, tmp_path: Path) -> None:
        """Hub profile with public_mode overridden to False survives save/load.

        The round-trip must preserve both profile=hub AND public_mode=False,
        even though hub defaults set public_mode=True.
        """
        # Build hub config, override public_mode to False
        config = get_profile_defaults(Profile.HUB)
        config.api.public_mode = False
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.profile == Profile.HUB
        assert loaded.api.public_mode is False  # Override preserved
        assert loaded.api.enabled is True  # Hub default preserved

    def test_hub_profile_public_mode_override_false_serialized(self) -> None:
        """Serialized hub config with public_mode=False emits both profile and override."""
        config = get_profile_defaults(Profile.HUB)
        config.api.public_mode = False
        output = _serialize_config(config)

        assert output["profile"] == "hub"
        assert output["api"]["public_mode"] is False

    # ---------------------------------------------------------------
    # Additional _parse_bool edge cases
    # ---------------------------------------------------------------

    def test_parse_bool_float_nonzero(self) -> None:
        """_parse_bool with a non-zero float returns True via bool()."""
        assert _parse_bool(0.5) is True

    def test_parse_bool_float_zero(self) -> None:
        """_parse_bool with 0.0 returns False via bool()."""
        assert _parse_bool(0.0) is False

    def test_parse_bool_nonempty_list(self) -> None:
        """_parse_bool with a non-empty list returns True via bool()."""
        assert _parse_bool([1]) is True

    def test_parse_bool_empty_list(self) -> None:
        """_parse_bool with an empty list returns False via bool()."""
        assert _parse_bool([]) is False

    def test_parse_bool_actual_bool_true(self) -> None:
        """_parse_bool with actual True returns True (fast path, no coercion)."""
        result = _parse_bool(True)
        assert result is True
        assert isinstance(result, bool)

    def test_parse_bool_actual_bool_false(self) -> None:
        """_parse_bool with actual False returns False (fast path)."""
        result = _parse_bool(False)
        assert result is False
        assert isinstance(result, bool)


class TestHubProfileEdgeCases:
    """Adversarial tests for hub profile defaults, overrides, and validation."""

    # ---------------------------------------------------------------
    # 2. Hub profile + mode override conflict
    # ---------------------------------------------------------------

    def test_hub_profile_mode_override_standalone(self, tmp_path: Path) -> None:
        """Hub profile with explicit mode: standalone -- YAML override wins.

        Profile sets mode=hub, but explicit YAML reticulum.mode=standalone
        should override the profile default.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "hub",
            "reticulum": {"mode": "standalone"},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.HUB
        assert config.reticulum.mode == DeploymentMode.STANDALONE  # YAML wins

    def test_hub_profile_mode_override_peer(self, tmp_path: Path) -> None:
        """Hub profile with explicit mode: peer -- YAML override wins."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "hub",
            "reticulum": {"mode": "peer"},
        }))

        config = load_core_config(config_path)
        assert config.profile == Profile.HUB
        assert config.reticulum.mode == DeploymentMode.PEER

    def test_hub_profile_mode_override_preserves_other_hub_defaults(self, tmp_path: Path) -> None:
        """Mode override doesn't clobber other hub profile defaults.

        Only mode should change; relay_mode, ipc, public_mode, etc. should
        still reflect hub profile defaults.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "profile": "hub",
            "reticulum": {"mode": "standalone"},
        }))

        config = load_core_config(config_path)
        assert config.rpc.relay_mode is True  # Hub default
        assert config.api.public_mode is True  # Hub default
        assert config.ipc.enabled is False  # Hub default
        assert config.lxmf.propagation_node.enabled is True  # Hub default

    # ---------------------------------------------------------------
    # 3. Hub profile validation
    # ---------------------------------------------------------------

    def test_hub_defaults_fail_validation_no_interfaces(self) -> None:
        """Hub profile defaults have no server/peers -- validation should flag this.

        Hub mode requires server or peer connectivity, but get_profile_defaults
        does not set up any interfaces. This is by design (user must configure
        connectivity) but validation should catch it.
        """
        config = get_profile_defaults(Profile.HUB)
        errors = validate_core_config(config)

        # Should have at least the hub-mode-requires-connectivity error
        hub_mode_errors = [
            e for e in errors if e.field == "reticulum.mode" and "hub" in e.message.lower()
        ]
        assert len(hub_mode_errors) > 0, (
            f"Expected hub mode validation error, got: {[str(e) for e in errors]}"
        )

    def test_hub_defaults_also_flag_propagation_node_name(self) -> None:
        """Hub defaults enable propagation_node but don't set a name.

        Validation requires a name when propagation_node.enabled is True.
        """
        config = get_profile_defaults(Profile.HUB)
        errors = validate_core_config(config)

        prop_errors = [
            e for e in errors if "propagation_node" in e.field and "name" in e.message.lower()
        ]
        assert len(prop_errors) > 0, (
            f"Expected propagation_node.name error, got: {[str(e) for e in errors]}"
        )

    def test_hub_with_server_and_name_passes_validation(self) -> None:
        """Hub profile with server interface and propagation name should validate clean."""
        config = get_profile_defaults(Profile.HUB)
        config.reticulum.interfaces.server.enabled = True
        config.lxmf.propagation_node.name = "test-hub"

        errors = validate_core_config(config)
        assert errors == [], f"Expected no errors, got: {[str(e) for e in errors]}"

    # ---------------------------------------------------------------
    # 6. Mixed profile defaults leak
    # ---------------------------------------------------------------

    def test_hub_ipc_explicitly_disabled(self) -> None:
        """Hub profile explicitly disables IPC, not just inheriting dataclass default.

        CoreConfig() default for ipc.enabled is True (dataclass default).
        Hub profile must actively set it to False. If get_profile_defaults
        forgot to set this, IPC would leak through from the base default.
        """
        # Dataclass default is True
        bare_config = CoreConfig()
        assert bare_config.ipc.enabled is True

        # Hub must explicitly override
        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.ipc.enabled is False

    def test_hub_notifications_explicitly_disabled(self) -> None:
        """Hub profile explicitly disables notifications.

        CoreConfig() default for notifications.enabled is True.
        Hub profile must actively set it to False.
        """
        bare_config = CoreConfig()
        assert bare_config.notifications.enabled is True

        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.notifications.enabled is False

    def test_hub_terminal_explicitly_disabled(self) -> None:
        """Hub profile explicitly disables terminal.

        CoreConfig() default for terminal.enabled is False (same as hub).
        Verify hub does not accidentally enable it.
        """
        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.terminal.enabled is False

    def test_hub_command_execution_explicitly_disabled(self) -> None:
        """Hub profile explicitly disables command execution.

        CoreConfig() default for rpc.allow_command_execution is True.
        Hub must actively set it to False for safety.
        """
        bare_config = CoreConfig()
        assert bare_config.rpc.allow_command_execution is True

        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.rpc.allow_command_execution is False

    def test_hub_defaults_do_not_leak_operator_ipc(self) -> None:
        """Getting hub defaults after operator defaults doesn't leak operator IPC state.

        Verifies that get_profile_defaults creates independent config objects
        and doesn't mutate shared state.
        """
        operator_config = get_profile_defaults(Profile.OPERATOR)
        assert operator_config.ipc.enabled is True

        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.ipc.enabled is False

        # Verify operator wasn't mutated
        assert operator_config.ipc.enabled is True

    def test_hub_defaults_independent_of_call_order(self) -> None:
        """Profile defaults are independent -- calling hub then operator doesn't leak."""
        hub_config = get_profile_defaults(Profile.HUB)
        operator_config = get_profile_defaults(Profile.OPERATOR)
        hub_config2 = get_profile_defaults(Profile.HUB)

        # All hub configs should be identical regardless of interleaved calls
        assert hub_config.ipc.enabled is False
        assert hub_config2.ipc.enabled is False
        assert operator_config.ipc.enabled is True

        assert hub_config.api.public_mode is True
        assert hub_config2.api.public_mode is True
        assert operator_config.api.public_mode is False

    def test_hub_enable_transport_explicit(self) -> None:
        """Hub profile explicitly sets enable_transport=True rather than relying on auto.

        CoreConfig() default for enable_transport is None (auto-detect).
        Hub profile must explicitly set it to True so it's deterministic.
        """
        bare_config = CoreConfig()
        assert bare_config.reticulum.enable_transport is None

        hub_config = get_profile_defaults(Profile.HUB)
        assert hub_config.reticulum.enable_transport is True

    def test_hub_profile_yaml_round_trip_with_mode_override(self, tmp_path: Path) -> None:
        """Hub profile with mode override survives full round-trip.

        Save a hub profile with mode=standalone, reload, verify both
        profile=hub and mode=standalone are preserved.
        """
        config = get_profile_defaults(Profile.HUB)
        config.reticulum.mode = DeploymentMode.STANDALONE
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.profile == Profile.HUB
        assert loaded.reticulum.mode == DeploymentMode.STANDALONE
