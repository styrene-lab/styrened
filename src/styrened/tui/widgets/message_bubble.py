"""MessageBubble widget for chat message display.

Selectable message widget that carries metadata for context actions
(retry, delete, reply). Contains a Static for text and optionally an
ImagePreview for inline image attachments.
"""
from __future__ import annotations


import logging
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

logger = logging.getLogger(__name__)

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


# Attachment type icons
ATTACHMENT_ICONS = {
    "image": "\U0001f5bc",  # framed picture
    "audio": "\U0001f50a",  # speaker high volume
    "file": "\U0001f4ce",  # paperclip
}


def _human_size(size: int | None) -> str:
    """Format byte count as human-readable string."""
    if size is None or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


class MessageBubble(Widget):
    """Selectable message display with metadata.

    Carries message metadata for context actions like retry, delete,
    and reply. CSS classes indicate message state for styling.

    Composes a Static child for text content, and optionally an
    ImagePreview child for inline image attachment rendering.

    Attributes:
        message_id: Database message ID.
        is_outgoing: Whether this is a sent message.
        status: Delivery status string.
        lxmf_hash: LXMF message hash (hex) for reply threading.
        reply_to_hash: Hash of the message being replied to.
        raw_content: Raw message content text (avoids shadowing Static.content).
        timestamp: Message timestamp.
        read_by_recipient: Whether the recipient has read this message.
        has_attachment: Whether this message has an attachment.
        attachment_type: Type of attachment ("image", "audio", "file").
        attachment_name: Original attachment filename.
        attachment_size: Attachment size in bytes.
    """

    DEFAULT_CSS = """
    MessageBubble {
        height: auto;
        width: 1fr;
    }

    MessageBubble .bubble-text {
        width: 1fr;
    }

    MessageBubble ImagePreview {
        height: auto;
        max-height: 20;
        width: 1fr;
    }
    """

    def __init__(
        self,
        text: str = "",
        *,
        message_id: int = 0,
        is_outgoing: bool = False,
        status: str = "",
        lxmf_hash: str | None = None,
        reply_to_hash: str | None = None,
        raw_content: str = "",
        timestamp: float = 0.0,
        read_by_recipient: bool = False,
        has_attachment: bool = False,
        attachment_type: str | None = None,
        attachment_name: str | None = None,
        attachment_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._text = text
        self.message_id = message_id
        self.is_outgoing = is_outgoing
        self.status = status
        self.lxmf_hash = lxmf_hash
        self.reply_to_hash = reply_to_hash
        self.raw_content = raw_content
        self.timestamp = timestamp
        self.read_by_recipient = read_by_recipient
        self.has_attachment = has_attachment
        self.attachment_type = attachment_type
        self.attachment_name = attachment_name
        self.attachment_size = attachment_size

        # Set CSS classes based on state
        if is_outgoing:
            self.add_class("message-bubble", "--outgoing")
        else:
            self.add_class("message-bubble", "--incoming")

        if status == "failed":
            self.add_class("--failed")

        if has_attachment:
            self.add_class("--has-attachment")

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle.

        Encapsulates the internal app structure access so callers
        don't reach through ``app._lifecycle`` directly.
        """
        try:
            return self.app.services.bridge
        except Exception:
            return None

    @property
    def _is_image_attachment(self) -> bool:
        """Whether this bubble has an image attachment to render inline."""
        return (
            self.has_attachment
            and self.attachment_type is not None
            and self.attachment_type.startswith("image")
        )

    def compose(self) -> ComposeResult:
        """Compose bubble content: text Static plus optional ImagePreview."""
        yield Static(self._text, classes="bubble-text")
        if self._is_image_attachment:
            from styrened.tui.widgets.image_preview import ImagePreview

            yield ImagePreview(id=f"bubble-img-{self.message_id}")

    def on_mount(self) -> None:
        """Kick off image fetch if this bubble has an image attachment."""
        if self._is_image_attachment and self.message_id:
            self.run_worker(self._fetch_image(), group=f"img-{self.message_id}")

    async def _fetch_image(self) -> None:
        """Fetch image attachment via IPCBridge and set preview data."""
        from styrened.tui.widgets.image_preview import ImagePreview

        try:
            preview = self.query_one(f"#bubble-img-{self.message_id}", ImagePreview)
        except Exception:
            return

        preview.filename = self.attachment_name or ""
        preview.loading = True

        bridge = self._ipc_bridge
        if bridge is None:
            self._collapse_to_text_indicator()
            return

        try:
            import asyncio
            import base64

            result = await asyncio.wait_for(
                bridge.get_attachment(self.message_id),
                timeout=10.0,
            )
            data = base64.b64decode(result.get("data_b64", ""))
            if not data:
                self._collapse_to_text_indicator()
                return
            preview.image_data = data
        except TimeoutError:
            logger.warning(f"Image fetch timed out for message {self.message_id}")
            self._collapse_to_text_indicator()
        except Exception as e:
            logger.error(f"Failed to fetch image for message {self.message_id}: {e}")
            self._collapse_to_text_indicator()

    def _collapse_to_text_indicator(self) -> None:
        """Replace the ImagePreview with a compact text attachment indicator.

        Called when image data cannot be fetched (deleted attachment,
        timeout, no connection). Removes the ImagePreview widget and
        appends an attachment line to the bubble text so the bubble
        collapses to minimal height.
        """
        from styrened.tui.widgets.image_preview import ImagePreview

        try:
            preview = self.query_one(f"#bubble-img-{self.message_id}", ImagePreview)
            preview.remove()
        except Exception:
            pass

        icon = ATTACHMENT_ICONS["image"]
        name = self.attachment_name or "image"
        size_str = _human_size(self.attachment_size)
        if size_str:
            fallback = f"[dim]{icon} {name} ({size_str})[/]"
        else:
            fallback = f"[dim]{icon} {name}[/]"
        self.update_text(f"{self._text}\n{fallback}")

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

    def update_text(self, new_text: str) -> None:
        """Update the displayed text content.

        Args:
            new_text: New Rich markup text to display.
        """
        self._text = new_text
        try:
            self.query_one(".bubble-text", Static).update(new_text)
        except Exception:
            pass

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
