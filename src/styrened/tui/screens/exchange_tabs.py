"""Exchange tab content widgets for Direct and Contacts tabs.

Lifts compose() content from CommsScreen (Direct subtab) and ContactsScreen
into standalone Widget subclasses for embedding in ExchangeScreen's TabbedContent.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.ui_state import CommsMode
from styrened.tui.widgets.highlighted_panel import get_color_cascade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ExchangeDirectTab
# ---------------------------------------------------------------------------


class ExchangeDirectTab(Widget):
    """Direct tab content: active direct-link sessions, bridges, and presence.

    Lifted from CommsScreen.compose() — preserves all capability-gated
    sections (Yggdrasil, I2P) and IPC polling patterns.
    """

    DEFAULT_CSS = """
    ExchangeDirectTab {
        height: 1fr;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._caps_loaded = False

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr,attr-defined]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        with Vertical(id="comms-container"):
            # Active direct-link sessions
            with Vertical(id="comms-direct-content"):
                yield Static(
                    "No active direct sessions.",
                    id="comms-direct-placeholder",
                )

            # Bridges — capability-gated (Yggdrasil, I2P)
            with Vertical(id="comms-bridges-content"):
                with Vertical(id="comms-yggdrasil-section", classes="hidden"):
                    yield Label("Yggdrasil", id="comms-yggdrasil-label")
                    yield Static(
                        "Yggdrasil overlay network is active.",
                        id="comms-yggdrasil-status",
                    )
                with Vertical(id="comms-i2p-section", classes="hidden"):
                    yield Label("I2P", id="comms-i2p-label")
                    yield Static("I2P network is active.", id="comms-i2p-status")
                    yield Input(
                        placeholder="Enter .i2p address…",
                        id="comms-i2p-url-input",
                    )
                yield Static(
                    "No bridge capabilities active. Enable Yggdrasil or I2P in config.",
                    id="comms-bridges-placeholder",
                )

            # Presence
            yield Static(
                "Live presence and reachability will appear here.",
                id="comms-presence-placeholder",
            )

    def on_mount(self) -> None:
        """Fetch daemon capabilities and update capability-gated sections."""
        if self._ipc_bridge is not None:
            self.run_worker(self._load_capabilities(), group="comms-caps", exclusive=True)

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh capability state when Exchange screen is resumed."""
        if self._ipc_bridge is not None:
            self.run_worker(self._load_capabilities(), group="comms-caps", exclusive=True)

    async def _load_capabilities(self) -> None:
        """Fetch core config + daemon status and apply capability visibility."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        import asyncio

        tasks = {
            "config": asyncio.create_task(bridge.get_core_config()),
            "status": asyncio.create_task(bridge.get_status()),
        }

        config_data: dict[str, Any] = {}
        active_links = 0

        try:
            try:
                raw_config = await tasks["config"]
                config_data = raw_config if isinstance(raw_config, dict) else {}
            except Exception:
                pass

            try:
                status = await tasks["status"]
                active_links = getattr(status, "active_links", 0) or 0
            except Exception:
                pass
        finally:
            pending = [t for t in tasks.values() if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # Derive capabilities from config
        yggdrasil_enabled = False
        i2p_enabled = False

        ygg_cfg = config_data.get("yggdrasil", {})
        if isinstance(ygg_cfg, dict):
            yggdrasil_enabled = str(ygg_cfg.get("mode", "disabled")).lower() != "disabled"

        i2p_cfg = config_data.get("i2p", {})
        if isinstance(i2p_cfg, dict):
            i2p_enabled = str(i2p_cfg.get("mode", "disabled")).lower() != "disabled"

        self._apply_capability_state(
            yggdrasil_enabled=yggdrasil_enabled,
            i2p_enabled=i2p_enabled,
            active_links=active_links,
        )

    def _apply_capability_state(
        self,
        *,
        yggdrasil_enabled: bool,
        i2p_enabled: bool,
        active_links: int,
    ) -> None:
        """Update UI visibility and content based on resolved capability state."""
        try:
            placeholder = self.query_one("#comms-direct-placeholder", Static)
            if active_links > 0:
                placeholder.update(f"{active_links} active direct session(s).")
            else:
                placeholder.update("No active direct sessions.")
        except Exception:
            pass

        any_bridge = yggdrasil_enabled or i2p_enabled

        try:
            bridges_placeholder = self.query_one("#comms-bridges-placeholder", Static)
            if any_bridge:
                bridges_placeholder.add_class("hidden")
            else:
                bridges_placeholder.remove_class("hidden")
        except Exception:
            pass

        try:
            ygg_section = self.query_one("#comms-yggdrasil-section")
            if yggdrasil_enabled:
                ygg_section.remove_class("hidden")
            else:
                ygg_section.add_class("hidden")
        except Exception:
            pass

        try:
            i2p_section = self.query_one("#comms-i2p-section")
            if i2p_enabled:
                i2p_section.remove_class("hidden")
            else:
                i2p_section.add_class("hidden")
        except Exception:
            pass

        self._caps_loaded = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle I2P URL submission — open page browser with I2P transport."""
        if event.input.id == "comms-i2p-url-input":
            url = event.value.strip()
            if not url:
                return
            self._open_i2p_page(url)

    def _open_i2p_page(self, url: str) -> None:
        """Navigate to page browser for an I2P .i2p address."""
        try:
            from styrened.tui.widgets.page_browser import PageBrowserWidget  # noqa: F401

            self.notify(f"Opening I2P page: {url}", severity="information")
            # TODO: push PageBrowserScreen with i2p_url=url once available
        except Exception:
            self.notify(f"I2P page browser not available (URL: {url})", severity="warning")


# ---------------------------------------------------------------------------
# ExchangeContactsTab
# ---------------------------------------------------------------------------


class ExchangeContactsTab(Widget):
    """Contacts tab content: contact list with add/edit/delete/resolve actions.

    Lifted from ContactsScreen.compose() — preserves all IPC polling,
    DataTable row selection, and form interactions.
    """

    DEFAULT_CSS = """
    ExchangeContactsTab {
        height: 1fr;
        background: $background;
    }

    ExchangeContactsTab Static {
        color: $primary;
        background: $background;
    }

    ExchangeContactsTab DataTable {
        background: $background;
        color: $primary;
    }

    ExchangeContactsTab DataTable > .datatable--header {
        background: $surface;
        color: $primary;
        text-style: bold;
    }

    ExchangeContactsTab DataTable > .datatable--cursor {
        background: $surface;
        color: $primary;
    }

    ExchangeContactsTab Input {
        background: $background;
        color: $primary;
        border: round $border;
    }

    ExchangeContactsTab #edit-form {
        display: none;
        height: auto;
        padding: 1;
    }

    ExchangeContactsTab #edit-form.visible {
        display: block;
    }

    ExchangeContactsTab #resolve-panel {
        display: none;
        height: auto;
        padding: 1;
    }

    ExchangeContactsTab #resolve-panel.visible {
        display: block;
    }
    """

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr,attr-defined]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        """Compose contacts UI (lifted from ContactsScreen)."""
        with Container(id="contacts-container"):
            yield HighlightedPanel(
                DataTable(id="contacts-table"),
                title="CONTACTS",
                id="contacts-panel",
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
            )

    def on_mount(self) -> None:
        """Load contacts on mount."""
        table = self.query_one("#contacts-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ALIAS", "STATUS", "LAST MESSAGE", "PEER HASH")

        if self._ipc_bridge is None:
            table.add_row("-", "-", "-", f"[{get_color_cascade().dim}]Contacts require daemon mode[/]")
            return

        self.run_worker(self._load_contacts())

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Reload contacts when Exchange screen is resumed."""
        if self._ipc_bridge is not None:
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

        device_map: dict[str, dict[str, Any]] = {}
        conv_map: dict[str, dict[str, Any]] = {}

        try:
            devices = await bridge.get_devices()
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
        """Open chat with the selected contact on enter."""
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

    def open_chat(self) -> None:
        """Open chat with the selected contact (callable from parent screen)."""
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

    def show_add_form(self) -> None:
        """Show add contact form (callable from parent screen)."""
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

    def show_edit_form(self) -> None:
        """Edit selected contact (callable from parent screen)."""
        table = self.query_one("#contacts-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return

        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        peer_hash = str(cell_key.row_key.value)
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

    def delete_selected(self) -> None:
        """Delete selected contact (callable from parent screen)."""
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

    def show_resolve_panel(self) -> None:
        """Show resolve name panel (callable from parent screen)."""
        resolve_panel = self.query_one("#resolve-panel", Vertical)
        resolve_panel.add_class("visible")
        resolve_input = self.query_one("#resolve-input", Input)
        resolve_input.focus()

    def dismiss_forms(self) -> bool:
        """Dismiss any open forms. Returns True if a form was dismissed."""
        edit_form = self.query_one("#edit-form", Vertical)
        resolve_panel = self.query_one("#resolve-panel", Vertical)

        if edit_form.has_class("visible"):
            edit_form.remove_class("visible")
            return True
        if resolve_panel.has_class("visible"):
            resolve_panel.remove_class("visible")
            return True
        return False

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
