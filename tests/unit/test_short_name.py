"""Unit tests for the short-name identity system.

Tests validation, announce format, NodeStore queries, resolve_name chain,
and config round-trip for the short_name field.
"""

import tempfile
from unittest.mock import MagicMock

import pytest

from styrened.models.config import IdentityConfig, validate_short_name
from styrened.models.mesh_device import (
    DeviceType,
    MeshDevice,
    create_mesh_device,
    parse_announce_data,
)
from styrened.services.node_store import NodeStore

# ---------------------------------------------------------------------------
# TestShortNameValidation
# ---------------------------------------------------------------------------


class TestShortNameValidation:
    """Tests for validate_short_name() function."""

    def test_valid_simple_name(self):
        assert validate_short_name("alice") is True

    def test_valid_with_digits(self):
        assert validate_short_name("node42") is True

    def test_valid_with_hyphens(self):
        assert validate_short_name("my-node") is True

    def test_valid_min_length_3(self):
        assert validate_short_name("abc") is True

    def test_valid_max_length_20(self):
        assert validate_short_name("a" * 20) is True

    def test_invalid_too_short_2_chars(self):
        assert validate_short_name("ab") is False

    def test_invalid_too_long_21_chars(self):
        assert validate_short_name("a" * 21) is False

    def test_invalid_leading_hyphen(self):
        assert validate_short_name("-alice") is False

    def test_invalid_trailing_hyphen(self):
        assert validate_short_name("alice-") is False

    def test_invalid_uppercase(self):
        assert validate_short_name("Alice") is False

    def test_invalid_spaces(self):
        assert validate_short_name("my node") is False

    def test_invalid_special_chars(self):
        assert validate_short_name("alice!") is False

    def test_invalid_empty_string(self):
        assert validate_short_name("") is False

    def test_valid_all_digits(self):
        assert validate_short_name("123") is True

    def test_valid_digit_hyphen_mix(self):
        assert validate_short_name("node-01-alpha") is True

    def test_invalid_single_char(self):
        assert validate_short_name("a") is False

    def test_invalid_underscore(self):
        assert validate_short_name("my_node") is False


# ---------------------------------------------------------------------------
# TestAnnounceFormatWithShortName
# ---------------------------------------------------------------------------


class TestAnnounceFormatWithShortName:
    """Tests for 6-field announce format generation and parsing."""

    def test_parse_6_field_announce(self):
        """6-field announce includes short_name."""
        app_data = b"styrene:Alice:0.5.0:node:abc123def456abc123def456abc12345:alice"
        name, dtype, caps, version, lxmf, short_name, _fp = parse_announce_data(app_data)
        assert name == "Alice"
        assert dtype == DeviceType.STYRENE_NODE
        assert version == "0.5.0"
        assert lxmf == "abc123def456abc123def456abc12345"
        assert short_name == "alice"

    def test_parse_5_field_announce_backward_compat(self):
        """5-field announce returns None for short_name (backward compat)."""
        app_data = b"styrene:Alice:0.5.0:node:abc123def456abc123def456abc12345"
        name, dtype, caps, version, lxmf, short_name, _fp = parse_announce_data(app_data)
        assert name == "Alice"
        assert lxmf == "abc123def456abc123def456abc12345"
        assert short_name is None

    def test_parse_6_field_empty_short_name(self):
        """6-field with empty short_name returns None."""
        app_data = b"styrene:Alice:0.5.0:node:abc123def456abc123def456abc12345:"
        name, dtype, caps, version, lxmf, short_name, _fp = parse_announce_data(app_data)
        assert short_name is None

    def test_parse_4_field_legacy(self):
        """4-field legacy announce returns None for lxmf and short_name."""
        app_data = b"styrene:Alice:0.5.0:node"
        name, dtype, caps, version, lxmf, short_name, _fp = parse_announce_data(app_data)
        assert name == "Alice"
        assert lxmf is None
        assert short_name is None

    def test_parse_non_styrene_returns_none_short_name(self):
        """Non-Styrene announces return None short_name in 6-tuple."""
        app_data = b"rnode:my-rnode"
        result = parse_announce_data(app_data)
        assert len(result) == 7
        assert result[5] is None  # short_name

    def test_parse_empty_app_data(self):
        """Empty app_data returns 6-tuple with Nones."""
        result = parse_announce_data(None)
        assert len(result) == 7
        assert result[5] is None

    def test_create_mesh_device_with_short_name(self):
        """create_mesh_device passes through short_name from announce data."""
        app_data = b"styrene:Alice:0.5.0:node:abc123def456abc123def456abc12345:alice"
        device = create_mesh_device(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            app_data=app_data,
        )
        assert device.short_name == "alice"

    def test_create_mesh_device_without_short_name(self):
        """create_mesh_device sets short_name=None for old-format announces."""
        app_data = b"styrene:Alice:0.5.0:node:abc123def456abc123def456abc12345"
        device = create_mesh_device(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            app_data=app_data,
        )
        assert device.short_name is None


