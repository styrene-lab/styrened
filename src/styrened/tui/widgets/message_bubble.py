"""MessageBubble widget for chat message display.

Selectable message widget that carries metadata for context actions
(retry, delete, reply). Replaces raw Static widgets in chat display.
"""

from typing import Any

from textual.widgets import Static

# Delivery status indicators
STATUS_ICONS = {
    "pending": "\u23f3",  # hourglass
    "sent": "\u2713",  # check
    "delivered": "\u2713\u2713",  # double check
    "failed": "\u2717",  # cross
    "read": "\u2713\u2713",
}

# Read receipt uses a distinct style from delivered
READ_ICON = "\u2713\u2713"


class MessageBubble(Static):
    """Selectable message display with metadata.

    Carries message metadata for context actions like retry, delete,
    and reply. CSS classes indicate message state for styling.

    Attributes:
        message_id: Database message ID.
        is_outgoing: Whether this is a sent message.
        status: Delivery status string.
        lxmf_hash: LXMF message hash (hex) for reply threading.
        reply_to_hash: Hash of the message being replied to.
        content: Raw message content text.
        timestamp: Message timestamp.
        read_by_recipient: Whether the recipient has read this message.
    """

    def __init__(
        self,
        renderable: str = "",
        *,
        message_id: int = 0,
        is_outgoing: bool = False,
        status: str = "",
        lxmf_hash: str | None = None,
        reply_to_hash: str | None = None,
        content: str = "",
        timestamp: float = 0.0,
        read_by_recipient: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(renderable, **kwargs)
        self.message_id = message_id
        self.is_outgoing = is_outgoing
        self.status = status
        self.lxmf_hash = lxmf_hash
        self.reply_to_hash = reply_to_hash
        self.content = content
        self.timestamp = timestamp
        self.read_by_recipient = read_by_recipient

        # Set CSS classes based on state
        if is_outgoing:
            self.add_class("message-bubble", "--outgoing")
        else:
            self.add_class("message-bubble", "--incoming")

        if status == "failed":
            self.add_class("--failed")

    def select(self) -> None:
        """Mark this bubble as selected."""
        self.add_class("--selected")

    def deselect(self) -> None:
        """Remove selection from this bubble."""
        self.remove_class("--selected")

    @property
    def is_selected(self) -> bool:
        """Whether this bubble is currently selected."""
        return self.has_class("--selected")

    @property
    def is_failed(self) -> bool:
        """Whether this message has failed delivery."""
        return self.status == "failed"

    def update_status(self, new_status: str) -> None:
        """Update the delivery status and refresh display.

        Args:
            new_status: New status string.
        """
        old_failed = self.status == "failed"
        self.status = new_status

        # Update CSS classes
        if new_status == "failed" and not old_failed:
            self.add_class("--failed")
        elif new_status != "failed" and old_failed:
            self.remove_class("--failed")
