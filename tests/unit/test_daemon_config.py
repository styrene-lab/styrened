"""Unit tests for YggdrasilConfig and I2PConfig models.

Covers:
- Default field values
- YggdrasilConfig YAML round-trip via _parse_yggdrasil
- I2PConfig YAML round-trip via _parse_i2p
- Unknown fields in YAML are silently ignored
- Invalid mode strings fall back to DISABLED
- CoreConfig has yggdrasil and i2p fields
"""
from __future__ import annotations


import pytest

from styrened.models.config import CoreConfig, GroupThreadFeatureTierConfig, GroupThreadsConfig, I2PConfig, YggdrasilConfig
from styrened.services.daemon_adapter import DaemonMode


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestYggdrasilConfigDefaults:
    def test_mode_is_disabled(self):
        cfg = YggdrasilConfig()
        assert cfg.mode is DaemonMode.DISABLED

    def test_binary_path_default(self):
        assert YggdrasilConfig().binary_path == "yggdrasil"

    def test_listen_port_default(self):
        assert YggdrasilConfig().listen_port == 9002

    def test_admin_socket_empty(self):
        assert YggdrasilConfig().admin_socket == ""

    def test_multicast_default_true(self):
        assert YggdrasilConfig().multicast is True

    def test_bootstrap_from_rns_default_true(self):
        assert YggdrasilConfig().bootstrap_from_rns is True

    def test_initial_peers_empty_list(self):
        cfg = YggdrasilConfig()
        assert cfg.initial_peers == []
        # Ensure separate instances don't share the same list
        cfg2 = YggdrasilConfig()
        cfg.initial_peers.append("tls://1.2.3.4:9001")
        assert cfg2.initial_peers == []


class TestI2PConfigDefaults:
    def test_mode_is_disabled(self):
        assert I2PConfig().mode is DaemonMode.DISABLED

    def test_http_proxy_host_default(self):
        assert I2PConfig().http_proxy_host == "127.0.0.1"

    def test_http_proxy_port_default(self):
        assert I2PConfig().http_proxy_port == 4444

    def test_managed_http_proxy_port_default(self):
        assert I2PConfig().managed_http_proxy_port == 4445

    def test_managed_i2pcontrol_port_default(self):
        assert I2PConfig().managed_i2pcontrol_port == 7651

    def test_b32_address_empty(self):
        assert I2PConfig().b32_address == ""

    def test_cache_ttl_default(self):
        assert I2PConfig().cache_ttl == 3600

    def test_fetch_timeout_default(self):
        assert I2PConfig().fetch_timeout == 45.0


# ---------------------------------------------------------------------------
# CoreConfig integration
# ---------------------------------------------------------------------------


class TestGroupThreadsConfigDefaults:
    def test_feature_tier_default(self):
        assert GroupThreadsConfig().feature_tier is GroupThreadFeatureTierConfig.BALANCED

    def test_first_run_auto_tier_default(self):
        assert GroupThreadsConfig().first_run_auto_tier is True


class TestCoreConfigHasFields:
    def test_yggdrasil_field_exists(self):
        cfg = CoreConfig()
        assert hasattr(cfg, "yggdrasil")
        assert isinstance(cfg.yggdrasil, YggdrasilConfig)

    def test_i2p_field_exists(self):
        cfg = CoreConfig()
        assert hasattr(cfg, "i2p")
        assert isinstance(cfg.i2p, I2PConfig)

    def test_group_threads_field_exists(self):
        cfg = CoreConfig()
        assert hasattr(cfg, "group_threads")
        assert isinstance(cfg.group_threads, GroupThreadsConfig)

    def test_separate_instances_independent(self):
        a = CoreConfig()
        b = CoreConfig()
        a.yggdrasil.initial_peers.append("tls://1.2.3.4:9001")
        assert b.yggdrasil.initial_peers == []


# ---------------------------------------------------------------------------
# YAML parsing helpers
# ---------------------------------------------------------------------------


def _make_core() -> CoreConfig:
    return CoreConfig()


def _parse_ygg(data: dict) -> YggdrasilConfig:
    from styrened.services.config import _parse_yggdrasil

    cfg = _make_core()
    _parse_yggdrasil(cfg, {"yggdrasil": data})
    return cfg.yggdrasil


def _parse_i2p_cfg(data: dict) -> I2PConfig:
    from styrened.services.config import _parse_i2p

    cfg = _make_core()
    _parse_i2p(cfg, {"i2p": data})
    return cfg.i2p


def _parse_group_threads_cfg(data: dict) -> GroupThreadsConfig:
    from styrened.services.config import _parse_group_threads

    cfg = _make_core()
    _parse_group_threads(cfg, {"group_threads": data})
    return cfg.group_threads


