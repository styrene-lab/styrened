"""Tests for block-ops redesign: peer_blocks as authoritative block store.

Covers:
- block_peer() write order: peer_blocks first, then RBAC, then contacts best-effort
- block_peer() returns False when peer_blocks write fails (RBAC not touched)
- unblock_peer() returns False when identity_hash not in peer_blocks
- unblock_peer() happy path: removes from peer_blocks, RBAC, and contacts
- _load_peer_blocks() returns identity_hash list from peer_blocks
- _seed_blocks_to_rbac() seeded into RBAC, no duplicates, invalidate_cache() once
- get_blocked_peers() reads peer_blocks (identity_hash keyed, no peer_hash key)
- _handle_lxmf_message() resolves identity_hash via NodeStore before RBAC check
"""
from __future__ import annotations


import time
from unittest.mock import MagicMock, patch, call

import pytest
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine(tmp_path):
    """SQLite DB with peer_blocks + contacts tables."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE peer_blocks ("
                "identity_hash TEXT PRIMARY KEY, "
                "blocked_at REAL NOT NULL, "
                "reason TEXT"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE contacts ("
                "identity_hash TEXT PRIMARY KEY, "
                "alias VARCHAR(100) NOT NULL, "
                "notes VARCHAR(500), "
                "blocked BOOLEAN NOT NULL DEFAULT 0, "
                "blocked_at REAL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            )
        )
        conn.commit()
    return engine, db_path


@pytest.fixture
def service(db_engine):
    """LXMFService with RBAC mock and patched DB path."""
    _, db_path = db_engine
    from styrened.services.lxmf_service import LXMFService
    from styrened.models.rbac import RBACPolicy, Role

    svc = LXMFService()
    policy = MagicMock(spec=RBACPolicy)
    policy.resolve_role.return_value = Role.PEER  # not blocked by default
    svc.set_rbac_policy(policy)

    with patch("styrened.paths") as mock_paths:
        mock_paths.messages_db.return_value = db_path
        yield svc, db_engine, policy


# ---------------------------------------------------------------------------
# block_peer()
# ---------------------------------------------------------------------------


class TestBlockPeer:
    def test_returns_true_on_success(self, service):
        svc, (engine, _), policy = service
        result = svc.block_peer("a" * 64)
        assert result is True

    def test_writes_to_peer_blocks(self, service):
        svc, (engine, _), policy = service
        ih = "b" * 64
        svc.block_peer(ih)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT identity_hash FROM peer_blocks WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchone()
        assert row is not None

    def test_updates_rbac_after_peer_blocks(self, service):
        svc, _, policy = service
        ih = "c" * 64
        svc.block_peer(ih)
        policy.block.assert_called_once_with(ih)

    def test_does_not_update_rbac_on_peer_blocks_failure(self, service):
        """If peer_blocks write fails, RBAC must NOT be updated."""
        svc, (engine, db_path), policy = service
        # Break the DB path so peer_blocks INSERT fails
        with patch("styrened.paths") as bad_paths:
            bad_paths.messages_db.return_value = "/nonexistent/path/x.db"
            result = svc.block_peer("d" * 64)
        assert result is False
        policy.block.assert_not_called()

    def test_creates_contacts_entry_best_effort(self, service):
        svc, (engine, _), policy = service
        ih = "e" * 64
        svc.block_peer(ih, alias="Alice")
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT alias, blocked FROM contacts WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchone()
        assert row is not None
        assert row[1] == 1

    def test_upserts_existing_contact(self, service):
        svc, (engine, db_path), policy = service
        ih = "f" * 64
        now = time.time()
        # Pre-insert contact
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO contacts (identity_hash, alias, blocked, created_at, updated_at) "
                    "VALUES (:h, 'existing', 0, :t, :t)"
                ),
                {"h": ih, "t": now},
            )
            conn.commit()
        svc.block_peer(ih)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT blocked FROM contacts WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchone()
        assert row[0] == 1

    def test_upserts_peer_blocks_if_already_blocked(self, service):
        """Second block_peer call should update blocked_at (upsert)."""
        svc, (engine, _), policy = service
        ih = "g" * 64
        svc.block_peer(ih)
        time.sleep(0.01)
        svc.block_peer(ih)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT identity_hash FROM peer_blocks WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchall()
        assert len(rows) == 1  # still one row, not duplicated


# ---------------------------------------------------------------------------
# unblock_peer()
# ---------------------------------------------------------------------------


class TestUnblockPeer:
    def _insert_block(self, engine, ih):
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                ),
                {"h": ih, "t": time.time()},
            )
            conn.commit()

    def test_returns_false_if_not_in_peer_blocks(self, service):
        svc, _, policy = service
        result = svc.unblock_peer("z" * 64)
        assert result is False
        policy.unblock.assert_not_called()

    def test_returns_true_on_success(self, service):
        svc, (engine, _), policy = service
        ih = "h" * 64
        self._insert_block(engine, ih)
        result = svc.unblock_peer(ih)
        assert result is True

    def test_deletes_from_peer_blocks(self, service):
        svc, (engine, _), policy = service
        ih = "i" * 64
        self._insert_block(engine, ih)
        svc.unblock_peer(ih)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT identity_hash FROM peer_blocks WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchone()
        assert row is None

    def test_calls_rbac_unblock(self, service):
        svc, (engine, _), policy = service
        ih = "j" * 64
        self._insert_block(engine, ih)
        svc.unblock_peer(ih)
        policy.unblock.assert_called_once_with(ih)

    def test_clears_contacts_blocked_flag(self, service):
        svc, (engine, _), policy = service
        ih = "k" * 64
        self._insert_block(engine, ih)
        now = time.time()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO contacts (identity_hash, alias, blocked, blocked_at, created_at, updated_at) "
                    "VALUES (:h, 'test', 1, :t, :t, :t)"
                ),
                {"h": ih, "t": now},
            )
            conn.commit()
        svc.unblock_peer(ih)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT blocked FROM contacts WHERE identity_hash = :h"),
                {"h": ih},
            ).fetchone()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# _load_peer_blocks()
# ---------------------------------------------------------------------------


class TestLoadPeerBlocks:
    def test_returns_empty_list_when_no_blocks(self, service):
        svc, _, _ = service
        result = svc._load_peer_blocks()
        assert result == []

    def test_returns_identity_hashes(self, service):
        svc, (engine, _), _ = service
        expected = ["a" * 64, "b" * 64]
        with engine.connect() as conn:
            for ih in expected:
                conn.execute(
                    text(
                        "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                    ),
                    {"h": ih, "t": time.time()},
                )
            conn.commit()
        result = svc._load_peer_blocks()
        assert sorted(result) == sorted(expected)

    def test_returns_empty_on_missing_table(self, tmp_path):
        """Gracefully returns [] when peer_blocks table doesn't exist."""
        db_path = tmp_path / "empty.db"
        # Create DB with no tables
        engine = create_engine(f"sqlite:///{db_path}")
        engine.dispose()

        from styrened.services.lxmf_service import LXMFService
        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            result = svc._load_peer_blocks()
        assert result == []


