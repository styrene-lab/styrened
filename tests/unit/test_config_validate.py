"""Tests for validate_core_config().

Validates port ranges, enum values, string constraints, and cross-field rules.
"""

from __future__ import annotations

import pytest

from styrened.models.config import (
    ConfigValidationError,
    CoreConfig,
    DeploymentMode,
    PeerConfig,
    PropagationNodeConfig,
)
from styrened.services.config import validate_core_config


class TestValidateCoreConfig:
    """Tests for validate_core_config()."""

    def test_valid_default_config_no_errors(self) -> None:
        """Default CoreConfig passes validation with no errors."""
        errors = validate_core_config(CoreConfig())
        assert errors == []

    def test_invalid_port_zero(self) -> None:
        """Port 0 is rejected."""
        config = CoreConfig()
        config.api.port = 0
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "api.port" in field_names

    def test_invalid_port_too_high(self) -> None:
        """Port > 65535 is rejected."""
        config = CoreConfig()
        config.api.port = 70000
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "api.port" in field_names

    def test_invalid_server_interface_port(self) -> None:
        """Server interface port validated."""
        config = CoreConfig()
        config.reticulum.interfaces.server.port = 0
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "reticulum.interfaces.server.port" in field_names

    def test_invalid_peer_port(self) -> None:
        """Peer port validated."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [PeerConfig(host="10.0.0.1", port=99999)]
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "reticulum.interfaces.peers[0].port" in field_names

    def test_empty_peer_host(self) -> None:
        """Empty peer host is rejected."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [PeerConfig(host="", port=4242)]
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "reticulum.interfaces.peers[0].host" in field_names

    def test_invalid_short_name(self) -> None:
        """Invalid short_name is rejected."""
        config = CoreConfig()
        config.identity.short_name = "INVALID"
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "identity.short_name" in field_names

    def test_valid_short_name_passes(self) -> None:
        """Valid short_name passes."""
        config = CoreConfig()
        config.identity.short_name = "valid-name"
        errors = validate_core_config(config)
        assert not any(e.field == "identity.short_name" for e in errors)

    def test_display_name_too_long(self) -> None:
        """Display name > 100 chars is rejected."""
        config = CoreConfig()
        config.identity.display_name = "x" * 101
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "identity.display_name" in field_names

    def test_display_name_empty(self) -> None:
        """Empty display name is rejected."""
        config = CoreConfig()
        config.identity.display_name = ""
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "identity.display_name" in field_names

    def test_invalid_provider(self) -> None:
        """Unknown identity provider is rejected."""
        config = CoreConfig()
        config.identity.provider = "hardware-token"
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "identity.provider" in field_names

    def test_hub_mode_without_connectivity(self) -> None:
        """Hub mode with no server or peers raises error."""
        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.interfaces.server.enabled = False
        config.reticulum.interfaces.peers = []
        errors = validate_core_config(config)
        assert any("hub" in str(e).lower() for e in errors)

    def test_hub_mode_with_server_passes(self) -> None:
        """Hub mode with server interface passes."""
        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.interfaces.server.enabled = True
        errors = validate_core_config(config)
        assert not any("hub" in str(e).lower() for e in errors)

    def test_hub_mode_with_peers_passes(self) -> None:
        """Hub mode with peers passes."""
        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.interfaces.peers = [PeerConfig(host="10.0.0.1")]
        errors = validate_core_config(config)
        assert not any("hub" in str(e).lower() for e in errors)

    def test_propagation_node_without_name(self) -> None:
        """Propagation node enabled without name is rejected."""
        config = CoreConfig()
        config.lxmf.propagation_node = PropagationNodeConfig(enabled=True, name=None)
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "lxmf.propagation_node.name" in field_names

    def test_propagation_node_with_name_passes(self) -> None:
        """Propagation node with name passes."""
        config = CoreConfig()
        config.lxmf.propagation_node = PropagationNodeConfig(enabled=True, name="Relay")
        errors = validate_core_config(config)
        assert not any(e.field == "lxmf.propagation_node.name" for e in errors)

    def test_negative_announce_interval(self) -> None:
        """Negative announce_interval is rejected."""
        config = CoreConfig()
        config.reticulum.announce_interval = -1
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "reticulum.announce_interval" in field_names

    def test_negative_auto_reply_cooldown(self) -> None:
        """Negative auto_reply_cooldown is rejected."""
        config = CoreConfig()
        config.chat.auto_reply_cooldown = -5
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "chat.auto_reply_cooldown" in field_names

    def test_zero_auto_reply_cooldown_passes(self) -> None:
        """Zero auto_reply_cooldown is valid (no cooldown)."""
        config = CoreConfig()
        config.chat.auto_reply_cooldown = 0
        errors = validate_core_config(config)
        assert not any(e.field == "chat.auto_reply_cooldown" for e in errors)

    def test_invalid_quiet_hours(self) -> None:
        """Quiet hours outside 0-23 are rejected."""
        config = CoreConfig()
        config.notifications.quiet_hours_start = 25
        config.notifications.quiet_hours_end = -1
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "notifications.quiet_hours_start" in field_names
        assert "notifications.quiet_hours_end" in field_names

    def test_invalid_hub_address_length(self) -> None:
        """Hub address must be 32 chars."""
        config = CoreConfig()
        config.reticulum.hub_address = "tooshort"
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "reticulum.hub_address" in field_names

    def test_invalid_propagation_destination(self) -> None:
        """Propagation destination must be 32 chars."""
        config = CoreConfig()
        config.lxmf.propagation_destination = "abc"
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "lxmf.propagation_destination" in field_names

    def test_invalid_static_peer_hash(self) -> None:
        """Static peers must be 32-char hex hashes."""
        config = CoreConfig()
        config.lxmf.static_peers = ["short"]
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "lxmf.static_peers" in field_names

    def test_invalid_authorized_identity(self) -> None:
        """Authorized identities must be 32-char hex hashes."""
        config = CoreConfig()
        config.terminal.authorized_identities = {"not32chars"}
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "terminal.authorized_identities" in field_names

    def test_multiple_errors_all_reported(self) -> None:
        """Multiple errors in one config are all reported."""
        config = CoreConfig()
        config.api.port = 0
        config.reticulum.announce_interval = -1
        config.identity.display_name = ""
        config.chat.auto_reply_cooldown = -5

        errors = validate_core_config(config)
        assert len(errors) >= 4

    def test_raise_on_error_raises(self) -> None:
        """raise_on_error=True raises ConfigValidationError."""
        config = CoreConfig()
        config.api.port = 0
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_core_config(config, raise_on_error=True)
        assert len(exc_info.value.errors) >= 1

    # --- API Auth ---

    def test_auth_session_ttl_too_low(self) -> None:
        """Session TTL below 60 seconds is rejected."""
        config = CoreConfig()
        config.api.auth.session_ttl = 30
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "api.auth.session_ttl" in field_names

    def test_auth_session_ttl_valid(self) -> None:
        """Session TTL of 60 seconds passes."""
        config = CoreConfig()
        config.api.auth.session_ttl = 60
        errors = validate_core_config(config)
        assert not any(e.field == "api.auth.session_ttl" for e in errors)

    def test_auth_invalid_authorized_identity(self) -> None:
        """Auth authorized identities must be 32-char hex hashes."""
        config = CoreConfig()
        config.api.auth.authorized_identities = {"short"}
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert "api.auth.authorized_identities" in field_names

    def test_auth_valid_authorized_identity(self) -> None:
        """Valid 32-char hex hash passes."""
        config = CoreConfig()
        config.api.auth.authorized_identities = {"a" * 32}
        errors = validate_core_config(config)
        assert not any(e.field == "api.auth.authorized_identities" for e in errors)

    def test_raise_on_error_no_error_succeeds(self) -> None:
        """raise_on_error=True with valid config does not raise."""
        errors = validate_core_config(CoreConfig(), raise_on_error=True)
        assert errors == []


class TestPQCConfigValidation:
    """Tests for PQC configuration validation."""

    def test_pqc_rekey_interval_valid(self) -> None:
        """Valid rekey_interval_hours passes validation."""
        config = CoreConfig()
        config.pqc.rekey_interval_hours = 12
        errors = validate_core_config(config)
        pqc_errors = [e for e in errors if "pqc." in e.field]
        assert len(pqc_errors) == 0

    def test_pqc_rekey_interval_zero_fails(self) -> None:
        """rekey_interval_hours < 1 fails validation."""
        config = CoreConfig()
        config.pqc.rekey_interval_hours = 0
        errors = validate_core_config(config)
        pqc_errors = [e for e in errors if e.field == "pqc.rekey_interval_hours"]
        assert len(pqc_errors) == 1
