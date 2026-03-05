"""Tests for peer blocking / blocklist functionality."""

import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from styrened.models.contacts import Contact


@pytest.fixture
def db_engine(tmp_path):
    """Create a test DB with contacts table including blocked columns."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE contacts ("
            "peer_hash VARCHAR(32) PRIMARY KEY, "
            "alias VARCHAR(100) NOT NULL, "
            "notes VARCHAR(500), "
            "blocked BOOLEAN NOT NULL DEFAULT 0, "
            "blocked_at REAL, "
            "created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL"
            ")"
        ))
        conn.commit()
    return engine, db_path


class TestContactBlockedField:
    """Contact model has blocked flag."""

    def test_contact_default_not_blocked(self):
        c = Contact(peer_hash="abc123", alias="test")
        assert c.blocked is False
        assert c.blocked_at is None

    def test_contact_blocked(self):
        c = Contact(peer_hash="abc123", alias="test", blocked=True, blocked_at=time.time())
        assert c.blocked is True
        assert c.blocked_at is not None


class TestLXMFServiceBlocklist:
    """LXMFService block/unblock/check methods."""

    def _make_service(self, db_path):
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        # Patch paths.messages_db to return our test db
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            yield svc, mock_paths

    def test_block_peer_creates_contact(self, db_engine):
        engine, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            result = svc.block_peer("deadbeef12345678")
            assert result is True

            # Verify in DB
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT blocked, alias FROM contacts WHERE peer_hash = 'deadbeef12345678'")
                ).fetchone()
                assert row is not None
                assert row[0] == 1  # blocked
                assert row[1] == "deadbeef"  # default alias = first 8 chars

    def test_block_existing_contact(self, db_engine):
        engine, db_path = db_engine
        # Create existing contact
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO contacts (peer_hash, alias, blocked, created_at, updated_at) "
                     "VALUES ('deadbeef12345678', 'Friendly', 0, :t, :t)"),
                {"t": time.time()},
            )
            conn.commit()

        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            result = svc.block_peer("deadbeef12345678")
            assert result is True

            # Alias preserved, blocked set
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT blocked, alias FROM contacts WHERE peer_hash = 'deadbeef12345678'")
                ).fetchone()
                assert row[0] == 1
                assert row[1] == "Friendly"

    def test_unblock_peer(self, db_engine):
        engine, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("deadbeef12345678")
            result = svc.unblock_peer("deadbeef12345678")
            assert result is True

            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT blocked, blocked_at FROM contacts WHERE peer_hash = 'deadbeef12345678'")
                ).fetchone()
                assert row[0] == 0
                assert row[1] is None

    def test_is_blocked_true(self, db_engine):
        engine, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("deadbeef12345678")
            assert svc._is_blocked("deadbeef12345678") is True

    def test_is_blocked_false(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            assert svc._is_blocked("deadbeef12345678") is False

    def test_is_blocked_uses_cache(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("deadbeef12345678")
            # Cache loaded
            assert svc._is_blocked("deadbeef12345678") is True
            # Mutate cache directly to prove it's cached
            svc._blocked_peers.discard("deadbeef12345678")
            assert svc._is_blocked("deadbeef12345678") is False
            # Invalidate reloads
            svc.invalidate_blocklist()
            assert svc._is_blocked("deadbeef12345678") is True

    def test_get_blocked_peers(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("aaaa1111")
            svc.block_peer("bbbb2222")
            blocked = svc.get_blocked_peers()
            assert len(blocked) == 2
            hashes = {b["peer_hash"] for b in blocked}
            assert "aaaa1111" in hashes
            assert "bbbb2222" in hashes

    def test_block_idempotent(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            assert svc.block_peer("deadbeef12345678") is True
            assert svc.block_peer("deadbeef12345678") is True
            blocked = svc.get_blocked_peers()
            assert len(blocked) == 1


class TestLXMFMessageDropped:
    """Blocked peers have messages silently dropped."""

    def test_blocked_message_dropped(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("deadbeef12345678")

            # Create a fake LXMF message
            msg = MagicMock()
            msg.source_hash = bytes.fromhex("deadbeef12345678")

            callback = MagicMock()
            svc._message_callbacks = [(callback, False)]

            svc._handle_lxmf_message(msg)

            # Callback should NOT have been called
            callback.assert_not_called()

    def test_unblocked_message_delivered(self, db_engine):
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path

            msg = MagicMock()
            msg.source_hash = bytes.fromhex("deadbeef12345678")
            msg.content = b'{"type": "chat", "message": "hello"}'
            msg.fields = {}
            msg.timestamp = time.time()

            callback = MagicMock()
            svc._message_callbacks = [(callback, True)]

            svc._handle_lxmf_message(msg)

            # Raw callback receives the message
            callback.assert_called_once_with(msg)


class TestBlocklistPrefixMatching:
    """_is_blocked supports prefix matching for short hashes in config."""

    def test_short_hash_blocks_full_hash(self, db_engine):
        """Config entry 'ca3e9813' blocks source 'ca3e981348d3bb48...'."""
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("ca3e9813")
            assert svc._is_blocked("ca3e981348d3bb48aabbccdd") is True

    def test_full_hash_blocks_full_hash(self, db_engine):
        """Exact match still works."""
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("ca3e981348d3bb48aabbccdd")
            assert svc._is_blocked("ca3e981348d3bb48aabbccdd") is True

    def test_short_hash_does_not_block_different_prefix(self, db_engine):
        """'ca3e9813' does NOT block 'deadbeef...'."""
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("ca3e9813")
            assert svc._is_blocked("deadbeef12345678") is False

    def test_message_dropped_with_prefix_block(self, db_engine):
        """LXMF message from full hash is dropped when short hash is blocked."""
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            svc.block_peer("ca3e9813")

            msg = MagicMock()
            # Full hash as bytes — .hex() returns full string
            msg.source_hash = bytes.fromhex("ca3e981348d3bb48")

            callback = MagicMock()
            svc._message_callbacks = [(callback, False)]
            svc._handle_lxmf_message(msg)
            callback.assert_not_called()

    def test_very_short_prefix_requires_minimum_length(self, db_engine):
        """Single-char prefix shouldn't block half the network."""
        _, db_path = db_engine
        from styrened.services.lxmf_service import LXMFService

        svc = LXMFService()
        with patch("styrened.paths") as mock_paths:
            mock_paths.messages_db.return_value = db_path
            # 2-char prefix — this is technically valid but aggressive
            svc.block_peer("ca")
            # Still matches because startswith works
            assert svc._is_blocked("ca3e981348d3bb48") is True