class TestYggdrasilYAMLParsing:
    def test_mode_adopt(self):
        y = _parse_ygg({"mode": "adopt"})
        assert y.mode is DaemonMode.ADOPT

    def test_mode_managed(self):
        y = _parse_ygg({"mode": "managed"})
        assert y.mode is DaemonMode.MANAGED

    def test_mode_invalid_falls_back_to_disabled(self):
        y = _parse_ygg({"mode": "bogus"})
        assert y.mode is DaemonMode.DISABLED

    def test_binary_path_parsed(self):
        y = _parse_ygg({"binary_path": "/usr/local/bin/yggdrasil"})
        assert y.binary_path == "/usr/local/bin/yggdrasil"

    def test_listen_port_parsed(self):
        y = _parse_ygg({"listen_port": 9100})
        assert y.listen_port == 9100

    def test_admin_socket_parsed(self):
        y = _parse_ygg({"admin_socket": "/tmp/ygg.sock"})
        assert y.admin_socket == "/tmp/ygg.sock"

    def test_multicast_false(self):
        y = _parse_ygg({"multicast": False})
        assert y.multicast is False

    def test_bootstrap_from_rns_false(self):
        y = _parse_ygg({"bootstrap_from_rns": False})
        assert y.bootstrap_from_rns is False

    def test_initial_peers_parsed(self):
        peers = ["tls://1.2.3.4:9001", "tls://5.6.7.8:9001"]
        y = _parse_ygg({"initial_peers": peers})
        assert y.initial_peers == peers

    def test_initial_peers_non_list_ignored(self):
        y = _parse_ygg({"initial_peers": "bad"})
        assert y.initial_peers == []

    def test_unknown_fields_ignored(self):
        """Extra keys in YAML must not raise errors."""
        y = _parse_ygg({"unknown_future_field": "value", "mode": "adopt"})
        assert y.mode is DaemonMode.ADOPT

    def test_empty_section_uses_defaults(self):
        y = _parse_ygg({})
        assert y.mode is DaemonMode.DISABLED
        assert y.listen_port == 9002

    def test_no_section_leaves_default(self):
        from styrened.services.config import _parse_yggdrasil

        cfg = _make_core()
        _parse_yggdrasil(cfg, {})  # no 'yggdrasil' key
        assert cfg.yggdrasil.mode is DaemonMode.DISABLED

    def test_non_dict_section_ignored(self):
        from styrened.services.config import _parse_yggdrasil

        cfg = _make_core()
        _parse_yggdrasil(cfg, {"yggdrasil": "not a dict"})
        assert cfg.yggdrasil.mode is DaemonMode.DISABLED


class TestGroupThreadsYAMLParsing:
    def test_feature_tier_parsed(self):
        g = _parse_group_threads_cfg({"feature_tier": "minimal"})
        assert g.feature_tier is GroupThreadFeatureTierConfig.MINIMAL

    def test_invalid_feature_tier_falls_back_to_balanced(self):
        g = _parse_group_threads_cfg({"feature_tier": "bogus"})
        assert g.feature_tier is GroupThreadFeatureTierConfig.BALANCED

    def test_policy_flags_parsed(self):
        g = _parse_group_threads_cfg(
            {
                "enabled": False,
                "bounded_retention": True,
                "auto_media_fetch": False,
                "metadata_first_sync": True,
                "background_catchup": False,
                "first_run_auto_tier": False,
            }
        )
        assert g.enabled is False
        assert g.bounded_retention is True
        assert g.auto_media_fetch is False
        assert g.metadata_first_sync is True
        assert g.background_catchup is False
        assert g.first_run_auto_tier is False


class TestI2PYAMLParsing:
    def test_mode_adopt(self):
        i = _parse_i2p_cfg({"mode": "adopt"})
        assert i.mode is DaemonMode.ADOPT

    def test_mode_managed(self):
        i = _parse_i2p_cfg({"mode": "managed"})
        assert i.mode is DaemonMode.MANAGED

    def test_mode_invalid_falls_back_to_disabled(self):
        i = _parse_i2p_cfg({"mode": "invalid"})
        assert i.mode is DaemonMode.DISABLED

    def test_http_proxy_host_parsed(self):
        i = _parse_i2p_cfg({"http_proxy_host": "192.168.1.1"})
        assert i.http_proxy_host == "192.168.1.1"

    def test_http_proxy_port_parsed(self):
        i = _parse_i2p_cfg({"http_proxy_port": 4448})
        assert i.http_proxy_port == 4448

    def test_managed_http_proxy_port_parsed(self):
        i = _parse_i2p_cfg({"managed_http_proxy_port": 4446})
        assert i.managed_http_proxy_port == 4446

    def test_managed_i2pcontrol_port_parsed(self):
        i = _parse_i2p_cfg({"managed_i2pcontrol_port": 7652})
        assert i.managed_i2pcontrol_port == 7652

    def test_b32_address_parsed(self):
        addr = "abc123def456.b32.i2p"
        i = _parse_i2p_cfg({"b32_address": addr})
        assert i.b32_address == addr

    def test_cache_ttl_parsed(self):
        i = _parse_i2p_cfg({"cache_ttl": 7200})
        assert i.cache_ttl == 7200

    def test_fetch_timeout_parsed(self):
        i = _parse_i2p_cfg({"fetch_timeout": 60.0})
        assert i.fetch_timeout == 60.0

    def test_unknown_fields_ignored(self):
        i = _parse_i2p_cfg({"future_option": True, "mode": "adopt"})
        assert i.mode is DaemonMode.ADOPT

    def test_empty_section_uses_defaults(self):
        i = _parse_i2p_cfg({})
        assert i.mode is DaemonMode.DISABLED
        assert i.http_proxy_port == 4444

    def test_no_section_leaves_default(self):
        from styrened.services.config import _parse_i2p

        cfg = _make_core()
        _parse_i2p(cfg, {})
        assert cfg.i2p.mode is DaemonMode.DISABLED

    def test_non_dict_section_ignored(self):
        from styrened.services.config import _parse_i2p

        cfg = _make_core()
        _parse_i2p(cfg, {"i2p": 42})
        assert cfg.i2p.mode is DaemonMode.DISABLED


