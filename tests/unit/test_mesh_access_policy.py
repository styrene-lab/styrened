"""Unit tests for mesh admission control (default-deny / allowlist policy).

Tests cover:
- StyreneAnnounceHandler respects OPEN vs ALLOWLIST mode
- Config round-trip (load + save) for discovery.access_mode and allowed_peers
- Daemon wires config fields to start_discovery()
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from styrened.models.config import (
    CoreConfig,
    DiscoveryConfig,
    MeshAccessMode,
    ReticulumConfig,
)
from styrened.services.reticulum import StyreneAnnounceHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_IDENTITY = "a" * 32
BLOCKED_IDENTITY = "b" * 32
DEST_HASH_HEX = "c" * 32


def _make_identity(identity_hash_hex: str) -> MagicMock:
    """Create a minimal mock RNS.Identity."""
    mock_id = MagicMock()
    mock_id.hash = bytes.fromhex(identity_hash_hex)
    mock_id.get_public_key.return_value = b"\x00" * 32
    return mock_id


def _call_received_announce(
    handler: StyreneAnnounceHandler,
    identity_hash_hex: str = ALLOWED_IDENTITY,
    dest_hash_hex: str = DEST_HASH_HEX,
) -> None:
    """Drive the handler with a fake announce, bypassing all RNS I/O.

    We patch the module-level ``RNS`` reference inside
    ``styrened.services.reticulum`` (not the real ``RNS`` package) so the
    handler's calls to ``RNS.Identity.remember``, ``RNS.Identity.recall``,
    ``RNS.Destination.hash``, and ``RNS.Transport.path_table`` all go to a
    MagicMock without requiring a real Reticulum instance.
    """
    announced_identity = _make_identity(identity_hash_hex)

    mock_rns = MagicMock()
    mock_rns.Identity.recall.return_value = MagicMock()
    mock_rns.Destination.hash.side_effect = Exception("no match")
    mock_rns.Transport.path_table = {}

    with patch("styrened.services.reticulum.RNS", mock_rns):
        handler.received_announce(
            destination_hash=bytes.fromhex(dest_hash_hex),
            announced_identity=announced_identity,
            app_data=None,
        )


# ---------------------------------------------------------------------------
# StyreneAnnounceHandler — open mode
# ---------------------------------------------------------------------------


class TestOpenMode:
    """OPEN mode: every announcing node is accepted (legacy behaviour)."""

    def test_open_mode_admits_any_identity(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.OPEN,
        )
        _call_received_announce(handler, identity_hash_hex=BLOCKED_IDENTITY)
        assert DEST_HASH_HEX in handler.discovered_devices
        callback.assert_called_once()

    def test_default_mode_is_open(self):
        handler = StyreneAnnounceHandler()
        assert handler.access_mode == MeshAccessMode.OPEN

    def test_none_access_mode_defaults_to_open(self):
        handler = StyreneAnnounceHandler(access_mode=None)
        assert handler.access_mode == MeshAccessMode.OPEN

    def test_open_mode_with_empty_allowed_peers_still_admits(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.OPEN,
            allowed_peers=set(),
        )
        _call_received_announce(handler)
        assert DEST_HASH_HEX in handler.discovered_devices

    def test_path_response_skipped_before_admission_check(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.OPEN,
        )
        # is_path_response=True must short-circuit before anything else
        handler.received_announce(
            destination_hash=bytes.fromhex(DEST_HASH_HEX),
            announced_identity=_make_identity(ALLOWED_IDENTITY),
            app_data=None,
            is_path_response=True,
        )
        assert DEST_HASH_HEX not in handler.discovered_devices
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# StyreneAnnounceHandler — allowlist mode
# ---------------------------------------------------------------------------


class TestAllowlistMode:
    """ALLOWLIST mode: only identity hashes in allowed_peers are admitted."""

    def test_allowlisted_identity_is_admitted(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={ALLOWED_IDENTITY},
        )
        _call_received_announce(handler, identity_hash_hex=ALLOWED_IDENTITY)
        assert DEST_HASH_HEX in handler.discovered_devices
        callback.assert_called_once()

    def test_unknown_identity_is_blocked(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={ALLOWED_IDENTITY},
        )
        _call_received_announce(handler, identity_hash_hex=BLOCKED_IDENTITY)
        assert DEST_HASH_HEX not in handler.discovered_devices
        callback.assert_not_called()

    def test_empty_allowlist_blocks_everyone(self):
        callback = MagicMock()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers=set(),
        )
        _call_received_announce(handler)
        assert DEST_HASH_HEX not in handler.discovered_devices
        callback.assert_not_called()

    def test_allowlist_match_is_case_insensitive(self):
        """Hashes stored upper-case in allowed_peers still match lower-case announce."""
        callback = MagicMock()
        upper_hash = ALLOWED_IDENTITY.upper()
        handler = StyreneAnnounceHandler(
            callback=callback,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={upper_hash},
        )
        # Announce comes in with lower-case identity hash (from .hex())
        _call_received_announce(handler, identity_hash_hex=ALLOWED_IDENTITY.lower())
        assert DEST_HASH_HEX in handler.discovered_devices

    def test_multiple_allowed_peers(self):
        peer_a = "a" * 32
        peer_b = "b" * 32
        dest_a = "c" * 32
        dest_b = "d" * 32

        handler = StyreneAnnounceHandler(
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={peer_a, peer_b},
        )

        _call_received_announce(handler, identity_hash_hex=peer_a, dest_hash_hex=dest_a)
        _call_received_announce(handler, identity_hash_hex=peer_b, dest_hash_hex=dest_b)

        assert dest_a in handler.discovered_devices
        assert dest_b in handler.discovered_devices

    def test_blocked_node_not_persisted_to_store(self):
        """Blocked announces must not reach the node_store."""
        node_store = MagicMock()
        handler = StyreneAnnounceHandler(
            node_store=node_store,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={ALLOWED_IDENTITY},
        )
        _call_received_announce(handler, identity_hash_hex=BLOCKED_IDENTITY)
        node_store.save_node.assert_not_called()

    def test_allowed_node_is_persisted_to_store(self):
        node_store = MagicMock()
        handler = StyreneAnnounceHandler(
            node_store=node_store,
            access_mode=MeshAccessMode.ALLOWLIST,
            allowed_peers={ALLOWED_IDENTITY},
        )
        _call_received_announce(handler, identity_hash_hex=ALLOWED_IDENTITY)
        node_store.save_node.assert_called_once()


# ---------------------------------------------------------------------------
# Config model defaults
# ---------------------------------------------------------------------------


class TestDiscoveryConfigDefaults:
    def test_default_access_mode_is_open(self):
        cfg = DiscoveryConfig()
        assert cfg.access_mode == MeshAccessMode.OPEN

    def test_default_allowed_peers_is_empty_set(self):
        cfg = DiscoveryConfig()
        assert cfg.allowed_peers == set()


# ---------------------------------------------------------------------------
# Config serialization round-trip
# ---------------------------------------------------------------------------


class TestConfigRoundTrip:
    def test_open_mode_round_trip(self, tmp_path):
        from styrened.services.config import load_core_config, save_core_config

        config = CoreConfig()
        config.discovery.access_mode = MeshAccessMode.OPEN
        config.discovery.allowed_peers = set()

        path = tmp_path / "config.yaml"
        save_core_config(config, path)
        loaded = load_core_config(path)

        assert loaded.discovery.access_mode == MeshAccessMode.OPEN
        assert loaded.discovery.allowed_peers == set()

    def test_allowlist_mode_round_trip(self, tmp_path):
        from styrened.services.config import load_core_config, save_core_config

        config = CoreConfig()
        config.discovery.access_mode = MeshAccessMode.ALLOWLIST
        config.discovery.allowed_peers = {ALLOWED_IDENTITY, BLOCKED_IDENTITY}

        path = tmp_path / "config.yaml"
        save_core_config(config, path)
        loaded = load_core_config(path)

        assert loaded.discovery.access_mode == MeshAccessMode.ALLOWLIST
        assert ALLOWED_IDENTITY in loaded.discovery.allowed_peers
        assert BLOCKED_IDENTITY in loaded.discovery.allowed_peers

    def test_invalid_access_mode_defaults_to_open(self, tmp_path):
        """Unknown access_mode string in YAML falls back to OPEN."""
        import yaml

        from styrened.services.config import load_core_config

        data = {"discovery": {"access_mode": "invalid_value"}}
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(data))

        loaded = load_core_config(path)
        assert loaded.discovery.access_mode == MeshAccessMode.OPEN

    def test_allowed_peers_are_normalized_to_lowercase(self, tmp_path):
        import yaml

        from styrened.services.config import load_core_config

        upper = ALLOWED_IDENTITY.upper()
        data = {"discovery": {"access_mode": "allowlist", "allowed_peers": [upper]}}
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(data))

        loaded = load_core_config(path)
        assert ALLOWED_IDENTITY.lower() in loaded.discovery.allowed_peers
        # Upper-case version must NOT appear (normalized)
        assert upper not in loaded.discovery.allowed_peers


# ---------------------------------------------------------------------------
# start_discovery wiring
# ---------------------------------------------------------------------------


class TestStartDiscoveryWiring:
    """start_discovery() must forward access_mode and allowed_peers to handler."""

    def test_start_discovery_passes_access_mode(self):
        from styrened.services import reticulum as rns_svc

        # Reset global state
        rns_svc._announce_handler = None

        with (
            patch.object(rns_svc, "RNS") as mock_rns,
        ):
            mock_rns.Transport.register_announce_handler = MagicMock()
            rns_svc.start_discovery(
                access_mode=MeshAccessMode.ALLOWLIST,
                allowed_peers={ALLOWED_IDENTITY},
            )

        handler = rns_svc._announce_handler
        assert handler is not None
        assert handler.access_mode == MeshAccessMode.ALLOWLIST
        assert ALLOWED_IDENTITY in handler._allowed_peers

        # Cleanup
        rns_svc._announce_handler = None

    def test_start_discovery_defaults_to_open(self):
        from styrened.services import reticulum as rns_svc

        rns_svc._announce_handler = None

        with patch.object(rns_svc, "RNS") as mock_rns:
            mock_rns.Transport.register_announce_handler = MagicMock()
            rns_svc.start_discovery()

        handler = rns_svc._announce_handler
        assert handler is not None
        assert handler.access_mode == MeshAccessMode.OPEN

        rns_svc._announce_handler = None