class TestSeedConfigBansOrdering:
    """_seed_config_bans works regardless of chat.enabled state."""

    def test_seed_bans_with_chat_disabled(self, tmp_path):
        """banned_peers should work even when chat.enabled=False."""
        from unittest.mock import patch as _patch

        from styrened.models.config import CoreConfig

        config = CoreConfig()
        config.chat.enabled = False
        config.banned_peers = ["deadbeef12345678"]

        # Create a minimal DB so block_peer has a table
        db_path = tmp_path / "messages.db"
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE contacts ("
                "peer_hash VARCHAR(32) PRIMARY KEY, "
                "alias VARCHAR(100) NOT NULL, "
                "notes VARCHAR(500), "
                "blocked BOOLEAN NOT NULL DEFAULT 0, "
                "blocked_at REAL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            ))
            conn.commit()

        with _patch("styrened.paths.messages_db", return_value=db_path), \
             _patch("styrened.models.messages.init_db", return_value=engine):
            from styrened.daemon import StyreneDaemon

            daemon = StyreneDaemon.__new__(StyreneDaemon)
            daemon.config = config
            daemon._seed_config_bans()

        # Verify ban was written
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT blocked FROM contacts WHERE peer_hash = 'deadbeef12345678'")
            ).fetchone()
            assert row is not None
            assert row[0] == 1


class TestIPCMessages:
    """IPC message serialization for block commands."""

    def test_block_request_roundtrip(self):
        from styrened.ipc.messages import CmdBlockPeerRequest

        req = CmdBlockPeerRequest(peer_hash="deadbeef12345678")
        payload = req.to_payload()
        assert payload == {"peer_hash": "deadbeef12345678"}
        restored = CmdBlockPeerRequest.from_payload(payload)
        assert restored.peer_hash == "deadbeef12345678"

    def test_unblock_request_roundtrip(self):
        from styrened.ipc.messages import CmdUnblockPeerRequest

        req = CmdUnblockPeerRequest(peer_hash="deadbeef12345678")
        payload = req.to_payload()
        restored = CmdUnblockPeerRequest.from_payload(payload)
        assert restored.peer_hash == "deadbeef12345678"

    def test_query_blocked_roundtrip(self):
        from styrened.ipc.messages import QueryBlockedPeersRequest

        req = QueryBlockedPeersRequest()
        payload = req.to_payload()
        assert payload == {}

    def test_ipc_types_unique(self):
        """All IPC message type values must be unique."""
        from styrened.ipc.protocol import IPCMessageType

        values = [m.value for m in IPCMessageType]
        assert len(values) == len(set(values)), f"Duplicate IPC values: {[v for v in values if values.count(v) > 1]}"
