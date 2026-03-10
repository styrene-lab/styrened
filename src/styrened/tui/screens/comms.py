"""Comms workspace screen.

Aggregate shell for synchronous/direct/live communication. Capability-gated
sections reveal based on daemon config: Yggdrasil and I2P sections are only
shown when those subsystems are enabled in core config.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, Static, TabbedContent, TabPane

from styrened.ui_state import CommsMode, CommsWorkspaceInputs, build_comms_workspace_state


class CommsScreen(Screen[None]):
    """Aggregate workspace for synchronous and live communication."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._caps_loaded = False

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        state = build_comms_workspace_state(CommsWorkspaceInputs())
        yield Header()
        with Container(id="comms-container"):
            yield Static("COMMS", id="comms-title")
            with TabbedContent(initial=state.active_mode.value, id="comms-tabs"):
                # Direct — active direct-link sessions
                with TabPane("Direct", id=CommsMode.DIRECT.value):
                    with Vertical(id="comms-direct-content"):
                        yield Static(
                            "No active direct sessions.",
                            id="comms-direct-placeholder",
                        )

                # Active — live session list
                with TabPane("Active", id=CommsMode.ACTIVE.value):
                    yield Static(
                        "No active sessions.",
                        id="comms-active-placeholder",
                    )

                # Bridges — capability-gated bridge surfaces
                with TabPane("Bridges", id=CommsMode.BRIDGES.value):
                    with Vertical(id="comms-bridges-content"):
                        # Yggdrasil section — hidden until caps loaded
                        with Vertical(id="comms-yggdrasil-section", classes="hidden"):
                            yield Label("Yggdrasil", id="comms-yggdrasil-label")
                            yield Static(
                                "Yggdrasil overlay network is active.",
                                id="comms-yggdrasil-status",
                            )

                        # I2P section — hidden until caps loaded
                        with Vertical(id="comms-i2p-section", classes="hidden"):
                            yield Label("I2P", id="comms-i2p-label")
                            yield Static(
                                "I2P network is active.",
                                id="comms-i2p-status",
                            )
                            yield Input(
                                placeholder="Enter .i2p address…",
                                id="comms-i2p-url-input",
                            )

                        # Shown when no bridges are available
                        yield Static(
                            "No bridge capabilities active. Enable Yggdrasil or I2P in config.",
                            id="comms-bridges-placeholder",
                        )

                # Presence — live reachability
                with TabPane("Presence", id=CommsMode.PRESENCE.value):
                    yield Static(
                        "Live presence and reachability will appear here.",
                        id="comms-presence-placeholder",
                    )
        yield Footer()

    def on_mount(self) -> None:
        """Fetch daemon capabilities and update capability-gated sections."""
        if self._ipc_bridge is not None:
            self.run_worker(self._load_capabilities(), group="comms-caps", exclusive=True)

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh capability state when returning to Comms workspace."""
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
        # Direct tab — show active link count
        try:
            placeholder = self.query_one("#comms-direct-placeholder", Static)
            if active_links > 0:
                placeholder.update(f"{active_links} active direct session(s).")
            else:
                placeholder.update("No active direct sessions.")
        except Exception:
            pass

        # Bridges tab — show/hide capability sections
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
