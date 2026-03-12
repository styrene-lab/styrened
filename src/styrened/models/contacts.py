"""SQLAlchemy model for contact/address book persistence.

Contacts provide user-settable aliases for mesh peers, enabling
name-based lookup and display name resolution in conversations.

v0.16.0: PK migrated from peer_hash (LXMF destination hash, 32-char hex)
to identity_hash (RNS identity hash, 64-char hex) for canonical identity-
based blocking.  The peer_blocks table is the authoritative block store;
Contact.blocked/blocked_at are retained for UI display.
"""
from __future__ import annotations


import time

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from styrened.models.messages import Base


class Contact(Base):
    """Contact alias for a mesh peer.

    Attributes:
        identity_hash: RNS identity hash (primary key, 64-char hex).
        alias: User-settable display name.
        notes: Optional notes about the contact.
        blocked: Whether this peer is blocked (all comms silently dropped).
        blocked_at: Timestamp when the peer was blocked.
        created_at: Timestamp when contact was created.
        updated_at: Timestamp when contact was last modified.
    """

    __tablename__ = "contacts"

    identity_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    blocked_at: Mapped[float | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[float] = mapped_column(nullable=False, default=time.time)
    updated_at: Mapped[float] = mapped_column(nullable=False, default=time.time)

    def __init__(
        self,
        identity_hash: str,
        alias: str,
        notes: str | None = None,
        blocked: bool = False,
        blocked_at: float | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> None:
        now = time.time()
        super().__init__(
            identity_hash=identity_hash,
            alias=alias,
            notes=notes,
            blocked=blocked,
            blocked_at=blocked_at,
            created_at=created_at or now,
            updated_at=updated_at or now,
        )

    def __repr__(self) -> str:
        return f"<Contact(identity_hash={self.identity_hash[:16]}..., alias={self.alias!r})>"
