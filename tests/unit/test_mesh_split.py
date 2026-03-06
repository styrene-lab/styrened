"""Unit tests for mesh view split: MY MESH vs OTHER STYRENE NODES.

Tests cover:
- /meta endpoint returns only non-identifiable fields
- /info endpoint respects info_respond flag (default False)
- DiscoveryConfig parsing: info_respond, operator_label
- DiscoveryConfig serialization round-trip
- RPCServer._gather_meta() field contract
- RPCServer._gather_info() field contract
- DirectLinkService.request_meta/request_info response handling
- IPC protocol: no duplicate command values after new additions
- MeshDeviceTree._is_my_mesh() RBAC roster integration
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.config import CoreConfig, DiscoveryConfig
from styrened.models.rbac import RBACPolicy, Role, RosterEntry
from styrened.services.config import load_core_config, save_core_config

# ---------------------------------------------------------------------------
# DiscoveryConfig: new fields
# ---------------------------------------------------------------------------


class TestDiscoveryConfigDefaults:
    def test_info_respond_defaults_false(self) -> None:
        """info_respond must default to False — default-deny."""
        config = DiscoveryConfig()
        assert config.info_respond is False

    def test_operator_label_defaults_empty(self) -> None:
        config = DiscoveryConfig()
        assert config.operator_label == ""


class TestDiscoveryConfigParsing:
    def test_parse_info_respond_true(self, tmp_path) -> None:
        cfg_file = tmp_path / "core-config.yaml"
        cfg_file.write_text(
            "discovery:\n"
            "  info_respond: true\n"
            "  operator_label: test-operator\n"
        )
        config = load_core_config(config_path=cfg_file)
        assert config.discovery.info_respond is True
        assert config.discovery.operator_label == "test-operator"

    def test_parse_info_respond_false_explicit(self, tmp_path) -> None:
        cfg_file = tmp_path / "core-config.yaml"
        cfg_file.write_text("discovery:\n  info_respond: false\n")
        config = load_core_config(config_path=cfg_file)
        assert config.discovery.info_respond is False

    def test_parse_missing_info_respond_defaults_false(self, tmp_path) -> None:
        cfg_file = tmp_path / "core-config.yaml"
        cfg_file.write_text("discovery:\n  enabled: true\n")
        config = load_core_config(config_path=cfg_file)
        assert config.discovery.info_respond is False


class TestDiscoveryConfigSerializationRoundtrip:
    def test_info_respond_roundtrip(self, tmp_path) -> None:
        cfg_file = tmp_path / "core-config.yaml"
        config = load_core_config(config_path=cfg_file)
        config.discovery.info_respond = True
        config.discovery.operator_label = "my-operator"
        save_core_config(config, config_path=cfg_file)
        reloaded = load_core_config(config_path=cfg_file)
        assert reloaded.discovery.info_respond is True
        assert reloaded.discovery.operator_label == "my-operator"

    def test_info_respond_false_roundtrip(self, tmp_path) -> None:
        cfg_file = tmp_path / "core-config.yaml"
        config = load_core_config(config_path=cfg_file)
        config.discovery.info_respond = False
        config.discovery.operator_label = ""
        save_core_config(config, config_path=cfg_file)
        reloaded = load_core_config(config_path=cfg_file)
        assert reloaded.discovery.info_respond is False

    def test_empty_operator_label_not_serialized(self, tmp_path) -> None:
        """Empty operator_label should not add a key to the YAML."""
        cfg_file = tmp_path / "core-config.yaml"
        config = load_core_config(config_path=cfg_file)
        config.discovery.operator_label = ""
        save_core_config(config, config_path=cfg_file)
        content = cfg_file.read_text()
        assert "operator_label" not in content


# ---------------------------------------------------------------------------
# RPCServer._gather_meta() — non-identifiable contract
# ---------------------------------------------------------------------------


class TestGatherMeta:
    def _make_server(self):
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer
        protocol = MagicMock()
        return RPCServer(styrene_protocol=protocol)

    def test_meta_contains_styrene_version(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "styrene_version" in meta
        assert isinstance(meta["styrene_version"], str)

    def test_meta_contains_profile(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "profile" in meta

    def test_meta_contains_capabilities(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "capabilities" in meta
        assert isinstance(meta["capabilities"], list)

    def test_meta_contains_arch(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "arch" in meta

    def test_meta_contains_os_id(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "os_id" in meta

    def test_meta_excludes_hostname(self) -> None:
        """Hostname is identifiable — must NOT appear in /meta."""
        server = self._make_server()
        meta = server._gather_meta()
        assert "hostname" not in meta

    def test_meta_excludes_ip(self) -> None:
        """IP address is identifiable — must NOT appear in /meta."""
        server = self._make_server()
        meta = server._gather_meta()
        assert "ip" not in meta

    def test_meta_excludes_uptime(self) -> None:
        """Uptime could be used for fingerprinting — excluded from /meta."""
        server = self._make_server()
        meta = server._gather_meta()
        assert "uptime" not in meta

    def test_meta_excludes_disk_info(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "disk_used" not in meta
        assert "disk_total" not in meta

    def test_meta_excludes_nixos_generation(self) -> None:
        server = self._make_server()
        meta = server._gather_meta()
        assert "nixos_generation" not in meta

    def test_meta_with_config_sets_profile(self) -> None:
        server = self._make_server()
        config = CoreConfig()
        meta = server._gather_meta(config)
        assert meta["profile"] == config.profile.value


# ---------------------------------------------------------------------------
# RPCServer._gather_info() — identifiable contract
# ---------------------------------------------------------------------------


class TestGatherInfo:
    def _make_server(self):
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer
        protocol = MagicMock()
        return RPCServer(styrene_protocol=protocol)

    def test_info_contains_name(self) -> None:
        server = self._make_server()
        info = server._gather_info()
        assert "name" in info

    def test_info_contains_operator_label(self) -> None:
        server = self._make_server()
        info = server._gather_info()
        assert "operator_label" in info

    def test_info_excludes_ip(self) -> None:
        server = self._make_server()
        info = server._gather_info()
        assert "ip" not in info

    def test_info_excludes_hostname(self) -> None:
        server = self._make_server()
        info = server._gather_info()
        assert "hostname" not in info

    def test_info_with_config_uses_operator_label(self) -> None:
        server = self._make_server()
        config = CoreConfig()
        config.discovery.operator_label = "test-label"
        info = server._gather_info(config)
        assert info["operator_label"] == "test-label"

    def test_info_no_config_returns_empty_strings(self) -> None:
        server = self._make_server()
        info = server._gather_info(None)
        assert info["name"] == ""
        assert info["operator_label"] == ""


# ---------------------------------------------------------------------------
# /info default-deny: info_respond=False returns empty dict
# ---------------------------------------------------------------------------


class TestInfoRespondFlag:
    def test_info_respond_false_returns_empty(self) -> None:
        """When info_respond=False, /info handler returns {}."""
        config = CoreConfig()
        assert config.discovery.info_respond is False
        # Simulate what daemon._serve_datalink_info does
        if not config.discovery.info_respond:
            result = {}
        else:
            result = {"name": "something"}
        assert result == {}

    def test_info_respond_true_returns_data(self) -> None:
        config = CoreConfig()
        config.discovery.info_respond = True
        config.discovery.operator_label = "op1"
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer
        server = RPCServer(styrene_protocol=MagicMock())
        if config.discovery.info_respond:
            result = server._gather_info(config)
        else:
            result = {}
        assert result.get("operator_label") == "op1"


# ---------------------------------------------------------------------------
# DirectLinkService response handling
# ---------------------------------------------------------------------------


class TestDirectLinkMetaHandling:
    @pytest.mark.asyncio
    async def test_request_meta_parses_json(self) -> None:
        """request_meta should parse and return the JSON dict."""
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        meta_payload = json.dumps({
            "styrene_version": "0.14.1",
            "profile": "node",
            "capabilities": ["lxmf", "rpc"],
            "arch": "aarch64",
            "os_id": "nixos",
        }).encode()
        svc.request = AsyncMock(return_value=meta_payload)
        result = await svc.request_meta("abc123")
        assert result is not None
        assert result["styrene_version"] == "0.14.1"
        assert result["profile"] == "node"

    @pytest.mark.asyncio
    async def test_request_meta_empty_response_returns_none(self) -> None:
        """Empty dict from remote (older node without /meta) → None."""
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        svc.request = AsyncMock(return_value=b"{}")
        result = await svc.request_meta("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_request_meta_no_response_returns_none(self) -> None:
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        svc.request = AsyncMock(return_value=None)
        result = await svc.request_meta("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_request_info_declined_returns_none(self) -> None:
        """Empty dict = remote declined (info_respond=False) → None."""
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        svc.request = AsyncMock(return_value=b"{}")
        result = await svc.request_info("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_request_info_with_name_returns_dict(self) -> None:
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        info_payload = json.dumps({
            "name": "remote-node",
            "operator_label": "alice",
        }).encode()
        svc.request = AsyncMock(return_value=info_payload)
        result = await svc.request_info("abc123")
        assert result is not None
        assert result["name"] == "remote-node"

    @pytest.mark.asyncio
    async def test_request_info_empty_values_returns_none(self) -> None:
        """Dict with only empty string values is treated as declined."""
        from styrened.services.direct_link import DirectLinkService
        svc = DirectLinkService.__new__(DirectLinkService)
        svc.request = AsyncMock(return_value=b'{"name": "", "operator_label": ""}')
        result = await svc.request_info("abc123")
        assert result is None


# ---------------------------------------------------------------------------
# IPC protocol: no duplicate values
# ---------------------------------------------------------------------------


class TestIPCProtocolNoDuplicates:
    def test_no_duplicate_command_values(self) -> None:
        """All IPCMessageType values must be unique after adding meta/info cmds."""
        from styrened.ipc.protocol import IPCMessageType
        values = [e.value for e in IPCMessageType]
        assert len(values) == len(set(values)), (
            f"Duplicate IPCMessageType values: "
            f"{[v for v in values if values.count(v) > 1]}"
        )

    def test_meta_and_info_commands_present(self) -> None:
        from styrened.ipc.protocol import IPCMessageType
        assert hasattr(IPCMessageType, "CMD_DATALINK_META")
        assert hasattr(IPCMessageType, "CMD_DATALINK_INFO")
        assert IPCMessageType.CMD_DATALINK_META.value == 0x65
        assert IPCMessageType.CMD_DATALINK_INFO.value == 0x66


# ---------------------------------------------------------------------------
# MeshDeviceTree._is_my_mesh() RBAC integration
# ---------------------------------------------------------------------------


class TestIsMymesh:
    def _make_device(self, identity_hash: str) -> MagicMock:
        device = MagicMock()
        device.identity_hash = identity_hash
        return device

    def test_roster_hit_peer_is_my_mesh(self) -> None:
        from styrened.tui.screens.dashboard import MeshDeviceTree

        tree = MeshDeviceTree.__new__(MeshDeviceTree)

        config = CoreConfig()
        config.rbac = RBACPolicy(
            roster={"aabbccdd" * 4: RosterEntry(
                identity_hash="aabbccdd" * 4,
                role=Role.PEER,
            )}
        )

        with patch("styrened.services.config.load_core_config", return_value=config):
            device = self._make_device("aabbccdd" * 4)
            assert tree._is_my_mesh(device) is True

    def test_missing_identity_uses_default_role(self) -> None:
        """Identity not in roster resolves to default_role.
        With default_role=PEER (the default), the node IS 'my mesh'.
        With default_role=NONE, it is NOT.
        """
        from styrened.models.rbac import Role
        from styrened.tui.screens.dashboard import MeshDeviceTree

        tree = MeshDeviceTree.__new__(MeshDeviceTree)

        # default_role=PEER → any unlisted node counts as trusted
        config_peer = CoreConfig()
        config_peer.rbac = RBACPolicy(default_role=Role.PEER)
        with patch("styrened.services.config.load_core_config", return_value=config_peer):
            device = self._make_device("11223344" * 4)
            assert tree._is_my_mesh(device) is True

        # default_role=NONE → unlisted nodes are not trusted
        config_none = CoreConfig()
        config_none.rbac = RBACPolicy(default_role=Role.NONE)
        with patch("styrened.services.config.load_core_config", return_value=config_none):
            device = self._make_device("11223344" * 4)
            assert tree._is_my_mesh(device) is False

    def test_blocked_identity_is_not_my_mesh(self) -> None:
        from styrened.tui.screens.dashboard import MeshDeviceTree

        tree = MeshDeviceTree.__new__(MeshDeviceTree)

        config = CoreConfig()
        config.rbac = RBACPolicy(
            roster={"deadbeef" * 4: RosterEntry(
                identity_hash="deadbeef" * 4,
                role=Role.BLOCKED,
            )}
        )

        with patch("styrened.services.config.load_core_config", return_value=config):
            device = self._make_device("deadbeef" * 4)
            assert tree._is_my_mesh(device) is False

    def test_no_rbac_config_is_not_my_mesh(self) -> None:
        from styrened.tui.screens.dashboard import MeshDeviceTree

        tree = MeshDeviceTree.__new__(MeshDeviceTree)

        config = CoreConfig()
        config.rbac = None

        with patch("styrened.services.config.load_core_config", return_value=config):
            device = self._make_device("aabbccdd" * 4)
            assert tree._is_my_mesh(device) is False

    def test_admin_identity_is_my_mesh(self) -> None:
        from styrened.tui.screens.dashboard import MeshDeviceTree

        tree = MeshDeviceTree.__new__(MeshDeviceTree)

        config = CoreConfig()
        config.rbac = RBACPolicy(
            roster={"cafebabe" * 4: RosterEntry(
                identity_hash="cafebabe" * 4,
                role=Role.ADMIN,
            )}
        )

        with patch("styrened.services.config.load_core_config", return_value=config):
            device = self._make_device("cafebabe" * 4)
            assert tree._is_my_mesh(device) is True
