"""Tests for save_core_config() round-trip serialization.

Validates that all 10 config sections survive a save → load cycle with
all fields intact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from styrened.models.config import (
    APIConfig,
    AutoReplyMode,
    ChatConfig,
    CoreConfig,
    DeploymentMode,
    DiscoveryConfig,
    IPCConfig,
    IdentityConfig,
    LXMFConfig,
    MetricsConfig,
    NotificationsConfig,
    PeerConfig,
    PropagationNodeConfig,
    RPCConfig,
    ReticulumConfig,
    ServerInterfaceConfig,
    TerminalConfig,
    YubiKeyConfig,
)
from styrened.services.config import load_core_config, save_core_config


class TestSaveCoreConfigRoundTrip:
    """save → load round-trip for every config section."""

    def test_default_config_round_trip(self, tmp_path: Path) -> None:
        """Default CoreConfig survives save → load unchanged."""
        config = CoreConfig()
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        # Reticulum
        assert loaded.reticulum.mode == config.reticulum.mode
        assert loaded.reticulum.announce_interval == config.reticulum.announce_interval
        assert loaded.reticulum.auto_initialize == config.reticulum.auto_initialize
        assert loaded.reticulum.hub_enabled == config.reticulum.hub_enabled

        # Identity
        assert loaded.identity.display_name == config.identity.display_name
        assert loaded.identity.icon == config.identity.icon
        assert loaded.identity.provider == config.identity.provider

        # RPC
        assert loaded.rpc.enabled == config.rpc.enabled
        assert loaded.rpc.relay_mode == config.rpc.relay_mode
        assert loaded.rpc.allow_command_execution == config.rpc.allow_command_execution

        # Discovery
        assert loaded.discovery.enabled == config.discovery.enabled
        assert loaded.discovery.auto_announce == config.discovery.auto_announce

        # Chat
        assert loaded.chat.enabled == config.chat.enabled
        assert loaded.chat.auto_reply_mode == config.chat.auto_reply_mode
        assert loaded.chat.auto_reply_message == config.chat.auto_reply_message
        assert loaded.chat.auto_reply_cooldown == config.chat.auto_reply_cooldown
        assert loaded.chat.persist_messages == config.chat.persist_messages

        # API
        assert loaded.api.enabled == config.api.enabled
        assert loaded.api.host == config.api.host
        assert loaded.api.port == config.api.port
        assert loaded.api.metrics.enabled == config.api.metrics.enabled

        # IPC
        assert loaded.ipc.enabled == config.ipc.enabled
        assert loaded.ipc.socket_mode == config.ipc.socket_mode

        # Notifications
        assert loaded.notifications.enabled == config.notifications.enabled
        assert loaded.notifications.quiet_hours_start == config.notifications.quiet_hours_start
        assert loaded.notifications.quiet_hours_end == config.notifications.quiet_hours_end

        # LXMF
        assert loaded.lxmf.propagation_node.enabled == config.lxmf.propagation_node.enabled
        assert loaded.lxmf.autopeer == config.lxmf.autopeer
        assert loaded.lxmf.max_peers == config.lxmf.max_peers
        assert loaded.lxmf.propagation_cost == config.lxmf.propagation_cost

        # Terminal
        assert loaded.terminal.enabled == config.terminal.enabled
        assert loaded.terminal.allow_unauthenticated == config.terminal.allow_unauthenticated

    def test_fully_customized_config_round_trip(self, tmp_path: Path) -> None:
        """Config with ALL fields customized survives round-trip."""
        config = CoreConfig(
            reticulum=ReticulumConfig(
                mode=DeploymentMode.HUB,
                auto_initialize=False,
                enable_transport=True,
                config_path_override=Path("/etc/custom/reticulum"),
                operator_identity_path=Path("/etc/styrene/custom-id"),
                announce_interval=60,
                hub_enabled=True,
                hub_address="a" * 32,
                hub_announce_interval=30,
            ),
            identity=IdentityConfig(
                display_name="Test Hub",
                icon="🖥️",
                short_name="test-hub",
                provider="file",
            ),
            rpc=RPCConfig(
                enabled=True,
                relay_mode=True,
                allow_command_execution=False,
            ),
            discovery=DiscoveryConfig(
                enabled=False,
                auto_announce=False,
            ),
            chat=ChatConfig(
                enabled=False,
                auto_reply_mode=AutoReplyMode.DISABLED,
                auto_reply_message="Custom auto-reply",
                auto_reply_cooldown=600,
                persist_messages=False,
            ),
            api=APIConfig(
                enabled=True,
                host="127.0.0.1",
                port=9000,
                metrics=MetricsConfig(enabled=True),
            ),
            ipc=IPCConfig(
                enabled=False,
                socket_path=Path("/run/custom/control.sock"),
                socket_mode=0o770,
            ),
            notifications=NotificationsConfig(
                enabled=False,
                quiet_hours_start=22,
                quiet_hours_end=7,
            ),
            lxmf=LXMFConfig(
                propagation_node=PropagationNodeConfig(enabled=True, name="My Prop Node"),
                propagation_destination="b" * 32,
                propagation_limit=512,
                sync_limit=20480,
                delivery_limit=2000,
                autopeer=False,
                autopeer_maxdepth=8,
                max_peers=50,
                static_peers=["c" * 32, "d" * 32],
                from_static_only=True,
                propagation_cost=32,
                propagation_cost_flexibility=5,
                peering_cost=20,
                max_peering_cost=30,
            ),
            terminal=TerminalConfig(
                enabled=True,
                authorized_identities={"e" * 32, "f" * 32},
                allow_unauthenticated=False,
                default_shell="/bin/zsh",
                allowed_shells={"/bin/bash", "/bin/zsh"},
                session_idle_timeout=1800,
                max_sessions_per_identity=5,
                max_total_sessions=20,
                rate_limit_requests=20,
            ),
        )
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        # Reticulum
        assert loaded.reticulum.mode == DeploymentMode.HUB
        assert loaded.reticulum.auto_initialize is False
        assert loaded.reticulum.enable_transport is True
        assert loaded.reticulum.config_path_override == Path("/etc/custom/reticulum")
        assert loaded.reticulum.announce_interval == 60
        assert loaded.reticulum.hub_enabled is True
        assert loaded.reticulum.hub_address == "a" * 32
        assert loaded.reticulum.hub_announce_interval == 30

        # Identity
        assert loaded.identity.display_name == "Test Hub"
        assert loaded.identity.icon == "🖥️"
        assert loaded.identity.short_name == "test-hub"
        assert loaded.identity.provider == "file"

        # RPC
        assert loaded.rpc.relay_mode is True
        assert loaded.rpc.allow_command_execution is False

        # Discovery
        assert loaded.discovery.enabled is False
        assert loaded.discovery.auto_announce is False

        # Chat
        assert loaded.chat.auto_reply_message == "Custom auto-reply"
        assert loaded.chat.auto_reply_cooldown == 600
        assert loaded.chat.persist_messages is False

        # API
        assert loaded.api.host == "127.0.0.1"
        assert loaded.api.port == 9000
        assert loaded.api.metrics.enabled is True

        # IPC
        assert loaded.ipc.enabled is False
        assert loaded.ipc.socket_path == Path("/run/custom/control.sock")
        assert loaded.ipc.socket_mode == 0o770

        # Notifications
        assert loaded.notifications.quiet_hours_start == 22
        assert loaded.notifications.quiet_hours_end == 7

        # LXMF
        assert loaded.lxmf.propagation_node.enabled is True
        assert loaded.lxmf.propagation_node.name == "My Prop Node"
        assert loaded.lxmf.propagation_destination == "b" * 32
        assert loaded.lxmf.propagation_limit == 512
        assert loaded.lxmf.sync_limit == 20480
        assert loaded.lxmf.delivery_limit == 2000
        assert loaded.lxmf.autopeer is False
        assert loaded.lxmf.autopeer_maxdepth == 8
        assert loaded.lxmf.max_peers == 50
        assert loaded.lxmf.static_peers == ["c" * 32, "d" * 32]
        assert loaded.lxmf.from_static_only is True
        assert loaded.lxmf.propagation_cost == 32
        assert loaded.lxmf.propagation_cost_flexibility == 5
        assert loaded.lxmf.peering_cost == 20
        assert loaded.lxmf.max_peering_cost == 30

        # Terminal
        assert loaded.terminal.enabled is True
        assert loaded.terminal.authorized_identities == {"e" * 32, "f" * 32}
        assert loaded.terminal.allow_unauthenticated is False
        assert loaded.terminal.default_shell == "/bin/zsh"
        assert loaded.terminal.allowed_shells == {"/bin/bash", "/bin/zsh"}
        assert loaded.terminal.session_idle_timeout == 1800
        assert loaded.terminal.max_sessions_per_identity == 5
        assert loaded.terminal.max_total_sessions == 20
        assert loaded.terminal.rate_limit_requests == 20

    def test_nested_interfaces_round_trip(self, tmp_path: Path) -> None:
        """Server interface and peers survive round-trip."""
        config = CoreConfig()
        config.reticulum.interfaces.auto = True
        config.reticulum.interfaces.server = ServerInterfaceConfig(
            enabled=True, listen_ip="192.168.1.1", port=5555
        )
        config.reticulum.interfaces.peers = [
            PeerConfig(host="10.0.0.1", port=4242, name="Hub Alpha"),
            PeerConfig(host="10.0.0.2", port=4243),
        ]
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.reticulum.interfaces.auto is True
        assert loaded.reticulum.interfaces.server.enabled is True
        assert loaded.reticulum.interfaces.server.listen_ip == "192.168.1.1"
        assert loaded.reticulum.interfaces.server.port == 5555
        assert len(loaded.reticulum.interfaces.peers) == 2
        assert loaded.reticulum.interfaces.peers[0].host == "10.0.0.1"
        assert loaded.reticulum.interfaces.peers[0].name == "Hub Alpha"
        assert loaded.reticulum.interfaces.peers[1].host == "10.0.0.2"
        assert loaded.reticulum.interfaces.peers[1].port == 4243

    def test_yubikey_config_round_trip(self, tmp_path: Path) -> None:
        """YubiKey identity config survives round-trip."""
        config = CoreConfig()
        config.identity.provider = "yubikey"
        config.identity.yubikey = YubiKeyConfig(
            credential_id="base64-cred-id-here",
            rp_id="custom.mesh.org",
            require_touch=True,
        )
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.identity.provider == "yubikey"
        assert loaded.identity.yubikey.credential_id == "base64-cred-id-here"
        assert loaded.identity.yubikey.rp_id == "custom.mesh.org"
        assert loaded.identity.yubikey.require_touch is True

    def test_lxmf_propagation_node_round_trip(self, tmp_path: Path) -> None:
        """LXMF propagation node config survives round-trip."""
        config = CoreConfig()
        config.lxmf.propagation_node = PropagationNodeConfig(
            enabled=True, name="Relay Node Alpha"
        )
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        assert loaded.lxmf.propagation_node.enabled is True
        assert loaded.lxmf.propagation_node.name == "Relay Node Alpha"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """save_core_config creates parent directories if needed."""
        config = CoreConfig()
        config_path = tmp_path / "subdir" / "nested" / "config.yaml"

        save_core_config(config, config_path)

        assert config_path.exists()
        loaded = load_core_config(config_path)
        assert loaded.reticulum.mode == DeploymentMode.STANDALONE

    def test_optional_none_fields_omitted(self, tmp_path: Path) -> None:
        """Fields with None values are omitted from YAML (not written as null)."""
        config = CoreConfig()
        config_path = tmp_path / "config.yaml"

        save_core_config(config, config_path)

        content = config_path.read_text()
        # These optional fields should not appear when None/default
        assert "operator_identity_path" not in content
        assert "config_path_override" not in content
        assert "hub_address" not in content
        assert "socket_path" not in content
        assert "propagation_destination" not in content
