"""Unit tests for ContactService CRUD and name resolution."""

import tempfile

import pytest

from styrened.models.messages import init_db
from styrened.services.contacts import ContactInfo, ContactService


@pytest.fixture
def db_engine():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    return init_db(db_path)


@pytest.fixture
def contact_service(db_engine):
    """Create a ContactService with test database."""
    return ContactService(db_engine=db_engine)


class TestContactInfoSerialization:
    """Tests for ContactInfo dataclass serialization."""

    def test_to_dict_includes_all_fields(self):
        """to_dict returns all contact fields."""
        info = ContactInfo(
            peer_hash="abcd1234abcd1234",
            alias="Alice",
            notes="Friend",
            created_at=1000.0,
            updated_at=2000.0,
        )
        d = info.to_dict()
        assert d["peer_hash"] == "abcd1234abcd1234"
        assert d["alias"] == "Alice"
        assert d["notes"] == "Friend"
        assert d["created_at"] == 1000.0
        assert d["updated_at"] == 2000.0

    def test_from_dict_reconstructs_contact(self):
        """from_dict reconstructs ContactInfo from dict."""
        data = {
            "peer_hash": "abcd1234abcd1234",
            "alias": "Bob",
            "notes": None,
            "created_at": 1000.0,
            "updated_at": 2000.0,
        }
        info = ContactInfo.from_dict(data)
        assert info.peer_hash == "abcd1234abcd1234"
        assert info.alias == "Bob"
        assert info.notes is None

    def test_from_dict_handles_missing_fields(self):
        """from_dict uses defaults for missing fields."""
        info = ContactInfo.from_dict({})
        assert info.peer_hash == ""
        assert info.alias == ""
        assert info.notes is None


