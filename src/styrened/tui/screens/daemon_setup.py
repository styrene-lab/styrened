"""Daemon setup screen — guides operator through starting/installing styrened.

Shown when the TUI detects no running daemon on startup. Offers three paths:

    1. Install as Service (recommended) — launchd/systemd persistent service
    2. Start Now — session-only subprocess via DaemonManager
    3. Skip — offline mode, no daemon

Returns:
    True if daemon started successfully, False if skipped.
"""

from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static

from styrened.tui.services.service_installer import (
    ServicePlatform,
    ServiceStatus,
    detect_platform,
    install_service,
)


class DaemonSetupScreen(Screen[bool]):
    """Guides the operator through daemon startup.

    Detects the platform and offers appropriate options for starting
    the styrened daemon. Returns True if daemon started successfully,
    False if the operator chose to skip.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "skip", "Skip"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._platform = ServicePlatform.UNSUPPORTED

    def compose(self) -> ComposeResult:
        """Compose the daemon setup layout."""
        yield Static("DAEMON SETUP", classes="wizard-title")

        with Container(id="daemon-setup-content"):
            # Info panel
            with Vertical(id="daemon-info"):
                yield Static(
                    "",
                    id="daemon-info-text",
                    classes="wizard-text",
                )

            yield Label("")

            # Action buttons
            with Vertical(id="daemon-actions"):
                yield Button(
                    "Install as Service (Recommended)",
                    variant="primary",
                    id="btn-install-service",
                )
                yield Label(
                    "  Persists across reboots via launchd/systemd",
                    classes="wizard-help",
                )
                yield Label("")

                yield Button(
                    "Start Now (Session Only)",
                    variant="default",
                    id="btn-start-now",
                )
                yield Label(
                    "  Runs daemon as subprocess for this session",
                    classes="wizard-help",
                )
                yield Label("")

                yield Button(
                    "Skip (Offline Mode)",
                    variant="default",
                    id="btn-skip",
                )
                yield Label(
                    "  Continue without daemon — limited functionality",
                    classes="wizard-help",
                )

            yield Label("")

            # Status area
            yield Static("", id="daemon-status")

    def on_mount(self) -> None:
        """Detect platform and update info text."""
        self._platform = detect_platform()
        self._update_info_text()

    def _update_info_text(self) -> None:
        """Update the info panel based on detected platform."""
        info = self.query_one("#daemon-info-text", Static)

        platform_name = {
            ServicePlatform.LAUNCHD: "macOS (launchd)",
            ServicePlatform.SYSTEMD: "Linux (systemd)",
            ServicePlatform.UNSUPPORTED: "this platform",
        }.get(self._platform, "this platform")

        if self._platform == ServicePlatform.UNSUPPORTED:
            info.update(
                "[bold]No running daemon detected[/]\n\n"
                "The styrened daemon provides mesh networking services.\n"
                "Service installation is not supported on this platform.\n"
                "You can start the daemon manually or run in offline mode."
            )
            # Disable install button on unsupported platforms
            self.query_one("#btn-install-service", Button).disabled = True
        else:
            info.update(
                "[bold]No running daemon detected[/]\n\n"
                "The styrened daemon provides mesh networking services.\n"
                f"Detected platform: {platform_name}\n\n"
                "Choose how to start the daemon:"
            )

    @on(Button.Pressed, "#btn-install-service")
    def on_install_service(self) -> None:
        """Install styrened as a system service."""
        self._disable_buttons()
        self._show_status("Installing service...")
        self._do_install_service()

    @on(Button.Pressed, "#btn-start-now")
    def on_start_now(self) -> None:
        """Start daemon as a managed subprocess."""
        self._disable_buttons()
        self._show_status("Starting daemon...")
        self._do_start_now()

    @on(Button.Pressed, "#btn-skip")
    def on_skip(self) -> None:
        """Skip daemon setup and continue in offline mode."""
        self.dismiss(False)

    def action_skip(self) -> None:
        """Skip via escape key."""
        self.dismiss(False)

    @work(exclusive=True)
    async def _do_install_service(self) -> None:
        """Install service in background worker."""
        try:
            info = await install_service()

            if info.status == ServiceStatus.ERROR:
                self._show_status(
                    f"Installation failed: {info.error}",
                    success=False,
                )
                self._enable_buttons()
                return

            # Verify daemon is reachable via IPC
            if await self._verify_ipc():
                self._show_status("Service installed and daemon running")
                self.dismiss(True)
            else:
                self._show_status(
                    "Service installed but daemon not yet reachable. "
                    "It may need a moment to start.",
                    success=False,
                )
                self._enable_buttons()

        except Exception as e:
            self._show_status(f"Error: {e}", success=False)
            self._enable_buttons()

    @work(exclusive=True)
    async def _do_start_now(self) -> None:
        """Start daemon as subprocess in background worker."""
        try:
            from styrened.tui.services.daemon_manager import DaemonManager, DaemonMode

            manager = DaemonManager(mode=DaemonMode.MANAGED)
            if await manager.ensure_running():
                # Store reference so app can use it
                self.app._daemon_manager_from_setup = manager
                self._show_status("Daemon started")
                self.dismiss(True)
            else:
                self._show_status(
                    "Failed to start daemon — check logs for details",
                    success=False,
                )
                self._enable_buttons()

        except Exception as e:
            self._show_status(f"Error: {e}", success=False)
            self._enable_buttons()

    async def _verify_ipc(self, timeout: float = 10.0) -> bool:
        """Verify daemon is reachable via IPC ping.

        Args:
            timeout: Maximum time to wait for daemon to respond.

        Returns:
            True if daemon responded to ping.
        """
        import asyncio

        from styrened.ipc import ControlClient, get_default_socket_path

        socket_path = get_default_socket_path()
        elapsed = 0.0
        interval = 0.5

        while elapsed < timeout:
            if socket_path.exists():
                try:
                    client = ControlClient(socket_path=socket_path, timeout=3.0)
                    try:
                        await client.connect()
                        result = await client.ping(timeout=2.0)
                        if result:
                            return True
                    finally:
                        await client.disconnect()
                except Exception:
                    pass

            await asyncio.sleep(interval)
            elapsed += interval

        return False

    def _disable_buttons(self) -> None:
        """Disable all action buttons during async operations."""
        for btn_id in ("#btn-install-service", "#btn-start-now", "#btn-skip"):
            self.query_one(btn_id, Button).disabled = True

    def _enable_buttons(self) -> None:
        """Re-enable action buttons after operation completes."""
        for btn_id in ("#btn-install-service", "#btn-start-now", "#btn-skip"):
            btn = self.query_one(btn_id, Button)
            btn.disabled = False

        # Keep install disabled on unsupported platforms
        if self._platform == ServicePlatform.UNSUPPORTED:
            self.query_one("#btn-install-service", Button).disabled = True

    def _show_status(self, message: str, success: bool = True) -> None:
        """Update the status display.

        Args:
            message: Status message to show.
            success: Whether this is a success (green) or error (red) message.
        """
        status = self.query_one("#daemon-status", Static)
        if success:
            status.update(f"[bold]{message}[/]")
        else:
            status.update(f"[bold red]{message}[/]")