# ---------------------------------------------------------------------------
# _seed_blocks_to_rbac()
# ---------------------------------------------------------------------------


class TestSeedBlocksToRbac:
    def test_no_op_when_peer_blocks_empty(self, service):
        svc, _, policy = service
        svc._seed_blocks_to_rbac()
        policy.block.assert_not_called()
        policy.invalidate_cache.assert_not_called()

    def test_seeds_new_blocks(self, service):
        svc, (engine, _), policy = service
        from styrened.models.rbac import Role
        policy.resolve_role.return_value = Role.PEER  # not already blocked

        ihs = ["c" * 64, "d" * 64]
        with engine.connect() as conn:
            for ih in ihs:
                conn.execute(
                    text(
                        "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                    ),
                    {"h": ih, "t": time.time()},
                )
            conn.commit()

        svc._seed_blocks_to_rbac()
        assert policy.block.call_count == 2
        policy.invalidate_cache.assert_called_once()

    def test_skips_already_blocked_in_rbac(self, service):
        """Does not duplicate entries already blocked in RBAC."""
        svc, (engine, _), policy = service
        from styrened.models.rbac import Role
        ih = "e" * 64
        # Already blocked in RBAC
        policy.resolve_role.return_value = Role.BLOCKED

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                ),
                {"h": ih, "t": time.time()},
            )
            conn.commit()

        svc._seed_blocks_to_rbac()
        policy.block.assert_not_called()
        # invalidate_cache is not called because nothing was added
        policy.invalidate_cache.assert_not_called()

    def test_calls_invalidate_cache_once_regardless_of_count(self, service):
        """invalidate_cache() called exactly once even for many entries."""
        svc, (engine, _), policy = service
        from styrened.models.rbac import Role
        policy.resolve_role.return_value = Role.PEER

        with engine.connect() as conn:
            for i in range(5):
                ih = str(i) * 64
                conn.execute(
                    text(
                        "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                    ),
                    {"h": ih, "t": time.time()},
                )
            conn.commit()

        svc._seed_blocks_to_rbac()
        policy.invalidate_cache.assert_called_once()


# ---------------------------------------------------------------------------
# get_blocked_peers()
# ---------------------------------------------------------------------------


class TestGetBlockedPeers:
    def test_returns_empty_when_no_blocks(self, service):
        svc, _, _ = service
        result = svc.get_blocked_peers()
        assert result == []

    def test_returns_identity_hash_keyed_dicts(self, service):
        svc, (engine, _), _ = service
        ih = "f" * 64
        ts = time.time()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                ),
                {"h": ih, "t": ts},
            )
            conn.commit()

        result = svc.get_blocked_peers()
        assert len(result) == 1
        entry = result[0]
        assert entry["identity_hash"] == ih
        assert "peer_hash" not in entry
        assert entry["blocked_at"] == pytest.approx(ts, abs=1.0)

    def test_joins_alias_from_contacts(self, service):
        svc, (engine, _), _ = service
        ih = "g" * 64
        ts = time.time()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                ),
                {"h": ih, "t": ts},
            )
            conn.execute(
                text(
                    "INSERT INTO contacts (identity_hash, alias, blocked, created_at, updated_at) "
                    "VALUES (:h, 'BadActor', 1, :t, :t)"
                ),
                {"h": ih, "t": ts},
            )
            conn.commit()

        result = svc.get_blocked_peers()
        assert result[0]["alias"] == "BadActor"

    def test_alias_is_none_when_no_contact_entry(self, service):
        svc, (engine, _), _ = service
        ih = "h" * 64
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:h, :t)"
                ),
                {"h": ih, "t": time.time()},
            )
            conn.commit()

        result = svc.get_blocked_peers()
        assert result[0]["alias"] is None


