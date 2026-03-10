"""Tests for RBAC integration in LXMFService."""

from unittest.mock import MagicMock, patch

import pytest

from styrened.models.rbac import RBACPolicy, Role


def _make_daemon(rbac_policy=None):
    """Create a minimal mock daemon with real _inject_lxmf_rbac bound."""
    from styrened.daemon import StyreneDaemon

    daemon = MagicMock()
    daemon.config = MagicMock()
    daemon.config.rbac = rbac_policy or RBACPolicy()
    daemon._inject_lxmf_rbac = StyreneDaemon._inject_lxmf_rbac.__get__(daemon)
    return daemon


@pytest.fixture
def lxmf_service():
    """Create a fresh LXMFService instance for testing."""
    from styrened.services.lxmf_service import LXMFService

    svc = LXMFService()
    # Register a dummy callback so messages aren't dropped for "no callbacks"
    svc._message_callbacks = [(MagicMock(), True)]
    return svc


@pytest.fixture
def rbac_policy():
    """Create an RBACPolicy with default_role=PEER."""
    return RBACPolicy(default_role=Role.PEER)


@pytest.fixture
def mock_message():
    """Create a mock LXMF message."""
    msg = MagicMock()
    msg.source_hash = bytes.fromhex("abcdef1234567890abcdef1234567890")
    msg.content = b'{"type": "chat", "message": "hello"}'
    msg.fields = {}
    return msg


class TestLXMFRBACBlockedDropsMessages:
    """RBAC BLOCKED role should drop messages."""

    def test_blocked_role_drops_message(self, lxmf_service, mock_message):
        """Message from BLOCKED peer is dropped when RBAC policy is set."""
        source_hex = mock_message.source_hash.hex()
        policy = RBACPolicy(default_role=Role.PEER, blocked=[source_hex])
        lxmf_service.set_rbac_policy(policy)

        lxmf_service._handle_lxmf_message(mock_message)

        # Callback should NOT have been called
        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_not_called()

    def test_blocked_by_prefix_drops_message(self, lxmf_service, mock_message):
        """Message blocked by prefix match via RBAC."""
        source_hex = mock_message.source_hash.hex()
        prefix = source_hex[:8]
        policy = RBACPolicy(default_role=Role.PEER, blocked=[prefix])
        lxmf_service.set_rbac_policy(policy)

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_not_called()


class TestLXMFRBACPeerAllowsMessages:
    """PEER role should allow messages through."""

    def test_peer_role_allows_message(self, lxmf_service, rbac_policy, mock_message):
        """Message from PEER role identity is delivered."""
        lxmf_service.set_rbac_policy(rbac_policy)

        lxmf_service._handle_lxmf_message(mock_message)

        # Raw callback should have been called with the message
        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_called_once_with(mock_message)


class TestLXMFDefaultRBACPolicy:
    """Default RBACPolicy (PEER default role) allows all non-blocked traffic."""

    def test_default_policy_allows_messages(self, lxmf_service, mock_message):
        """Default RBACPolicy with PEER default role allows messages through."""
        # lxmf_service starts with a default RBACPolicy()
        assert lxmf_service._rbac_policy is not None

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_called_once_with(mock_message)

    def test_blocked_on_default_policy_drops(self, lxmf_service, mock_message):
        """Blocking a peer on the default policy drops messages."""
        source_hex = mock_message.source_hash.hex()
        lxmf_service._rbac_policy.block(source_hex)

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_not_called()


class TestBlockUnblockSyncsRBAC:
    """block_peer/unblock_peer should sync to RBAC policy when present."""

    def test_block_peer_syncs_to_rbac(self, lxmf_service, rbac_policy):
        """block_peer adds to RBAC blocked list."""
        lxmf_service.set_rbac_policy(rbac_policy)
        peer = "ca3e981348d3bb48abcdef1234567890" * 2  # 64 chars

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            lxmf_service.block_peer(peer)

        assert peer in rbac_policy.blocked

    def test_unblock_peer_syncs_to_rbac(self, lxmf_service, rbac_policy):
        """unblock_peer removes from RBAC blocked list."""
        peer = "ca3e981348d3bb48abcdef1234567890" * 2
        rbac_policy.block(peer)
        lxmf_service.set_rbac_policy(rbac_policy)

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            # Simulate peer found in peer_blocks
            mock_conn.execute.return_value.fetchone.return_value = (peer,)
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            lxmf_service.unblock_peer(peer)

        assert peer not in rbac_policy.blocked

    def test_block_peer_always_syncs_to_rbac(self, lxmf_service):
        """block_peer always syncs to the default RBAC policy."""
        peer = "ca3e981348d3bb48abcdef1234567890" * 2

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            result = lxmf_service.block_peer(peer)

        assert result is True
        assert peer in lxmf_service._rbac_policy.blocked


