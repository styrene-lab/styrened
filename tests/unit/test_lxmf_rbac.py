"""Tests for RBAC integration in LXMFService."""

from unittest.mock import MagicMock, patch

import pytest

from styrened.models.rbac import RBACPolicy, Role


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


class TestLXMFLegacyFallback:
    """When _rbac_policy is None, legacy _is_blocked is used."""

    def test_legacy_blocked_drops_message(self, lxmf_service, mock_message):
        """Legacy blocklist still works when no RBAC policy is set."""
        assert lxmf_service._rbac_policy is None
        source_hex = mock_message.source_hash.hex()
        lxmf_service._blocked_peers = {source_hex}

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_not_called()

    def test_legacy_unblocked_allows_message(self, lxmf_service, mock_message):
        """Legacy unblocked peer passes through when no RBAC policy."""
        assert lxmf_service._rbac_policy is None
        lxmf_service._blocked_peers = set()

        lxmf_service._handle_lxmf_message(mock_message)

        callback = lxmf_service._message_callbacks[0][0]
        callback.assert_called_once_with(mock_message)


class TestBlockUnblockSyncsRBAC:
    """block_peer/unblock_peer should sync to RBAC policy when present."""

    @patch("styrened.services.lxmf_service.LXMFService._load_blocklist", return_value=set())
    def test_block_peer_syncs_to_rbac(self, _mock_load, lxmf_service, rbac_policy):
        """block_peer adds to RBAC blocked list."""
        lxmf_service.set_rbac_policy(rbac_policy)
        peer = "ca3e981348d3bb48abcdef1234567890"

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = None  # no existing contact

            lxmf_service.block_peer(peer)

        assert peer in rbac_policy.blocked

    @patch("styrened.services.lxmf_service.LXMFService._load_blocklist", return_value=set())
    def test_unblock_peer_syncs_to_rbac(self, _mock_load, lxmf_service, rbac_policy):
        """unblock_peer removes from RBAC blocked list."""
        rbac_policy.block("ca3e981348d3bb48abcdef1234567890")
        lxmf_service.set_rbac_policy(rbac_policy)
        peer = "ca3e981348d3bb48abcdef1234567890"

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            lxmf_service.unblock_peer(peer)

        assert peer not in rbac_policy.blocked

    def test_block_peer_without_rbac_no_error(self, lxmf_service):
        """block_peer with no RBAC policy doesn't crash."""
        assert lxmf_service._rbac_policy is None
        peer = "ca3e981348d3bb48abcdef1234567890"

        with patch("styrened.paths.messages_db", return_value="/tmp/fake.db"), \
             patch("sqlalchemy.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = None

            result = lxmf_service.block_peer(peer)

        assert result is True


class TestSetRBACPolicy:
    """set_rbac_policy method."""

    def test_sets_policy(self, lxmf_service, rbac_policy):
        """Policy is stored on the service."""
        assert lxmf_service._rbac_policy is None
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

    def _make_daemon(self, rbac_policy=None):
        """Create a minimal mock daemon with config."""
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = rbac_policy
        # Bind the real method to our mock
        from styrened.daemon import StyreneDaemon
        daemon._inject_lxmf_rbac = StyreneDaemon._inject_lxmf_rbac.__get__(daemon)
        daemon._seed_contacts_blocks_to_rbac = StyreneDaemon._seed_contacts_blocks_to_rbac.__get__(daemon)
        return daemon

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.models.messages.init_db")
    def test_rbac_injected_when_policy_present(self, mock_init_db, mock_get_svc):
        """RBAC policy is injected into LXMFService when config.rbac is set."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)

        mock_svc = MagicMock()
        mock_svc.is_initialized = True
        mock_svc._load_blocklist.return_value = set()
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()

        mock_svc.set_rbac_policy.assert_called_once_with(policy)

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_no_injection_when_policy_absent(self, mock_get_svc):
        """No RBAC injection when config.rbac is None."""
        daemon = self._make_daemon(rbac_policy=None)

        mock_svc = MagicMock()
        mock_svc.is_initialized = True
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()

        mock_svc.set_rbac_policy.assert_not_called()

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.models.messages.init_db")
    def test_contacts_blocks_seeded_during_injection(self, mock_init_db, mock_get_svc):
        """Contacts-DB blocks are seeded into RBAC during injection."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)

        mock_svc = MagicMock()
        mock_svc.is_initialized = True
        mock_svc._load_blocklist.return_value = {"deadbeef12345678"}
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()

        assert "deadbeef12345678" in policy.blocked

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    def test_skips_when_lxmf_not_initialized(self, mock_get_svc):
        """Gracefully skips when LXMF is not yet initialized."""
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)

        mock_svc = MagicMock()
        mock_svc.is_initialized = False
        mock_get_svc.return_value = mock_svc

        daemon._inject_lxmf_rbac()  # Should not raise

        mock_svc.set_rbac_policy.assert_not_called()
