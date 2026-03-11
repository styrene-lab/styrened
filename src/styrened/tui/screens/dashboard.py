"""Dashboard Screen — Home workspace.

Home shows the local node status, unread summary, and recent activity.
Peer browsing lives in the Nodes workspace (ExplorationScreen).
"""

from typing import Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static
from styrened import __version__ as _TUI_VERSION
from styrened.tui.services.reticulum import start_discovery
from styrened.tui.widgets.activity_feed import ActivityFeedWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
from styrened.tui.widgets.home_status_bar import HomeStatusBar


class IdentityNudgeBanner(Static):
    """Dismissible banner nudging the operator to set up their identity."""

    DEFAULT_CSS = """
    IdentityNudgeBanner {
        background: $primary 20%;
        color: $text;
        border: tall $primary;
        padding: 0 1;
        height: 3;
        margin: 0 0 1 0;
        display: none;
    }
    IdentityNudgeBanner.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__(
            "👤  Set up your identity — press [bold]S[/bold] to open Settings",
            id="identity-nudge-banner",
        )

    def show_nudge(self) -> None:
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")


class VersionMismatchBanner(Static):
    """Dismissible warning banner shown when daemon and TUI versions differ."""

    DEFAULT_CSS = """
    VersionMismatchBanner {
        background: $warning 30%;
        color: $warning-lighten-2;
        border: tall $warning;
        padding: 0 1;
        height: 3;
        margin: 0 0 1 0;
        display: none;
    }
    VersionMismatchBanner.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__("", id="version-mismatch-banner")
        self._daemon_version: str = ""
        self._restarting: bool = False

    def show_mismatch(self, daemon_version: str) -> None:
        """Display the banner with the mismatched daemon version."""
        if self._restarting:
            return
        self._daemon_version = daemon_version
        self.update(
            f"⚠  Daemon v{daemon_version} ≠ TUI v{_TUI_VERSION} — "
            f"press [bold]R[/bold] to restart service, [bold]D[/bold] to dismiss"
        )
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the banner."""
        self.remove_class("visible")

    @property
    def daemon_version(self) -> str:
        return self._daemon_version

    @property
    def is_restarting(self) -> bool:
        return self._restarting

    def set_restarting(self, value: bool) -> None:
        self._restarting = value
        if value:
            self.update(
                f"⟳  Restarting daemon service… (TUI v{_TUI_VERSION})"
            )
            self.add_class("visible")


class DashboardScreen(Screen[None]):
    """Home workspace — local status, unread summary, and recent activity.

    Peer browsing and the full mesh device tree belong in the Nodes workspace
    (ExplorationScreen). Home is intentionally narrow: it shows what the
    operator needs at a glance without duplicating the Nodes workspace.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh_or_restart", "Refresh/Restart", priority=True),
        Binding("d", "dismiss_banner", "Dismiss", show=False),
        Binding("n", "open_exploration", "Nodes", show=True),
        Binding("e", "open_exploration", "Nodes", show=False),
        Binding("s", "open_settings", "Settings", show=False),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._hub_retry_timer: Timer | None = None
        self._activity_worker: Any | None = None

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def on_mount(self) -> None:
        """Initialise Home: start discovery, then check identity nudge."""
        # Keep discovery running so ExplorationScreen has fresh data when
        # the operator switches to Nodes. Home itself doesn't render the tree.
        start_discovery()

        # Show identity nudge if user hasn't configured their identity
        self._check_identity_nudge()

        self._hub_retry_timer = self.set_interval(30.0, self._retry_hub_connection)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(), group="activity-feed"
            )

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Pause periodic refresh while Home is not the active screen."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.pause()
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh Home panels when the operator returns from another workspace."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.resume()

        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(), group="activity-feed"
            )

    def on_unmount(self) -> None:
        """Stop timers when Home is removed from the screen stack."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.stop()
            self._hub_retry_timer = None
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    def _retry_hub_connection(self) -> None:
        """Periodically poll hub status via IPC."""
        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="hub-status")

    def compose(self) -> ComposeResult:
        yield Header()
        yield IdentityNudgeBanner()
        yield VersionMismatchBanner()
        with Container(id="dashboard-container"):
            yield HighlightedPanel(
                HomeStatusBar(id="home-status-bar"),
                title="STATUS",
                id="status-bar-panel",
            )
            yield HighlightedPanel(
                HomeNodeSummaryTable(id="home-node-summary"),
                title="NODES",
                id="nodes-panel",
            )
            yield HighlightedPanel(
                ActivityFeedWidget(id="activity-feed-widget"),
                title="ACTIVITY",
                id="activity-panel",
            )
        yield Footer()

    def action_open_exploration(self) -> None:
        """Open the canonical Nodes workspace."""
        self.app.action_open_nodes()  # type: ignore[attr-defined]

    def action_refresh_or_restart(self) -> None:
        """R: restart service if banner is visible, otherwise refresh."""
        try:
            banner = self.query_one(VersionMismatchBanner)
            if banner.has_class("visible") and not banner.is_restarting:
                self.run_worker(self._restart_daemon_service(), group="daemon-restart")
                return
        except Exception:
            pass
        self.action_refresh()

    def action_dismiss_banner(self) -> None:
        """D: dismiss the version mismatch banner and/or identity nudge."""
        try:
            self.query_one(VersionMismatchBanner).hide()
        except Exception:
            pass
        self._dismiss_identity_nudge()

    def _check_identity_nudge(self) -> None:
        """Show the identity nudge if the operator hasn't configured identity."""
        try:
            config = self.app.config  # type: ignore[attr-defined]
            if config.tui.identity_nudge_dismissed:
                return
            # Check if identity is still at default
            identity = getattr(config, "identity", None) or getattr(
                getattr(config, "core", None), "identity", None
            )
            if identity is None:
                return
            display_name = getattr(identity, "display_name", "Anonymous Styrene")
            if display_name in ("Anonymous Styrene", ""):
                self.query_one(IdentityNudgeBanner).show_nudge()
        except Exception:
            pass

    def _dismiss_identity_nudge(self) -> None:
        """Dismiss the identity nudge and persist the dismissal to config."""
        try:
            banner = self.query_one(IdentityNudgeBanner)
            if not banner.has_class("visible"):
                return
            banner.hide()
            config = self.app.config  # type: ignore[attr-defined]
            config.tui.identity_nudge_dismissed = True
            from styrened.tui.services.config import save_config
            save_config(config)
        except Exception:
            pass

    def action_open_settings(self) -> None:
        """S: open settings screen (also dismisses identity nudge)."""
        self._dismiss_identity_nudge()
        try:
            self.app.action_open_settings()  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _restart_daemon_service(self) -> None:
        """Restart the external service and wait for daemon to come back."""
        try:
            banner = self.query_one(VersionMismatchBanner)
        except Exception:
            return

        banner.set_restarting(True)

        try:
            # Ask DaemonManager to handle the restart
            daemon_manager = getattr(self.app, "_daemon_manager", None)  # type: ignore[attr-defined]
            if daemon_manager is None:
                # Fallback: call service_installer directly
                from styrened.tui.services.service_installer import restart_service
                await restart_service()
            else:
                await daemon_manager.restart()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Daemon restart failed: %s", exc)
        finally:
            banner.set_restarting(False)
            banner.hide()

        # Trigger fresh status fetch after restart
        self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

    def action_refresh(self) -> None:
        """Refresh Home status panels."""
        self.notify("Refreshed")

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

        try:
            self.app._check_for_updates()  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _fetch_daemon_status(self) -> None:
        """Fetch Home status from daemon and push into HomeStatusBar + HomeNodeSummaryTable."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        import asyncio

        tasks = {
            "status": asyncio.create_task(bridge.get_status()),
            "hub": asyncio.create_task(bridge.get_hub_status()),
            "mesh_devices": asyncio.create_task(bridge.get_devices(styrene_only=True)),
            "conversations": asyncio.create_task(bridge.get_conversations()),
        }

        try:
            try:
                status = await tasks["status"]
                hub_data = await tasks["hub"]
                mesh_devices = list(await tasks["mesh_devices"])
            except Exception:
                # Mark status bar as disconnected on failure
                try:
                    self.query_one(HomeStatusBar).daemon_connected = False
                except Exception:
                    pass
                return

            # Check for version mismatch and show/hide banner
            try:
                banner = self.query_one(VersionMismatchBanner)
                daemon_ver = str(getattr(status, "daemon_version", "") or "")
                if daemon_ver and daemon_ver != _TUI_VERSION and not banner.is_restarting:
                    banner.show_mismatch(daemon_ver)
                elif not daemon_ver or daemon_ver == _TUI_VERSION:
                    if not banner.is_restarting:
                        banner.hide()
            except Exception:
                pass

            # Update HomeStatusBar reactive props
            try:
                status_bar = self.query_one(HomeStatusBar)
                status_bar.rns_online = getattr(status, "rns_initialized", False)
                status_bar.daemon_connected = True
                status_bar.styrene_mesh_count = len(mesh_devices)
                status_bar.daemon_uptime = getattr(status, "uptime", 0.0) or 0.0
                if isinstance(hub_data, dict):
                    from styrened.services.hub_connection import HubStatus
                    is_connected = hub_data.get("is_connected", False)
                    status_bar.hub_status = (
                        HubStatus.CONNECTED if is_connected else HubStatus.DISCONNECTED
                    )
                iface_count = getattr(status, "interface_count", 0) or 0
                status_bar.interface_count = iface_count
            except Exception:
                pass

            # Update HomeNodeSummaryTable with mesh devices
            try:
                node_table = self.query_one(HomeNodeSummaryTable)
                node_table.update_nodes(mesh_devices)
            except Exception:
                pass

            # Update unread count on status bar
            convs: list[dict[str, Any]] = []
            try:
                convs = await tasks["conversations"]
            except Exception:
                pass

            try:
                status_bar = self.query_one(HomeStatusBar)
                total_unread = sum(
                    c.get("unread_count", 0) for c in convs if isinstance(c, dict)
                )
                status_bar.unread_count = total_unread
            except Exception:
                pass
        finally:
            pending = [t for t in tasks.values() if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    def on_home_node_summary_table_node_selected(
        self, message: HomeNodeSummaryTable.NodeSelected
    ) -> None:
        """Handle node selection from the summary table — push detail screen."""
        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        self.app.push_screen(
            MeshDeviceDetailScreen(device_identity=message.identity_hash)
        )

    async def _subscribe_activity(self) -> None:
        """Subscribe to daemon activity events and feed them to ActivityFeedWidget."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        from styrened.ipc.protocol import IPCMessageType

        await bridge.subscribe_activity()

        try:
            activity_widget = self.query_one(ActivityFeedWidget)
        except Exception:
            return

        async for event_type, payload in bridge.iter_events(IPCMessageType.EVENT_ACTIVITY):
            if isinstance(payload, dict):
                evt = payload.get("event_type", "unknown")
                activity_widget.add_event(evt, payload)


