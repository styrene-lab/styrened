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