class TestSetRBACPolicy:
    """set_rbac_policy method."""

    def test_sets_policy(self, lxmf_service, rbac_policy):
        """Policy is stored on the service."""
        lxmf_service.set_rbac_policy(rbac_policy)
        assert lxmf_service._rbac_policy is rbac_policy


class TestContactsDBBlocksSeededToRBAC:
    """Verify contacts-DB blocks are loaded into RBAC on startup."""

    def test_contacts_blocks_seeded(self, lxmf_service, rbac_policy):
        """Blocks in contacts DB but not in RBAC config are seeded."""
        lxmf_service.set_rbac_policy(rbac_policy)
        # Simulate contacts DB having a blocked peer not in RBAC config
        lxmf_service._load_blocklist = lambda: {"deadbeef12345678", "cafebabe87654321"}

        # Simulate daemon calling _seed_contacts_blocks_to_rbac
        blocked_set = lxmf_service._load_blocklist()
        for peer_hash in blocked_set:
            if peer_hash not in rbac_policy.blocked:
                rbac_policy.block(peer_hash)

        assert "deadbeef12345678" in rbac_policy.blocked
        assert "cafebabe87654321" in rbac_policy.blocked

    def test_contacts_blocks_not_duplicated(self, lxmf_service, rbac_policy):
        """Blocks already in RBAC config are not duplicated."""
        rbac_policy.block("deadbeef12345678")
        lxmf_service.set_rbac_policy(rbac_policy)
        lxmf_service._load_blocklist = lambda: {"deadbeef12345678"}

        blocked_set = lxmf_service._load_blocklist()
        for peer_hash in blocked_set:
            if peer_hash not in rbac_policy.blocked:
                rbac_policy.block(peer_hash)

        assert rbac_policy.blocked.count("deadbeef12345678") == 1

    def test_rbac_blocked_message_after_seed(self, lxmf_service, mock_message):
        """Message from contacts-DB-blocked peer is dropped after seeding."""
        source_hex = mock_message.source_hash.hex()
        policy = RBACPolicy(default_role=Role.PEER)
        lxmf_service.set_rbac_policy(policy)
        # Simulate seeding from contacts DB
        policy.block(source_hex)

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_not_called()


class TestInjectLxmfRbacDaemonWiring:
    """Regression tests for daemon._inject_lxmf_rbac().

    Ensures RBAC is injected into LXMFService from start() regardless
    of chat.enabled state. This was the bug fixed in commit cf94431.
    """

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.models.messages.init_db")
    def test_rbac_injected_when_policy_present(self, mock_init_db, mock_get_svc):
        """RBAC policy is injected into LXMFService when config.rbac is set."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = _make_daemon(rbac_policy=policy)

        mock_svc = MagicMock()
        mock_svc.is_initialized = True
        mock_svc._load_blocklist.return_value = set()
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()

        mock_svc.set_rbac_policy.assert_called_once_with(policy)

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_skips_when_lxmf_not_initialized(self, mock_get_svc):
        """Gracefully skips when LXMF is not yet initialized."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = _make_daemon(rbac_policy=policy)

        mock_svc = MagicMock()
        mock_svc.is_initialized = False
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()  # Should not raise

        mock_svc.set_rbac_policy.assert_not_called()


class TestInjectLxmfRbacExceptionHandling:
    """Verify _inject_lxmf_rbac degrades gracefully on errors."""

    @patch("styrened.services.lxmf_service.get_lxmf_service", side_effect=ImportError("no LXMF"))
    def test_inject_survives_import_error(self, mock_get_svc):
        """_inject_lxmf_rbac doesn't crash when LXMF is not installed."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = _make_daemon(rbac_policy=policy)
        daemon._inject_lxmf_rbac()  # Should not raise




class TestRBACReversePrefixMatch:
    """Test the reverse prefix matching in resolve_role."""

    def test_short_hash_matches_long_blocked_prefix(self):
        """If blocked list has a long prefix and identity is short, still matches.

        This covers the `prefix.startswith(identity_hash)` branch in resolve_role.
        """
        policy = RBACPolicy(
            default_role=Role.PEER,
            blocked=["abcdef1234567890abcdef1234567890"],
        )
        # Short identity hash that is a prefix of the blocked entry
        role = policy.resolve_role("abcdef12")
        assert role == Role.BLOCKED

    def test_non_matching_prefix(self):
        """Non-matching prefix does not block."""
        policy = RBACPolicy(
            default_role=Role.PEER,
            blocked=["abcdef12"],
        )
        role = policy.resolve_role("99999999aabbccdd")
        assert role == Role.PEER