# ---------------------------------------------------------------------------
# _handle_lxmf_message() — RBAC with NodeStore lookup
# ---------------------------------------------------------------------------


class TestHandleLxmfMessageRbac:
    def _make_message(self, dest_hash_hex: str):
        msg = MagicMock()
        msg.source_hash = bytes.fromhex(dest_hash_hex)
        msg.fields = {}
        msg.content = b""
        msg.title = b""
        return msg

    def test_drops_message_when_identity_hash_blocked(self, tmp_path):
        """RBAC check uses resolved identity_hash from NodeStore."""
        from styrened.services.lxmf_service import LXMFService
        from styrened.models.rbac import Role

        svc = LXMFService()
        policy = MagicMock()
        policy.resolve_role.return_value = Role.BLOCKED
        svc.set_rbac_policy(policy)

        callback = MagicMock()
        svc.register_callback(callback)

        dest_hash = "ab" * 16  # 32 hex chars
        identity_hash = "cd" * 32  # 64 hex chars

        mock_store = MagicMock()
        mock_store.get_identity_for_lxmf_destination.return_value = identity_hash

        with patch(
            "styrened.services.node_store.get_node_store", return_value=mock_store
        ):
            svc._handle_lxmf_message(self._make_message(dest_hash))

        # RBAC check was done against identity_hash, not dest_hash
        policy.resolve_role.assert_called_with(identity_hash)
        callback.assert_not_called()

    def test_falls_back_to_source_hash_when_nodestore_unavailable(self, tmp_path):
        """When NodeStore raises, falls back to source_hash (hex) for RBAC check."""
        from styrened.services.lxmf_service import LXMFService
        from styrened.models.rbac import Role

        svc = LXMFService()
        policy = MagicMock()
        policy.resolve_role.return_value = Role.BLOCKED
        svc.set_rbac_policy(policy)

        callback = MagicMock()
        svc.register_callback(callback)

        # source_hash_hex is used as the message source — it's a 32-char
        # hex string (16 bytes), the LXMF destination hash of the sender.
        source_hash_hex = "ab" * 16  # 32 hex chars

        with patch(
            "styrened.services.node_store.get_node_store",
            side_effect=Exception("unavailable"),
        ):
            svc._handle_lxmf_message(self._make_message(source_hash_hex))

        # Falls back to the raw source_hash hex when NodeStore is unavailable
        policy.resolve_role.assert_called_with(source_hash_hex)
        callback.assert_not_called()

    def test_passes_message_when_not_blocked(self, tmp_path):
        """Non-blocked peers have messages dispatched to callbacks."""
        from styrened.services.lxmf_service import LXMFService
        from styrened.models.rbac import Role

        svc = LXMFService()
        policy = MagicMock()
        policy.resolve_role.return_value = Role.PEER  # not blocked
        svc.set_rbac_policy(policy)

        callback = MagicMock()
        svc.register_callback(callback, raw_mode=True)

        dest_hash = "ef" * 16

        mock_store = MagicMock()
        mock_store.get_identity_for_lxmf_destination.return_value = None
        mock_store.get_identity_for_destination.return_value = None

        with patch(
            "styrened.services.node_store.get_node_store", return_value=mock_store
        ):
            svc._handle_lxmf_message(self._make_message(dest_hash))

        callback.assert_called_once()
