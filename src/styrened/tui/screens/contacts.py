from __future__ import annotations

"""ContactsScreen - Manage contact aliases for mesh peers.

Provides a DataTable of contacts with add, edit, delete, and resolve actions.
Uses IPCBridge for daemon communication and theme variables for styling.
"""

import datetime
import logging
import time
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.highlighted_panel import get_color_cascade

logger = logging.getLogger(__name__)


class ContactsScreen(Screen[None]):
    """Contacts management screen.

    Displays a list of saved contacts (alias → peer hash) and provides
    controls for adding, editing, removing, and resolving contacts.

    All data is loaded via IPCBridge from the daemon.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Home"),
        Binding("enter", "open_chat", "Chat"),
        Binding("c", "open_chat", "Chat", show=False),
        Binding("a", "add_contact", "Add"),
        Binding("e", "edit_contact", "Edit"),
        Binding("delete", "delete_contact", "Delete"),
        Binding("r", "resolve_name", "Resolve"),
    ]

    CSS = """
    ContactsScreen {
        background: $background;
    }

    ContactsScreen Static {
        color: $primary;
        background: $background;
    }

    ContactsScreen DataTable {
        background: $background;
        color: $primary;
    }

    ContactsScreen DataTable > .datatable--header {
        background: $surface;
        color: $primary;
        text-style: bold;
    }

    ContactsScreen DataTable > .datatable--cursor {
        background: $surface;
        color: $primary;
    }

    ContactsScreen Input {
        background: $background;
        color: $primary;
        border: round $border;
    }

    ContactsScreen #edit-form {
        display: none;
        height: auto;
        padding: 1;
    }

    ContactsScreen #edit-form.visible {
        display: block;
    }

    ContactsScreen #resolve-panel {
        display: none;
        height: auto;
        padding: 1;
    }

    ContactsScreen #resolve-panel.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose contacts UI."""
        yield Header()
        with Container(id="contacts-container"):
            yield HighlightedPanel(
                DataTable(id="contacts-table"),
                title="CONTACTS",
                id="contacts-panel",
                classes="panel-info",
            )

            # Edit form (hidden by default)
            yield HighlightedPanel(
                Vertical(
                    Input(placeholder="Peer hash (hex)", id="edit-hash-input"),
                    Input(placeholder="Alias", id="edit-alias-input"),
                    Input(placeholder="Notes (optional)", id="edit-notes-input"),
                    Horizontal(
                        Button("Save", id="save-btn", variant="primary"),
                        Button("Cancel", id="cancel-btn", variant="default"),
                    ),
                    id="edit-form",
                ),
                title="EDIT CONTACT",
                id="edit-form-panel",
                classes="panel-interactive",
            )

            # Resolve panel (hidden by default)
            yield HighlightedPanel(
                Vertical(
                    Horizontal(
                        Input(placeholder="Name to resolve", id="resolve-input"),
                        Button("Resolve", id="resolve-btn", variant="primary"),
                    ),
                    Static("", id="resolve-result"),
                    id="resolve-panel",
                ),
                title="RESOLVE NAME",
                id="resolve-panel-container",
                classes="panel-interactive",
            )
        yield Footer()

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app.services.bridge
        except Exception:
            return None

    def on_mount(self) -> None:
        """Load contacts on mount."""
        table = self.query_one("#contacts-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ALIAS", "STATUS", "LAST MESSAGE", "PEER HASH")

        if self._ipc_bridge is None:
            table.add_row("-", "-", "-", f"[{get_color_cascade().dim}]Contacts require daemon mode[/]")
            return

        self.run_worker(self._load_contacts())

    @staticmethod
    def _relative_time(ts: float) -> str:
        """Format a unix timestamp as a human-readable relative time."""
        if not ts:
            return ""
        elapsed = int(time.time() - ts)
        if elapsed < 0:
            return "just now"
        if elapsed < 60:
            return "just now"
        if elapsed < 3600:
            return f"{elapsed // 60}m ago"
        if elapsed < 86400:
            return f"{elapsed // 3600}h ago"
        if elapsed < 604800:
            return f"{elapsed // 86400}d ago"
        return datetime.datetime.fromtimestamp(ts).strftime("%b %d")

    async def _load_contacts(self) -> None:
        """Load contacts enriched with presence and last message data."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            contacts = await bridge.get_contacts()
        except Exception as e:
            logger.warning(f"Failed to load contacts: {e}")
            contacts = []

        # Fetch devices and conversations for cross-referencing
        device_map: dict[str, dict[str, Any]] = {}
        conv_map: dict[str, dict[str, Any]] = {}

        try:
            cache = getattr(self.app, "device_cache", None)
            devices = cache.get() if cache is not None else await bridge.get_devices()
            for dev in devices:
                d = dev if isinstance(dev, dict) else dev.to_dict()
                for key in (d.get("lxmf_destination_hash"), d.get("destination_hash")):
                    if key:
                        device_map[key] = d
        except Exception:
            pass

        try:
            convs = await bridge.get_conversations()
            for conv in convs:
                ph = conv.get("peer_hash", "")
                if ph:
                    conv_map[ph] = conv
        except Exception:
            pass

        table = self.query_one("#contacts-table", DataTable)
        table.clear()

        if not contacts:
            table.add_row("-", "-", "-", f"[{get_color_cascade().dim}]No contacts saved[/]")
            return

        for contact in contacts:
            peer_hash = contact.get("identity_hash", "") or contact.get("peer_hash", "")
            alias = contact.get("alias", "")
            hash_display = peer_hash[:16] + "..." if len(peer_hash) > 16 else peer_hash

            # Presence from device announces
            dev = device_map.get(peer_hash)
            if dev:
                dev_status = dev.get("status", "")
                last_announce = dev.get("last_announce", 0)
                if dev_status == "active":
                    status_str = f"[{get_color_cascade().bright}]● online[/]"
                elif dev_status == "stale":
                    status_str = f"[{get_color_cascade().color_warning}]◐ {self._relative_time(last_announce)}[/]"
                else:
                    status_str = f"[{get_color_cascade().dim}]○ {self._relative_time(last_announce)}[/]"
            else:
                status_str = f"[{get_color_cascade().dim}]○ unknown[/]"

            # Last message from conversations
            conv = conv_map.get(peer_hash)
            if conv:
                last_msg_time = conv.get("last_message_time", 0)
                preview = conv.get("last_message_preview", "")
                if preview and len(preview) > 25:
                    preview = preview[:25] + "…"
                if last_msg_time:
                    last_msg_str = f"[{get_color_cascade().dim}]{self._relative_time(last_msg_time)}[/]"
                    if preview:
                        last_msg_str = f"{preview} [{get_color_cascade().dim}]{self._relative_time(last_msg_time)}[/]"
                else:
                    last_msg_str = ""
            else:
                last_msg_str = ""

            table.add_row(
                alias,
                status_str,
                last_msg_str,
                hash_display,
                key=peer_hash,
            )

    def _get_selected_peer_hash(self) -> str | None:
        """Get the peer_hash of the currently selected contact row."""
        table = self.query_one("#contacts-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return None

        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return None

        return str(cell_key.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle DataTable enter key - open chat with selected contact.

        The DataTable consumes enter key events when cursor_type="row",
        emitting RowSelected instead of letting the screen binding fire.
        """
        if event.row_key and event.row_key.value and event.row_key.value != "-":
            peer_hash = str(event.row_key.value)

            if self._ipc_bridge is None:
                self.notify("Chat requires daemon mode", severity="warning")
                return

            from styrened.tui.screens.conversation import ConversationScreen

            self.app.push_screen(
                ConversationScreen(
                    peer_hash=peer_hash,
                    origin_workspace="contacts",
                )
            )

    def action_open_chat(self) -> None:
        """Open chat with the selected contact.

        Fallback action for the enter/c bindings. When DataTable is focused,
        on_data_table_row_selected handles it instead.
        """
        peer_hash = self._get_selected_peer_hash()
        if peer_hash is None:
            return

        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(
            ConversationScreen(
                peer_hash=peer_hash,
                origin_workspace="contacts",
            )
        )

    def action_go_back(self) -> None:
        """Go back, hiding forms first if visible."""
        edit_form = self.query_one("#edit-form", Vertical)
        resolve_panel = self.query_one("#resolve-panel", Vertical)

        if edit_form.has_class("visible"):
            edit_form.remove_class("visible")
            return
        if resolve_panel.has_class("visible"):
            resolve_panel.remove_class("visible")
            return

        self.app.switch_screen("dashboard")

    def action_add_contact(self) -> None:
        """Show add contact form."""
        edit_form = self.query_one("#edit-form", Vertical)
        hash_input = self.query_one("#edit-hash-input", Input)
        alias_input = self.query_one("#edit-alias-input", Input)
        notes_input = self.query_one("#edit-notes-input", Input)

        hash_input.value = ""
        alias_input.value = ""
        notes_input.value = ""
        hash_input.disabled = False
        edit_form.add_class("visible")
        hash_input.focus()

    def action_edit_contact(self) -> None:
        """Edit selected contact."""
        table = self.query_one("#contacts-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return

        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        peer_hash = str(cell_key.row_key.value)

        # Get current values from row
        alias = str(table.get_cell_at(Coordinate(table.cursor_row, 0)))
        notes = str(table.get_cell_at(Coordinate(table.cursor_row, 2)))

        edit_form = self.query_one("#edit-form", Vertical)
        hash_input = self.query_one("#edit-hash-input", Input)
        alias_input = self.query_one("#edit-alias-input", Input)
        notes_input = self.query_one("#edit-notes-input", Input)

        hash_input.value = peer_hash
        hash_input.disabled = True
        alias_input.value = alias
        notes_input.value = notes
        edit_form.add_class("visible")
        alias_input.focus()

    def action_delete_contact(self) -> None:
        """Delete selected contact."""
        table = self.query_one("#contacts-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return

        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        peer_hash = str(cell_key.row_key.value)
        self.run_worker(self._delete_contact(peer_hash))

    async def _delete_contact(self, peer_hash: str) -> None:
        """Delete a contact via IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        try:
            removed = await bridge.remove_contact(peer_hash)
            if removed:
                self.notify("Contact removed", severity="information")
            else:
                self.notify("Contact not found", severity="warning")
        except Exception as e:
            self.notify(f"Failed to remove contact: {e}", severity="error")
            return

        await self._load_contacts()

    def action_resolve_name(self) -> None:
        """Show resolve name panel."""
        resolve_panel = self.query_one("#resolve-panel", Vertical)
        resolve_panel.add_class("visible")
        resolve_input = self.query_one("#resolve-input", Input)
        resolve_input.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if str(event.button.id) == "save-btn":
            await self._save_contact()
        elif str(event.button.id) == "cancel-btn":
            self.query_one("#edit-form", Vertical).remove_class("visible")
        elif str(event.button.id) == "resolve-btn":
            await self._resolve_name()

    async def _save_contact(self) -> None:
        """Save contact from form inputs."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        peer_hash = self.query_one("#edit-hash-input", Input).value.strip()
        alias = self.query_one("#edit-alias-input", Input).value.strip()
        notes = self.query_one("#edit-notes-input", Input).value.strip()

        if not peer_hash:
            self.notify("Peer hash is required", severity="warning")
            return
        if not alias:
            self.notify("Alias is required", severity="warning")
            return

        try:
            await bridge.set_contact(
                peer_hash=peer_hash,
                alias=alias,
                notes=notes or None,
            )
            self.notify("Contact saved", severity="information")
        except Exception as e:
            self.notify(f"Failed to save contact: {e}", severity="error")
            return

        self.query_one("#edit-form", Vertical).remove_class("visible")
        await self._load_contacts()

    async def _resolve_name(self) -> None:
        """Resolve a name to a peer hash."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Resolve requires daemon mode", severity="warning")
            return

        name = self.query_one("#resolve-input", Input).value.strip()
        if not name:
            self.notify("Enter a name to resolve", severity="warning")
            return

        result_widget = self.query_one("#resolve-result", Static)

        try:
            peer_hash = await bridge.resolve_name(name)
            if peer_hash:
                result_widget.update(f"Resolved: {peer_hash}")
            else:
                result_widget.update(f"[{get_color_cascade().dim}]No match found[/]")
        except Exception as e:
            result_widget.update(f"[{get_color_cascade().color_danger}]Error: {e}[/]")