# ---------------------------------------------------------------------------
# TestNodeStoreShortName
# ---------------------------------------------------------------------------


class TestNodeStoreShortName:
    """Tests for NodeStore short_name persistence and queries."""

    @pytest.fixture
    def node_store(self, tmp_path):
        db_path = tmp_path / "nodes.db"
        return NodeStore(db_path=db_path)

    def _make_device(
        self,
        dest_hash: str = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        identity_hash: str = "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
        name: str = "Alice",
        short_name: str | None = "alice",
        lxmf_dest: str | None = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ) -> MeshDevice:
        return MeshDevice(
            destination_hash=dest_hash,
            identity_hash=identity_hash,
            name=name,
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000000,
            short_name=short_name,
            lxmf_destination_hash=lxmf_dest,
        )

    def test_save_and_retrieve_short_name(self, node_store):
        """Saved short_name is retrievable."""
        device = self._make_device(short_name="alice")
        node_store.save_node(device)
        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.short_name == "alice"

    def test_save_null_short_name(self, node_store):
        """Null short_name is stored and retrieved as None."""
        device = self._make_device(short_name=None)
        node_store.save_node(device)
        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.short_name is None

    def test_schema_migration_adds_column(self, tmp_path):
        """Opening an old DB without short_name column still works."""
        import sqlite3

        db_path = tmp_path / "legacy.db"
        # Create a legacy schema without short_name
        conn = sqlite3.Connection(str(db_path))
        conn.execute("""
            CREATE TABLE nodes (
                destination_hash TEXT PRIMARY KEY,
                identity_hash TEXT NOT NULL,
                name TEXT,
                device_type TEXT,
                last_announce INTEGER,
                announce_count INTEGER DEFAULT 1,
                capabilities TEXT,
                version TEXT,
                lxmf_destination_hash TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
                "OldNode",
                "styrene_node",
                1000000,
                1,
                None,
                "0.4.0",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                1000000,
                1000000,
            ),
        )
        conn.commit()
        conn.close()

        # NodeStore should migrate and still read existing rows
        store = NodeStore(db_path=db_path)
        result = store.get_node_by_destination("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is not None
        assert result.name == "OldNode"
        assert result.short_name is None

    def test_get_nodes_by_short_name_exact(self, node_store):
        """get_nodes_by_short_name returns exact case-insensitive matches."""
        device = self._make_device(short_name="alice")
        node_store.save_node(device)

        results = node_store.get_nodes_by_short_name("Alice")
        assert len(results) == 1
        assert results[0].short_name == "alice"

    def test_get_nodes_by_short_name_no_match(self, node_store):
        """get_nodes_by_short_name returns empty for no match."""
        device = self._make_device(short_name="alice")
        node_store.save_node(device)

        results = node_store.get_nodes_by_short_name("bob")
        assert len(results) == 0

    def test_get_nodes_by_short_name_prefix(self, node_store):
        """get_nodes_by_short_name_prefix matches prefixes."""
        device = self._make_device(short_name="alice")
        node_store.save_node(device)

        results = node_store.get_nodes_by_short_name_prefix("ali")
        assert len(results) == 1
        assert results[0].short_name == "alice"

    def test_get_nodes_by_short_name_prefix_multiple(self, node_store):
        """get_nodes_by_short_name_prefix returns all prefix matches."""
        node_store.save_node(
            self._make_device(
                dest_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
                short_name="alice",
            )
        )
        node_store.save_node(
            self._make_device(
                dest_hash="11112222333344445555666677778888",
                identity_hash="88887777666655554444333322221111",
                short_name="alicia",
            )
        )

        results = node_store.get_nodes_by_short_name_prefix("ali")
        assert len(results) == 2

    def test_update_short_name_on_re_announce(self, node_store):
        """Re-announcing with new short_name updates the stored value."""
        device = self._make_device(short_name="alice")
        node_store.save_node(device)

        updated = self._make_device(short_name="alice-v2")
        node_store.save_node(updated)

        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.short_name == "alice-v2"


# ---------------------------------------------------------------------------
# TestResolveNameWithShortName
# ---------------------------------------------------------------------------


class TestResolveNameWithShortName:
    """Tests for the 6-step resolve_name chain with short_name."""

    @pytest.fixture
    def db_engine(self):
        from styrened.models.messages import init_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return init_db(f.name)

    def _make_node_store_mock(
        self, nodes: list[MeshDevice] | None = None
    ) -> MagicMock:
        mock = MagicMock()
        mock.get_all_nodes.return_value = nodes or []
        mock.get_nodes_by_short_name.return_value = []
        mock.get_nodes_by_short_name_prefix.return_value = []
        return mock

    def test_alias_takes_priority_over_short_name(self, db_engine):
        """Step 1 (exact alias) beats step 3 (short_name)."""
        from styrened.services.contacts import ContactService

        node = MagicMock()
        node.short_name = "alice"
        node.lxmf_destination_hash = "nodestore_lxmf_hash_1234567890ab"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = [node]

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        service.set_alias("contact_lxmf_hash_1234567890ab", "alice")

        result = service.resolve_name("alice")
        assert result == "contact_lxmf_hash_1234567890ab"

    def test_short_name_exact_match(self, db_engine):
        """Step 3: exact short_name match resolves to lxmf_dest."""
        from styrened.services.contacts import ContactService

        node = MagicMock()
        node.short_name = "bob"
        node.lxmf_destination_hash = "beef1234beef1234beef1234beef1234"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = [node]

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        result = service.resolve_name("bob")
        assert result == "beef1234beef1234beef1234beef1234"

    def test_short_name_exact_ambiguous_returns_none(self, db_engine):
        """Step 3: multiple exact short_name matches returns None."""
        from styrened.services.contacts import ContactService

        node1 = MagicMock()
        node1.short_name = "bob"
        node1.lxmf_destination_hash = "aaaa1234aaaa1234aaaa1234aaaa1234"

        node2 = MagicMock()
        node2.short_name = "bob"
        node2.lxmf_destination_hash = "bbbb1234bbbb1234bbbb1234bbbb1234"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = [node1, node2]

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        # Falls through to step 4+, but exact short_name is ambiguous
        result = service.resolve_name("bob")
        # Should not resolve from short_name (ambiguous), may fall through
        # to announce name match. With no announce name match, returns None.
        mock_store.get_all_nodes.return_value = []
        result = service.resolve_name("bob")
        assert result is None

    def test_short_name_prefix_match_unique(self, db_engine):
        """Step 4: unique short_name prefix resolves."""
        from styrened.services.contacts import ContactService

        node = MagicMock()
        node.short_name = "charlie"
        node.lxmf_destination_hash = "cccc1234cccc1234cccc1234cccc1234"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = []
        mock_store.get_nodes_by_short_name_prefix.return_value = [node]

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        result = service.resolve_name("char")
        assert result == "cccc1234cccc1234cccc1234cccc1234"

    def test_short_name_prefix_ambiguous_falls_through(self, db_engine):
        """Step 4: ambiguous prefix falls through to announce name."""
        from styrened.services.contacts import ContactService

        node1 = MagicMock()
        node1.short_name = "charlie"
        node1.lxmf_destination_hash = "cccc1234cccc1234cccc1234cccc1234"

        node2 = MagicMock()
        node2.short_name = "charles"
        node2.lxmf_destination_hash = "dddd1234dddd1234dddd1234dddd1234"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = []
        mock_store.get_nodes_by_short_name_prefix.return_value = [node1, node2]
        mock_store.get_all_nodes.return_value = []

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        result = service.resolve_name("char")
        assert result is None  # Falls through, no announce name match

    def test_short_name_skips_nodes_without_lxmf(self, db_engine):
        """Short name match without lxmf_destination_hash is skipped."""
        from styrened.services.contacts import ContactService

        node = MagicMock()
        node.short_name = "dave"
        node.lxmf_destination_hash = None

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = [node]
        mock_store.get_all_nodes.return_value = []

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        result = service.resolve_name("dave")
        assert result is None

    def test_announce_name_still_works(self, db_engine):
        """Steps 5-6: announce name resolution still works after short_name steps."""
        from styrened.services.contacts import ContactService

        mock_node = MagicMock()
        mock_node.name = "BobNode"
        mock_node.short_name = None
        mock_node.lxmf_destination_hash = "beef1234beef1234beef1234beef1234"

        mock_store = self._make_node_store_mock()
        mock_store.get_nodes_by_short_name.return_value = []
        mock_store.get_nodes_by_short_name_prefix.return_value = []
        mock_store.get_all_nodes.return_value = [mock_node]

        service = ContactService(db_engine=db_engine, node_store=mock_store)
        result = service.resolve_name("BobNode")
        assert result == "beef1234beef1234beef1234beef1234"


# ---------------------------------------------------------------------------
# TestConfigShortName
# ---------------------------------------------------------------------------


class TestConfigShortName:
    """Tests for short_name in config model and YAML round-trip."""

    def test_identity_config_default_none(self):
        """IdentityConfig.short_name defaults to None."""
        config = IdentityConfig()
        assert config.short_name is None

    def test_identity_config_with_short_name(self):
        """IdentityConfig accepts short_name."""
        config = IdentityConfig(short_name="alice")
        assert config.short_name == "alice"

    def test_config_load_with_short_name(self, tmp_path):
        """Loading config with short_name parses correctly."""
        from styrened.services.config import load_core_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "identity:\n"
            '  display_name: "Alice"\n'
            '  short_name: "alice"\n'
        )
        config = load_core_config(config_file)
        assert config.identity.short_name == "alice"

    def test_config_load_without_short_name(self, tmp_path):
        """Loading config without short_name leaves it as None."""
        from styrened.services.config import load_core_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "identity:\n"
            '  display_name: "Alice"\n'
        )
        config = load_core_config(config_file)
        assert config.identity.short_name is None

    def test_config_load_invalid_short_name_warns(self, tmp_path, caplog):
        """Loading config with invalid short_name logs a warning."""
        import logging

        from styrened.services.config import load_core_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "identity:\n"
            '  display_name: "Alice"\n'
            '  short_name: "INVALID NAME!"\n'
        )
        with caplog.at_level(logging.WARNING):
            config = load_core_config(config_file)
        assert config.identity.short_name is None
        assert "short_name" in caplog.text.lower() or "invalid" in caplog.text.lower()

    def test_config_save_with_short_name(self, tmp_path):
        """Saving config with short_name persists it."""
        import yaml

        from styrened.models.config import CoreConfig
        from styrened.services.config import save_core_config

        config = CoreConfig()
        config.identity.short_name = "alice"

        config_file = tmp_path / "config.yaml"
        save_core_config(config, config_file)

        with open(config_file) as f:
            data = yaml.safe_load(f)

        assert data["identity"]["short_name"] == "alice"

    def test_config_save_without_short_name(self, tmp_path):
        """Saving config without short_name omits it from YAML."""
        import yaml

        from styrened.models.config import CoreConfig
        from styrened.services.config import save_core_config

        config = CoreConfig()
        config.identity.short_name = None

        config_file = tmp_path / "config.yaml"
        save_core_config(config, config_file)

        with open(config_file) as f:
            data = yaml.safe_load(f)

        assert "short_name" not in data.get("identity", {})

    def test_config_round_trip(self, tmp_path):
        """Config save -> load round-trip preserves short_name."""
        from styrened.models.config import CoreConfig
        from styrened.services.config import load_core_config, save_core_config

        config = CoreConfig()
        config.identity.short_name = "roundtrip"
        config.identity.display_name = "Round Trip Node"

        config_file = tmp_path / "config.yaml"
        save_core_config(config, config_file)
        loaded = load_core_config(config_file)

        assert loaded.identity.short_name == "roundtrip"
        assert loaded.identity.display_name == "Round Trip Node"


# ---------------------------------------------------------------------------
# TestDeviceInfoShortName
# ---------------------------------------------------------------------------


class TestDeviceInfoShortName:
    """Tests for short_name in IPC DeviceInfo."""

    def test_device_info_to_dict_includes_short_name(self):
        from styrened.ipc.messages import DeviceInfo

        info = DeviceInfo(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            name="Alice",
            device_type="styrene_node",
            status="active",
            is_styrene_node=True,
            lxmf_destination_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            last_announce=1000.0,
            announce_count=1,
            short_name="alice",
        )
        d = info.to_dict()
        assert d["short_name"] == "alice"

    def test_device_info_from_dict_reads_short_name(self):
        from styrened.ipc.messages import DeviceInfo

        data = {
            "destination_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "identity_hash": "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            "name": "Alice",
            "device_type": "styrene_node",
            "status": "active",
            "is_styrene_node": True,
            "lxmf_destination_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "last_announce": 1000.0,
            "announce_count": 1,
            "short_name": "alice",
        }
        info = DeviceInfo.from_dict(data)
        assert info.short_name == "alice"

    def test_device_info_from_dict_missing_short_name(self):
        from styrened.ipc.messages import DeviceInfo

        data = {
            "destination_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "identity_hash": "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            "name": "Alice",
        }
        info = DeviceInfo.from_dict(data)
        assert info.short_name is None

    def test_device_info_from_mesh_device(self):
        from styrened.ipc.messages import DeviceInfo

        device = MeshDevice(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            name="Alice",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
            short_name="alice",
        )
        info = DeviceInfo.from_mesh_device(device)
        assert info.short_name == "alice"
