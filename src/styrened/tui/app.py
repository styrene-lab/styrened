"""Styrene TUI Application."""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.engine import Engine
from textual import work
from textual.app import App, ComposeResult

if TYPE_CHECKING:
    from styrened.protocols.chat import ChatProtocol
    from styrened.rpc import RPCClient
    from styrened.tui.models.config import DeploymentMode, PeerConfig
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header

from styrened.tui.models.config import ConfigLoadError, ConfigValidationError, StyreneConfig
from styrened.tui.screens.contacts import ContactsScreen
from styrened.tui.screens.daemon_setup import DaemonSetupScreen
from styrened.tui.screens.dashboard import DashboardScreen
from styrened.tui.screens.first_run_wizard import FirstRunWizardScreen
from styrened.tui.screens.provision import ProvisionScreen
from styrened.tui.screens.settings import SettingsScreen
from styrened.tui.services.app_lifecycle import LifecycleMode, StyreneLifecycle
from styrened.tui.services.config import (
    ensure_directories,
    get_default_config,
    load_config,
    rns_config_exists,
    save_rns_config,
    update_styrene_config_from_cli,
)
from styrened.tui.services.reticulum import find_reticulum_config
from styrened.tui.themes.styrene_brand import (
    STYRENE_THEME_KEY,
    create_styrene_cascade,
    create_styrene_theme,
)
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, set_color_cascade

try:
    import textual_image.renderable  # noqa: F401
    HAS_TEXTUAL_IMAGE = True
except ImportError:
    HAS_TEXTUAL_IMAGE = False