class TestContactServiceCRUD:
    """Tests for ContactService create/read/update/delete operations."""

    def test_set_alias_creates_new_contact(self, contact_service):
        """set_alias creates a new contact when none exists."""
        result = contact_service.set_alias("abcd1234abcd1234", "Alice")
        assert result.peer_hash == "abcd1234abcd1234"
        assert result.alias == "Alice"
        assert result.notes is None
        assert result.created_at > 0

    def test_set_alias_updates_existing_contact(self, contact_service):
        """set_alias updates alias when contact already exists."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.set_alias("abcd1234abcd1234", "Alice B.")
        assert result.alias == "Alice B."
        assert result.peer_hash == "abcd1234abcd1234"

    def test_set_alias_with_notes(self, contact_service):
        """set_alias stores notes alongside alias."""
        result = contact_service.set_alias(
            "abcd1234abcd1234", "Alice", notes="My friend"
        )
        assert result.notes == "My friend"

    def test_set_alias_updates_notes(self, contact_service):
        """set_alias updates notes on existing contact."""
        contact_service.set_alias("abcd1234abcd1234", "Alice", notes="Old note")
        result = contact_service.set_alias(
            "abcd1234abcd1234", "Alice", notes="New note"
        )
        assert result.notes == "New note"

    def test_get_contact_returns_existing(self, contact_service):
        """get_contact returns contact info for existing peer."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.get_contact("abcd1234abcd1234")
        assert result is not None
        assert result.alias == "Alice"

    def test_get_contact_returns_none_for_missing(self, contact_service):
        """get_contact returns None when peer not found."""
        result = contact_service.get_contact("nonexistent1234567")
        assert result is None

    def test_remove_alias_deletes_contact(self, contact_service):
        """remove_alias deletes the contact and returns True."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.remove_alias("abcd1234abcd1234")
        assert result is True
        assert contact_service.get_contact("abcd1234abcd1234") is None

    def test_remove_alias_returns_false_for_missing(self, contact_service):
        """remove_alias returns False when contact not found."""
        result = contact_service.remove_alias("nonexistent1234567")
        assert result is False

    def test_list_contacts_returns_ordered_by_alias(self, contact_service):
        """list_contacts returns contacts alphabetically by alias."""
        contact_service.set_alias("hash_c", "Charlie")
        contact_service.set_alias("hash_a", "Alice")
        contact_service.set_alias("hash_b", "Bob")
        contacts = contact_service.list_contacts()
        aliases = [c.alias for c in contacts]
        assert aliases == ["Alice", "Bob", "Charlie"]

    def test_list_contacts_empty_database(self, contact_service):
        """list_contacts returns empty list when no contacts exist."""
        contacts = contact_service.list_contacts()
        assert contacts == []


class TestContactServiceNameResolution:
    """Tests for ContactService name resolution chain."""

    def test_resolve_name_exact_alias_match(self, contact_service):
        """resolve_name finds exact alias match (case-insensitive)."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.resolve_name("Alice")
        assert result == "abcd1234abcd1234"

    def test_resolve_name_case_insensitive(self, contact_service):
        """resolve_name is case-insensitive for alias matching."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.resolve_name("alice")
        assert result == "abcd1234abcd1234"

    def test_resolve_name_prefix_match_unique(self, contact_service):
        """resolve_name matches unique alias prefix."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.resolve_name("ali")
        assert result == "abcd1234abcd1234"

    def test_resolve_name_prefix_match_ambiguous_returns_none(self, contact_service):
        """resolve_name returns None when prefix matches multiple aliases."""
        contact_service.set_alias("hash_a", "Alice")
        contact_service.set_alias("hash_b", "Alicia")
        result = contact_service.resolve_name("ali")
        assert result is None

    def test_resolve_name_prefix_match_disabled(self, contact_service):
        """resolve_name skips prefix matching when disabled."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.resolve_name("ali", prefix_match=False)
        assert result is None

    def test_resolve_name_not_found_returns_none(self, contact_service):
        """resolve_name returns None when no match found."""
        result = contact_service.resolve_name("nobody")
        assert result is None

    def test_resolve_name_falls_through_to_node_store(self):
        """resolve_name checks NodeStore when no alias match."""
        from unittest.mock import MagicMock

        mock_node = MagicMock()
        mock_node.name = "BobNode"
        mock_node.lxmf_destination_hash = "beef1234beef1234"

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = [mock_node]

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            engine = init_db(f.name)

        service = ContactService(db_engine=engine, node_store=mock_store)
        result = service.resolve_name("BobNode")
        assert result == "beef1234beef1234"

    def test_resolve_name_node_store_prefix_unique(self):
        """resolve_name matches unique NodeStore name prefix."""
        from unittest.mock import MagicMock

        mock_node = MagicMock()
        mock_node.name = "BobNode"
        mock_node.lxmf_destination_hash = "beef1234beef1234"

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = [mock_node]

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            engine = init_db(f.name)

        service = ContactService(db_engine=engine, node_store=mock_store)
        result = service.resolve_name("bob")
        assert result == "beef1234beef1234"

    def test_resolve_name_alias_takes_priority_over_node_store(self):
        """resolve_name prefers alias match over NodeStore match."""
        from unittest.mock import MagicMock

        mock_node = MagicMock()
        mock_node.name = "Alice"
        mock_node.lxmf_destination_hash = "nodestore_hash12345"

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = [mock_node]

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            engine = init_db(f.name)

        service = ContactService(db_engine=engine, node_store=mock_store)
        service.set_alias("contact_hash12345", "Alice")
        result = service.resolve_name("Alice")
        assert result == "contact_hash12345"


class TestContactServiceDisplayName:
    """Tests for ContactService display name resolution."""

    def test_get_display_name_returns_alias(self, contact_service):
        """get_display_name returns contact alias when set."""
        contact_service.set_alias("abcd1234abcd1234", "Alice")
        result = contact_service.get_display_name("abcd1234abcd1234")
        assert result == "Alice"

    def test_get_display_name_falls_back_to_node_store(self):
        """get_display_name returns NodeStore name when no alias."""
        from unittest.mock import MagicMock

        mock_node = MagicMock()
        mock_node.name = "BobNode"

        mock_store = MagicMock()
        mock_store.get_node_by_lxmf_destination.return_value = mock_node

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            engine = init_db(f.name)

        service = ContactService(db_engine=engine, node_store=mock_store)
        result = service.get_display_name("beef1234beef1234")
        assert result == "BobNode"

    def test_get_display_name_returns_none_when_unknown(self, contact_service):
        """get_display_name returns None when peer is unknown."""
        result = contact_service.get_display_name("unknown12345678")
        assert result is None

    def test_get_display_name_alias_takes_priority(self):
        """get_display_name prefers alias over NodeStore name."""
        from unittest.mock import MagicMock

        mock_node = MagicMock()
        mock_node.name = "NodeName"

        mock_store = MagicMock()
        mock_store.get_node_by_lxmf_destination.return_value = mock_node

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            engine = init_db(f.name)

        service = ContactService(db_engine=engine, node_store=mock_store)
        service.set_alias("abcd1234abcd1234", "CustomAlias")
        result = service.get_display_name("abcd1234abcd1234")
        assert result == "CustomAlias"