# ---------------------------------------------------------------------------
# Round-trip: load_core_config with both sections
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_yggdrasil_round_trip_via_parse(self):
        from styrened.services.config import _parse_i2p, _parse_yggdrasil

        cfg = _make_core()
        _parse_yggdrasil(
            cfg,
            {
                "yggdrasil": {
                    "mode": "managed",
                    "binary_path": "/nix/store/xyz/bin/yggdrasil",
                    "listen_port": 9002,
                    "admin_socket": "/tmp/ygg-managed.sock",
                    "multicast": False,
                    "bootstrap_from_rns": True,
                    "initial_peers": ["tls://1.2.3.4:9001"],
                }
            },
        )
        y = cfg.yggdrasil
        assert y.mode is DaemonMode.MANAGED
        assert y.binary_path == "/nix/store/xyz/bin/yggdrasil"
        assert y.listen_port == 9002
        assert y.admin_socket == "/tmp/ygg-managed.sock"
        assert y.multicast is False
        assert y.bootstrap_from_rns is True
        assert y.initial_peers == ["tls://1.2.3.4:9001"]

    def test_i2p_round_trip_via_parse(self):
        from styrened.services.config import _parse_i2p

        cfg = _make_core()
        _parse_i2p(
            cfg,
            {
                "i2p": {
                    "mode": "adopt",
                    "http_proxy_host": "127.0.0.1",
                    "http_proxy_port": 4444,
                    "managed_http_proxy_port": 4445,
                    "managed_i2pcontrol_port": 7651,
                    "b32_address": "deadbeef.b32.i2p",
                    "cache_ttl": 1800,
                    "fetch_timeout": 30.0,
                }
            },
        )
        i = cfg.i2p
        assert i.mode is DaemonMode.ADOPT
        assert i.http_proxy_host == "127.0.0.1"
        assert i.http_proxy_port == 4444
        assert i.managed_http_proxy_port == 4445
        assert i.managed_i2pcontrol_port == 7651
        assert i.b32_address == "deadbeef.b32.i2p"
        assert i.cache_ttl == 1800
        assert i.fetch_timeout == 30.0

    def test_serialize_config_includes_yggdrasil_section(self):
        from styrened.services.config import serialize_config

        cfg = _make_core()
        cfg.yggdrasil.mode = DaemonMode.MANAGED
        cfg.yggdrasil.binary_path = "/nix/store/yggdrasil/bin/yggdrasil"
        cfg.yggdrasil.listen_port = 9002
        cfg.yggdrasil.admin_socket = "/tmp/ygg.sock"
        cfg.yggdrasil.multicast = False
        cfg.yggdrasil.bootstrap_from_rns = False
        cfg.yggdrasil.initial_peers = ["tls://1.2.3.4:9001"]

        data = serialize_config(cfg)

        assert data["yggdrasil"] == {
            "mode": "managed",
            "binary_path": "/nix/store/yggdrasil/bin/yggdrasil",
            "listen_port": 9002,
            "admin_socket": "/tmp/ygg.sock",
            "multicast": False,
            "bootstrap_from_rns": False,
            "peer_discovery": "eager",
            "initial_peers": ["tls://1.2.3.4:9001"],
        }

    def test_serialize_config_includes_i2p_section(self):
        from styrened.services.config import serialize_config

        cfg = _make_core()
        cfg.i2p.mode = DaemonMode.MANAGED
        cfg.i2p.http_proxy_host = "127.0.0.2"
        cfg.i2p.http_proxy_port = 4444
        cfg.i2p.managed_http_proxy_port = 4445
        cfg.i2p.managed_i2pcontrol_port = 7651
        cfg.i2p.b32_address = "deadbeef.b32.i2p"
        cfg.i2p.cache_ttl = 1800
        cfg.i2p.fetch_timeout = 30.0

        data = serialize_config(cfg)

        assert data["i2p"] == {
            "mode": "managed",
            "http_proxy_host": "127.0.0.2",
            "http_proxy_port": 4444,
            "managed_http_proxy_port": 4445,
            "managed_i2pcontrol_port": 7651,
            "b32_address": "deadbeef.b32.i2p",
            "cache_ttl": 1800,
            "fetch_timeout": 30.0,
        }
