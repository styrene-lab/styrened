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
from styrened.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.services.config import load_config
from styrened.tui.services.reticulum import start_discovery
from styrened.tui.widgets.comms_summary import CommsSummaryWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.node_info_panel import NodeInfoPanel
from styrened.ui_state.daemon import (
    LocalDaemonInputs,
    build_home_node_info_state,
    build_home_node_local_state,
    build_local_daemon_state,
)


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
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._hub_retry_timer: Timer | None = None

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
        except Exception:
            return None

    def on_mount(self) -> None:
        """Initialise Home: apply local snapshot, then fetch daemon state."""
        # Keep discovery running so ExplorationScreen has fresh data when
        # the operator switches to Nodes. Home itself doesn't render the tree.
        start_discovery()

        self._hub_retry_timer = self.set_interval(30.0, self._retry_hub_connection)

        try:
            panel = self.query_one(NodeInfoPanel)
            panel.ipc_managed = self._ipc_bridge is not None
            self._apply_local_panel_snapshot(panel)
            if self._ipc_bridge is not None:
                panel.daemon_connected = False
        except Exception:
            pass

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Pause periodic refresh while Home is not the active screen."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.pause()

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh Home panels when the operator returns from another workspace."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.resume()

        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        node_info_panel = self.query_one(NodeInfoPanel)
        self._apply_local_panel_snapshot(node_info_panel)
        if self._ipc_bridge is None:
            node_info_panel.refresh_data()

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

    def on_unmount(self) -> None:
        """Stop timers when Home is removed from the screen stack."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.stop()
            self._hub_retry_timer = None

    def _retry_hub_connection(self) -> None:
        """Periodically poll hub status via IPC."""
        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="hub-status")

    def _apply_local_panel_snapshot(self, panel: NodeInfoPanel) -> None:
        """Push local hardware/config snapshot into NodeInfoPanel."""
        system_info = None
        primary_interface = None
        removable_count = 0
        hardware_error = None
        mode = "standalone"
        identity_display_name = ""
        identity_icon = ""
        identity_short_name = None
        identity_provider = "file"

        try:
            system_info = get_system_info()
            interfaces = get_network_interfaces()
            hardware_ifaces = [i for i in interfaces if i.is_hardware and i.is_up and i.ip_address]
            primary_interface = hardware_ifaces[0] if hardware_ifaces else None
            disks = get_disks()
            removable_count = len([d for d in disks if d.is_removable])
        except PlatformNotSupportedError as exc:
            hardware_error = str(exc)

        try:
            config = load_config()
            mode = config.reticulum.mode.value
            if hasattr(config, "identity"):
                identity_display_name = config.identity.display_name
                identity_icon = config.identity.icon
                identity_short_name = config.identity.short_name
                identity_provider = getattr(config.identity, "provider", "file")
        except Exception:
            pass

        panel.apply_home_local_snapshot(
            build_home_node_local_state(
                system_info=system_info,
                primary_interface=primary_interface,
                removable_count=removable_count,
                hardware_error=hardware_error,
                mode=mode,
                identity_display_name=identity_display_name,
                identity_icon=identity_icon,
                identity_short_name=identity_short_name,
                identity_provider=identity_provider,
            )
        )

    def _apply_local_daemon_snapshot(
        self,
        panel: NodeInfoPanel,
        *,
        daemon_state: object,
        mesh_device_infos: tuple[object, ...],
        raw_status: object | None = None,
    ) -> None:
        """Push daemon state into the Home status panel."""
        mesh_node_count = panel._apply_mesh_catalog_count(mesh_device_infos)
        home_snapshot = build_home_node_info_state(
            daemon_state=daemon_state,
            daemon_status=raw_status,
            mesh_node_count=mesh_node_count,
        )
        panel.apply_home_snapshot(home_snapshot)

    def compose(self) -> ComposeResult:
        yield Header()
        yield VersionMismatchBanner()
        with Container(id="dashboard-container"):
            yield HighlightedPanel(
                NodeInfoPanel(id="node-info-panel-widget"),
                title="HOME STATUS",
                id="node-info-panel",
            )
            yield HighlightedPanel(
                CommsSummaryWidget(id="comms-summary-widget"),
                title="COMMS",
                id="comms-summary-panel",
            )
        yield Footer()

    def action_open_exploration(self) -> None:
        """Open the canonical Nodes workspace."""
        self.app.action_open_nodes()  # type: ignore[union-attr]

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
        """D: dismiss the version mismatch banner."""
        try:
            self.query_one(VersionMismatchBanner).hide()
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
            daemon_manager = getattr(self.app, "_daemon_manager", None)  # type: ignore[union-attr]
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
        try:
            node_info = self.query_one(NodeInfoPanel)
            self._apply_local_panel_snapshot(node_info)
            if self._ipc_bridge is None:
                node_info.refresh_data()
        except Exception:
            pass

        self.notify("Refreshed")

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

        try:
            self.app._check_for_updates()  # type: ignore[union-attr]
        except Exception:
            pass

    async def _fetch_daemon_status(self) -> None:
        """Fetch Home status from daemon and push into NodeInfoPanel."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            panel = self.query_one(NodeInfoPanel)
        except Exception:
            return

        import asyncio

        tasks = {
            "status": asyncio.create_task(bridge.get_status()),
            "identity": asyncio.create_task(bridge.get_identity()),
            "hub": asyncio.create_task(bridge.get_hub_status()),
            "config": asyncio.create_task(bridge.get_core_config()),
            "mesh_devices": asyncio.create_task(bridge.get_devices(styrene_only=True)),
            "conversations": asyncio.create_task(bridge.get_conversations()),
            "contacts": asyncio.create_task(bridge.get_contacts()),
            "auto_reply": asyncio.create_task(bridge.get_auto_reply()),
        }

        try:
            try:
                status = await tasks["status"]
                identity = await tasks["identity"]
                hub_data = await tasks["hub"]
                core_config = await tasks["config"]
                mesh_devices = tuple(await tasks["mesh_devices"])
            except Exception:
                panel.daemon_connected = False
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

            daemon_state = build_local_daemon_state(
                LocalDaemonInputs(
                    daemon_status=status,
                    identity_info=identity,
                    hub_status=hub_data if isinstance(hub_data, dict) else None,
                    core_config=core_config if isinstance(core_config, dict) else None,
                )
            )
            self._apply_local_daemon_snapshot(
                panel,
                daemon_state=daemon_state,
                mesh_device_infos=mesh_devices,
                raw_status=status,
            )

            convs: list[dict[str, Any]] = []
            contacts: list[dict[str, Any]] = []
            auto_reply: dict[str, Any] = {}

            try:
                convs = await tasks["conversations"]
            except Exception:
                pass
            try:
                contacts = await tasks["contacts"]
            except Exception:
                pass
            try:
                auto_reply = await tasks["auto_reply"]
            except Exception:
                pass

            mesh_node_count = panel.styrene_mesh_count
            home_snapshot = build_home_node_info_state(
                daemon_state=daemon_state,
                daemon_status=status,
                mesh_node_count=mesh_node_count,
                conversations=convs,
                contacts=contacts,
                auto_reply=auto_reply,
            )
            panel.apply_home_snapshot(home_snapshot)
        finally:
            pending = [t for t in tasks.values() if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)