class StyreneApp(App[None]):
    """Styrene fleet provisioning and management TUI.

    Attributes:
        config: Application configuration loaded at startup.
    """

    TITLE = "STYRENE"
    SUB_TITLE = "Management"

    CSS_PATH = Path(__file__).parent / "styles" / "imperial_crt.tcss"

    # Keybinding hierarchy - see docs/KEYMAP.md for design rationale
    # Priority bindings bypass widget focus and always work
    # App-level bindings work when not overridden by screen/widget
    BINDINGS: ClassVar[list[BindingType]] = [
        # Priority bindings (always work regardless of focus)
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        # Global navigation
        Binding("?", "toggle_help", "Help"),
        Binding("grave_accent", "push_screen_settings", "Settings", show=True),
        Binding("i", "open_inbox", "Inbox", show=True),
        Binding("b", "push_screen('contacts')", "Contacts", show=True),
        # Screen shortcuts (can be overridden by screens)
        Binding("p", "push_screen('provision')", "Provision", show=True),
        Binding("ctrl+r", "restart_daemon", "Restart Daemon", show=False),
        Binding("a", "announce", "Announce", show=True),
    ]

    SCREENS: ClassVar[dict[str, type[Screen[Any]]]] = {  # type: ignore[assignment]
        "contacts": ContactsScreen,
        "dashboard": DashboardScreen,
        "provision": ProvisionScreen,
    }

    def action_push_screen_settings(self) -> None:
        """Push settings screen with current config."""
        self.push_screen(SettingsScreen(self.config))

    def action_open_inbox(self) -> None:
        """Open inbox screen showing all conversations."""
        if self._lifecycle.ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        from styrened.tui.screens.inbox import InboxScreen

        self.push_screen(InboxScreen())

    def get_unread_count(self) -> int:
        """Get total unread message count.

        Returns:
            Number of unread messages across all conversations.
        """
        if self.db_engine is None or not self.local_identity_hash:
            return 0

        from sqlalchemy.orm import Session

        from styrened.models.messages import Message

        with Session(self.db_engine) as session:
            count = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    Message.status == "pending",
                    Message.destination_hash == self.local_identity_hash,
                )
                .count()
            )
            return count

    # Application configuration
    config: StyreneConfig

    # Lifecycle manager for standalone service initialization
    _lifecycle: StyreneLifecycle

    # RPC client for fleet communication (mock in development)
    rpc_client: "RPCClient"

    # Database engine for message persistence
    db_engine: Engine | None

    # Chat protocol for LXMF messaging
    chat_protocol: "ChatProtocol | None"

    # Local identity hash for message attribution
    local_identity_hash: str

    def __init__(
        self,
        mode: "DeploymentMode | None" = None,
        headless: bool = False,
        server_port: int | None = None,
        peers: list["PeerConfig"] | None = None,
        api_port: int | None = None,
        config_path: str | None = None,
        remote_url: str | None = None,
    ) -> None:
        """Initialize Styrene application.

        Service initialization (RNS, LXMF, RPC, chat) is deferred to
        on_mount() to support async IPC mode. Only config, themes, and
        directories are set up here.

        Args:
            mode: Deployment mode override (standalone, hub, peer).
            headless: Run in headless mode (no TUI).
            server_port: TCP server port for hub mode.
            peers: List of peer hubs to connect to.
            api_port: HTTP API port for headless mode.
            config_path: Custom config file path.
            remote_url: Remote Styrene API URL (alternative to local RNS).
        """
        # Force truecolor rendering.  Respect terminals that genuinely
        # cannot do truecolor (TERM=linux, TERM=dumb) but override
        # ambiguous or missing COLORTERM values.
        term = os.environ.get("TERM", "")
        if term not in ("linux", "dumb"):
            os.environ["COLORTERM"] = "truecolor"
            os.environ["TEXTUAL_COLOR_SYSTEM"] = "truecolor"

        # CRITICAL: Textual builds the stylesheet during super().__init__()
        # using get_css_variables(), which reads self.theme and self.dark
        # to resolve CSS variables.  Our theme is dark-only — if Textual
        # auto-detects OS light mode, it uses light theme defaults for the
        # initial stylesheet build, producing a broken palette.
        #
        # Pre-populate the theme registry, default theme, AND dark flag
        # BEFORE super().__init__() so the single stylesheet build is correct.
        self._registered_themes = {STYRENE_THEME_KEY: create_styrene_theme()}
        self.__class__._default_theme = STYRENE_THEME_KEY
        self._dark = True  # Bypass reactive; set underlying attribute

        super().__init__()

        # Ensure theme and dark mode survived init (reactive may reset)
        self.dark = True
        if self.theme != STYRENE_THEME_KEY:
            self.register_theme(create_styrene_theme())
            self.theme = STYRENE_THEME_KEY

        # Store CLI overrides
        self._mode_override = mode
        self._headless = headless
        self._server_port = server_port
        self._peers_override = peers or []
        self._api_port = api_port
        self._config_path = config_path
        self._remote_url = remote_url

        # Ensure application directories exist
        ensure_directories()

        # Load configuration
        self._load_configuration()

        # Apply CLI overrides to config
        self._apply_cli_overrides()

        # Apply color cascade for non-CSS theme consumers
        set_color_cascade(create_styrene_cascade())

        # Initialize defaults for service-layer attributes
        # Actual initialization happens in on_mount() (async)
        self.db_engine = None
        self.chat_protocol = None
        self.local_identity_hash = ""

        # Create lifecycle manager (does not initialize services yet)
        self._lifecycle = StyreneLifecycle(self.config)

    def _apply_cli_overrides(self) -> None:
        """Apply CLI argument overrides to loaded configuration."""
        # Use the config service to apply and persist CLI overrides
        self.config = update_styrene_config_from_cli(
            self.config,
            mode=self._mode_override,
            server_port=self._server_port,
            peers=self._peers_override,
            api_port=self._api_port,
            headless=self._headless,
        )

        # Log applied overrides
        if self._mode_override:
            self.log.info(f"Mode override: {self._mode_override.value}")
        if self._headless:
            self.log.info("Running in headless mode")
        if self._server_port:
            self.log.info(f"Server port override: {self._server_port}")
        if self._peers_override:
            self.log.info(f"Added {len(self._peers_override)} peer(s)")
        if self._api_port:
            self.log.info(f"API port override: {self._api_port}")

        # Generate/update RNS config if needed
        if not rns_config_exists():
            try:
                rns_path = save_rns_config(self.config)
                self.log.info(f"Generated Reticulum config: {rns_path}")
            except Exception as e:
                self.log.warning(f"Could not generate RNS config: {e}")

    def _load_configuration(self) -> None:
        """Load application configuration, falling back to defaults on error."""
        try:
            self.config = load_config()
        except ConfigLoadError as e:
            # Log error and use defaults
            self.log.error(f"Failed to load config: {e}")
            self.config = get_default_config()
        except ConfigValidationError as e:
            # Log validation errors and use defaults
            self.log.warning(f"Config validation failed: {e}")
            self.config = get_default_config()

    def _initialize_rpc_client(self) -> None:
        """Initialize RPC client for fleet communication.

        If Child 1's RPCClient is available, use it. Otherwise use mock for development.
        """
        try:
            # Try to import real RPC client from Child 1
            # Get LXMF service (from Child 0)
            from styrened.rpc import RPCClient
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if lxmf_service and lxmf_service.is_initialized:
                self.rpc_client = RPCClient(lxmf_service)
                self.log.info("RPC client initialized")
            else:
                # LXMF not available - use mock
                from styrened.rpc.offline import OfflineRPCClient

                self.rpc_client = OfflineRPCClient()  # type: ignore[assignment]
                self.log.warning("Using offline RPC client (LXMF not available)")
        except ImportError:
            # Child 0/1 not integrated yet - use offline stub
            from styrened.rpc.offline import OfflineRPCClient

            self.rpc_client = OfflineRPCClient()  # type: ignore[assignment]
            self.log.info("Using offline RPC client (development mode)")

    def _initialize_chat(self) -> None:
        """Initialize message database and chat protocol.

        Sets up SQLite database for message persistence and creates
        ChatProtocol instance for LXMF messaging.
        """
        # Initialize database
        from styrened.models.messages import init_db

        try:
            self.db_engine = init_db()
            self.log.info("Message database initialized")
        except Exception as e:
            self.log.warning(f"Failed to initialize message database: {e}")
            self.db_engine = None

        # Get local identity hash from LXMF service
        self.local_identity_hash = ""
        try:
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if lxmf_service and lxmf_service.is_initialized and lxmf_service._identity:
                self.local_identity_hash = lxmf_service._identity.hexhash
                self.log.info(f"Local identity: {self.local_identity_hash[:16]}...")
        except Exception as e:
            self.log.warning(f"Could not get local identity: {e}")

        # Initialize ChatProtocol if we have database and LXMF
        self.chat_protocol = None
        if self.db_engine is not None:
            try:
                from styrened.protocols.chat import ChatProtocol
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                if (
                    lxmf_service
                    and lxmf_service.is_initialized
                    and lxmf_service._identity
                    and lxmf_service.router
                ):
                    self.chat_protocol = ChatProtocol(
                        router=lxmf_service.router,
                        identity=lxmf_service._identity,
                        db_engine=self.db_engine,
                    )
                    self.log.info("ChatProtocol initialized")
            except Exception as e:
                self.log.warning(f"Could not initialize ChatProtocol: {e}")

    async def _initialize_services(self) -> None:
        """Initialize all services asynchronously.

        Supports both IPC and legacy modes via the lifecycle manager.
        In IPC mode, the daemon is spawned and connected before proceeding.
        In legacy mode (or fallback), services are initialized in-process.
        """
        # Try async initialization (supports IPC + legacy + auto)
        success = await self._lifecycle.initialize_async()

        if not success:
            self.log.warning("Service initialization failed - running in offline mode")

        # In legacy mode, initialize RPC client and chat in-process
        if self._lifecycle.active_mode == LifecycleMode.LEGACY:
            self._initialize_rpc_client()
            self._initialize_chat()
        elif self._lifecycle.active_mode == LifecycleMode.IPC:
            # In IPC mode, RPC and chat go through the bridge
            # Initialize offline RPC client for backward compat with screens
            # that still use self.rpc_client directly
            from styrened.rpc.offline import OfflineRPCClient

            self.rpc_client = OfflineRPCClient()  # type: ignore[assignment]
            self.log.info(
                "IPC mode active — screens should migrate to IPCBridge"
            )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    async def on_mount(self) -> None:
        """Mount handler - check daemon, initialize services, handle first-run.

        Flow:
            1. Check for updates (background, non-blocking)
            2. Check if daemon is reachable via IPC ping
            3. If no daemon → DaemonSetupScreen (install/start/skip)
            4. If daemon OK → initialize services → FirstRunWizard or Dashboard
        """
        self._check_for_updates()
        daemon_ok = await self._check_daemon()
        if not daemon_ok:
            self.log.info("No daemon detected - launching setup screen")
            self.push_screen(
                DaemonSetupScreen(),
                callback=self._on_daemon_setup_complete,
            )
        else:
            await self._proceed_after_daemon()

    async def _check_daemon(self) -> bool:
        """Quick IPC socket check — does the socket exist and respond to ping?

        Returns:
            True if daemon is reachable, False otherwise.
        """
        try:
            from styrened.ipc import ControlClient, get_default_socket_path

            socket_path = get_default_socket_path()
            if not socket_path.exists():
                return False

            client = ControlClient(socket_path=socket_path, timeout=3.0)
            try:
                await client.connect()
                result = await client.ping(timeout=2.0)
                return result
            finally:
                await client.disconnect()
        except Exception:
            return False

    @work(thread=True, exclusive=True, group="update_check")
    def _check_for_updates(self) -> None:
        """Check PyPI for a newer version (runs in background thread)."""
        from styrened import __version__
        from styrened.tui.services.update_checker import check_for_update

        result = check_for_update(__version__)
        if result and result.update_available:
            self.call_from_thread(
                self._show_upgrade_screen,
                result.current,
                result.latest,
            )

    def _restart_tui(self) -> None:
        """Shut down the Textual app and re-exec the TUI process."""
        import shutil

        def _do_exec() -> None:
            # Find the 'styrene' entry point — prefer the one that launched us
            argv0 = sys.argv[0]
            # If argv0 is a module path (-m), re-exec via python -m
            if argv0.endswith("__main__.py") or not os.path.isfile(argv0):
                exe = shutil.which("styrene") or sys.executable
                if exe == sys.executable:
                    os.execvp(exe, [exe, "-m", "styrened.tui"])
                else:
                    os.execvp(exe, [exe])
            else:
                os.execvp(argv0, [argv0])

        # Exit Textual cleanly, then exec in the exit callback
        self.exit(result=None)
        # Schedule exec after event loop teardown
        import atexit
        atexit.register(_do_exec)

    def _show_upgrade_screen(self, current: str, latest: str) -> None:
        """Push the upgrade modal screen."""
        from styrened.tui.screens.upgrade import UpgradeScreen

        def _on_upgrade_result(should_restart: bool | None) -> None:
            if should_restart:
                self._restart_tui()

        self.push_screen(UpgradeScreen(current, latest), callback=_on_upgrade_result)

    async def _on_daemon_setup_complete(self, result: bool | None) -> None:
        """Handle daemon setup screen result.

        Args:
            result: True if daemon started, False if skipped, None if dismissed.
        """
        if result:
            self.log.info("Daemon started - proceeding with initialization")
            # If a managed DaemonManager was created by the setup screen,
            # wire it into the lifecycle
            manager = getattr(self, "_daemon_manager_from_setup", None)
            if manager is not None:
                self._lifecycle._daemon_manager = manager
                delattr(self, "_daemon_manager_from_setup")
            await self._proceed_after_daemon()
        else:
            self.log.info("Daemon setup skipped - running in offline mode")
            self.push_screen("dashboard")

    async def _proceed_after_daemon(self) -> None:
        """Initialize services and continue to wizard or dashboard."""
        await self._initialize_services()

        if find_reticulum_config() is None:
            self.log.info("Reticulum not configured - launching first-run wizard")
            self.push_screen(
                FirstRunWizardScreen(),
                callback=self._on_wizard_complete,
            )
        else:
            self.push_screen("dashboard")

    def _on_wizard_complete(self, result: bool | None) -> None:
        """Handle wizard completion.

        Args:
            result: True if config was created, False if skipped, None if dismissed.
        """
        if result:
            # User created config - reinitialize services
            self.log.info("Reticulum config created - reinitializing services")
            self._lifecycle.shutdown()
            self._lifecycle._initialize_legacy()
        else:
            # User skipped - log and continue in offline mode
            self.log.info("Reticulum setup skipped - running in offline mode")

        # Proceed to dashboard
        self.push_screen("dashboard")

    def action_toggle_dark(self) -> None:
        """Override Textual's built-in dark/light toggle.

        Styrene only supports dark mode. Prevent accidental theme switches
        that would replace our custom theme with Textual's defaults.
        """
        if self.theme != STYRENE_THEME_KEY:
            self.theme = STYRENE_THEME_KEY

    def action_toggle_help(self) -> None:
        """Toggle help overlay."""
        self.bell()  # Placeholder until help screen implemented

    @work(exclusive=True, group="announce")
    async def action_announce(self) -> None:
        """Force an immediate announce to the mesh."""
        try:
            bridge = getattr(self._lifecycle, "ipc_bridge", None)
            if bridge:
                await bridge.announce()
                self.notify("Announce sent", severity="information", timeout=3)
            else:
                self.notify("No IPC connection", severity="warning", timeout=3)
        except Exception as e:
            self.notify(f"Announce failed: {e}", severity="error", timeout=5)

    @work(exclusive=True, group="daemon_restart")
    async def action_restart_daemon(self) -> None:
        """Restart the daemon process via DaemonManager or system service."""
        self.notify("Restarting daemon...", severity="information", timeout=3)

        manager = getattr(self._lifecycle, "_daemon_manager", None)
        if manager is not None:
            success = await manager.restart()
            if success:
                self.notify("Daemon restarted", severity="information", timeout=5)
            else:
                self.notify("Restart failed — try: pkill -f 'styrened daemon' && styrened daemon &",
                            severity="error", timeout=10)
        else:
            # No managed daemon — try killing and respawning
            import subprocess
            try:
                subprocess.run(["pkill", "-f", r"^.*/styrened daemon"], timeout=5)
            except Exception:
                pass

            import asyncio
            await asyncio.sleep(1)

            from styrened.tui.services.daemon_manager import DaemonManager
            manager = DaemonManager()
            started = await manager.ensure_running()
            if started:
                self._lifecycle._daemon_manager = manager
                self.notify("Daemon restarted", severity="information", timeout=5)
            else:
                self.notify("Could not restart daemon — run: styrened daemon &",
                            severity="error", timeout=10)

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        """React to theme changes - refresh all themed components."""
        if old_theme == new_theme:
            return

        # Guard against early calls before screens are mounted
        if not self._screen_stack:
            return

        # Refresh all HighlightedPanel borders
        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        # Refresh dashboard panels that use Rich markup
        self._refresh_themed_panels()

    def _refresh_themed_panels(self) -> None:
        """Refresh panels that use Rich markup with cascade colors."""
        # Import here to avoid circular imports
        from styrened.tui.screens.dashboard import MeshDeviceTable
        from styrened.tui.widgets.node_info_panel import NodeInfoPanel

        # Refresh NodeInfoPanel
        for panel in self.query(NodeInfoPanel):
            panel.refresh_data()

        # Refresh MeshDeviceTable
        for table in self.query(MeshDeviceTable):
            table.refresh_data()

    async def on_shutdown(self) -> None:
        """Cleanup on app exit.

        Stops discovery, disconnects from hub, and shuts down RNS service.
        Uses async shutdown to properly clean up IPC connections.
        """
        try:
            await self._lifecycle.shutdown_async()
        except Exception as e:
            self.log.error(f"Error during shutdown: {e}")
