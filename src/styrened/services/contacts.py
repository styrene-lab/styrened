"""Contact service for managing mesh peer aliases and name resolution."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from styrened.models.contacts import Contact

logger = logging.getLogger(__name__)


@dataclass
class ContactInfo:
    """Contact information for API responses."""

    peer_hash: str
    alias: str
    notes: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_hash": self.peer_hash,
            "alias": self.alias,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContactInfo":
        return cls(
            peer_hash=data.get("peer_hash", ""),
            alias=data.get("alias", ""),
            notes=data.get("notes"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )

    @classmethod
    def from_model(cls, contact: Contact) -> "ContactInfo":
        return cls(
            peer_hash=contact.peer_hash,
            alias=contact.alias,
            notes=contact.notes,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )


class ContactService:
    """Manages contacts: CRUD operations and name resolution.

    Provides name resolution chain:
    1. Exact alias match
    2. Prefix alias match (unique)
    3. Exact short_name match (NodeStore, unique with lxmf_dest)
    4. Prefix short_name match (NodeStore, unique)
    5. Exact NodeStore announce name
    6. Prefix NodeStore announce name (unique)

    Args:
        db_engine: SQLAlchemy engine for persistence
        node_store: Optional NodeStore for announce name lookups
    """

    def __init__(self, db_engine: Engine, node_store: Any | None = None) -> None:
        self._db_engine = db_engine
        self._node_store = node_store

    def set_alias(self, peer_hash: str, alias: str, notes: str | None = None) -> ContactInfo:
        """Set or update a contact alias.

        Args:
            peer_hash: LXMF destination hash of the peer
            alias: Display name alias
            notes: Optional notes

        Returns:
            Updated ContactInfo
        """
        now = time.time()
        with Session(self._db_engine) as session:
            contact = session.get(Contact, peer_hash)
            if contact is not None:
                contact.alias = alias
                if notes is not None:
                    contact.notes = notes
                contact.updated_at = now
            else:
                contact = Contact(
                    peer_hash=peer_hash,
                    alias=alias,
                    notes=notes,
                    created_at=now,
                    updated_at=now,
                )
                session.add(contact)
            session.commit()
            info = ContactInfo.from_model(contact)
        logger.info(f"Set contact alias: {peer_hash[:16]}... -> {alias!r}")
        return info

    def remove_alias(self, peer_hash: str) -> bool:
        """Remove a contact alias.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            True if contact was removed, False if not found
        """
        with Session(self._db_engine) as session:
            contact = session.get(Contact, peer_hash)
            if contact is None:
                return False
            session.delete(contact)
            session.commit()
        logger.info(f"Removed contact: {peer_hash[:16]}...")
        return True

    def get_contact(self, peer_hash: str) -> ContactInfo | None:
        """Get contact info by peer hash.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            ContactInfo or None if not found
        """
        with Session(self._db_engine) as session:
            contact = session.get(Contact, peer_hash)
            if contact is None:
                return None
            return ContactInfo.from_model(contact)

    def list_contacts(self) -> list[ContactInfo]:
        """List all contacts ordered by alias.

        Returns:
            List of ContactInfo instances
        """
        with Session(self._db_engine) as session:
            contacts = session.query(Contact).order_by(Contact.alias).all()
            return [ContactInfo.from_model(c) for c in contacts]

    def resolve_name(self, name: str, prefix_match: bool = True) -> str | None:
        """Resolve a name to a peer hash.

        Resolution chain:
        1. Exact alias match (case-insensitive)
        2. Prefix alias match (unique, case-insensitive)
        3. Exact short_name match (NodeStore, unique with lxmf_dest)
        4. Prefix short_name match (NodeStore, unique)
        5. Exact NodeStore announce name (case-insensitive)
        6. Prefix NodeStore announce name (unique, case-insensitive)

        Args:
            name: Name to resolve
            prefix_match: Whether to try prefix matching

        Returns:
            Peer hash or None if not resolved
        """
        name_lower = name.lower()

        with Session(self._db_engine) as session:
            # 1. Exact alias match
            contacts = session.query(Contact).all()
            for c in contacts:
                if c.alias.lower() == name_lower:
                    return c.peer_hash

            # 2. Prefix alias match (must be unique)
            if prefix_match:
                prefix_matches = [
                    c for c in contacts if c.alias.lower().startswith(name_lower)
                ]
                if len(prefix_matches) == 1:
                    return prefix_matches[0].peer_hash

        if self._node_store is not None:
            # 3. Exact short_name match (unique with lxmf_dest)
            if hasattr(self._node_store, "get_nodes_by_short_name"):
                sn_matches = [
                    n
                    for n in self._node_store.get_nodes_by_short_name(name_lower)
                    if n.lxmf_destination_hash
                ]
                if len(sn_matches) == 1:
                    return sn_matches[0].lxmf_destination_hash

            # 4. Prefix short_name match (must be unique)
            if prefix_match and hasattr(self._node_store, "get_nodes_by_short_name_prefix"):
                sn_prefix_matches = [
                    n
                    for n in self._node_store.get_nodes_by_short_name_prefix(name_lower)
                    if n.lxmf_destination_hash
                ]
                if len(sn_prefix_matches) == 1:
                    return sn_prefix_matches[0].lxmf_destination_hash

            # 5. NodeStore exact announce name match
            nodes = self._node_store.get_all_nodes()
            for node in nodes:
                if node.name and node.name.lower() == name_lower:
                    if node.lxmf_destination_hash:
                        result: str = node.lxmf_destination_hash
                        return result

            # 6. NodeStore prefix announce name match (must be unique)
            if prefix_match:
                node_matches = [
                    n
                    for n in nodes
                    if n.name and n.name.lower().startswith(name_lower) and n.lxmf_destination_hash
                ]
                if len(node_matches) == 1:
                    prefix_result: str = node_matches[0].lxmf_destination_hash
                    return prefix_result

        return None

    def get_display_name(self, peer_hash: str) -> str | None:
        """Get display name for a peer.

        Resolution chain:
        1. Contact alias
        2. NodeStore announce name

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            Display name or None
        """
        # 1. Contact alias
        with Session(self._db_engine) as session:
            contact = session.get(Contact, peer_hash)
            if contact is not None:
                return contact.alias

        # 2. NodeStore announce name
        if self._node_store is not None:
            node = self._node_store.get_node_by_lxmf_destination(peer_hash)
            if node is not None and node.name:
                name: str = node.name
                return name

        return None
