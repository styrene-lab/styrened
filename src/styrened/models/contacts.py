"""SQLAlchemy model for contact/address book persistence.

Contacts provide user-settable aliases for mesh peers, enabling
name-based lookup and display name resolution in conversations.
"""

import time

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from styrened.models.messages import Base


class Contact(Base):
    """Contact alias for a mesh peer.

    Attributes:
        peer_hash: LXMF destination hash (primary key).
        alias: User-settable display name.
        notes: Optional notes about the contact.
        blocked: Whether this peer is blocked (all comms silently dropped).
        blocked_at: Timestamp when the peer was blocked.
        created_at: Timestamp when contact was created.
        updated_at: Timestamp when contact was last modified.
    """

    __tablename__ = "contacts"

    peer_hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    blocked_at: Mapped[float | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[float] = mapped_column(nullable=False, default=time.time)
    updated_at: Mapped[float] = mapped_column(nullable=False, default=time.time)

    def __init__(
        self,
        peer_hash: str,
        alias: str,
        notes: str | None = None,
        blocked: bool = False,
        blocked_at: float | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> None:
        now = time.time()
        super().__init__(
            peer_hash=peer_hash,
            alias=alias,
            notes=notes,
            blocked=blocked,
            blocked_at=blocked_at,
            created_at=created_at or now,
            updated_at=updated_at or now,
        )

    def __repr__(self) -> str:
        return f"<Contact(peer_hash={self.peer_hash[:16]}..., alias={self.alias!r})>"
