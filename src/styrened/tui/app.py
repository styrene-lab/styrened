from __future__ import annotations

"""Styrene TUI Application."""

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.engine import Engine
from textual import work
from textual.app import App, ComposeResult

if TYPE_CHECKING:
    from styrened.protocols.chat import ChatProtocol
    from styrened.tui.models.config import DeploymentMode, PeerConfig
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header

from styrened.tui.models.config import ConfigLoadError, ConfigValidationError, StyreneConfig
from styrened.tui.screens.comms import CommsScreen
from styrened.tui.screens.contacts import ContactsScreen
from styrened.tui.screens.exchange import ExchangeScreen
from styrened.tui.screens.daemon_setup import DaemonSetupScreen
from styrened.tui.screens.splash import SplashScreen
from styrened.tui.screens.dashboard import DashboardScreen
from styrened.tui.screens.exploration import ExplorationScreen
from styrened.tui.screens.first_run_wizard import FirstRunWizardScreen
from styrened.tui.screens.provision import ProvisionScreen
from styrened.tui.screens.settings import SettingsScreen
from styrened.tui.services.app_lifecycle import StyreneLifecycle
from styrened.tui.services.device_cache import DeviceCache
from styrened.ipc.bridge import IPCBridge
from styrened.tui.services.config import (
    ensure_directories,
    get_default_config,
    load_config,
    rns_config_exists,
    save_rns_config,
    update_styrene_config_from_cli,
)
from styrened.tui.services.reticulum import find_reticulum_config
from styrened.tui.themes.color_cascade import FORGE_WORLD_PRESETS, ColorCascade
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


# ---------------------------------------------------------------------------
# macOS-friendly Input bindings
# ---------------------------------------------------------------------------
# Textual's Input only has ctrl-based shortcuts (Unix/Emacs).  macOS users
# expect Option+Arrow for word navigation and Option+Backspace for
# delete-word.  Patch these onto Input.BINDINGS so every Input in the TUI
# gets them automatically.
def _patch_input_bindings() -> None:
    from textual.widgets import Input

    _mac_bindings = [
        Binding("alt+left", "cursor_left_word", "Word left", show=False),
        Binding("alt+right", "cursor_right_word", "Word right", show=False),
        Binding("alt+shift+left", "cursor_left_word(True)", "Select word left", show=False),
        Binding("alt+shift+right", "cursor_right_word(True)", "Select word right", show=False),
        Binding("alt+backspace", "delete_left_word", "Delete word left", show=False),
        Binding("alt+delete", "delete_right_word", "Delete word right", show=False),
        # super+arrow → home/end (Cmd+Left/Right on macOS)
        Binding("super+left", "home", "Line start", show=False),
        Binding("super+right", "end", "Line end", show=False),
        Binding("super+shift+left", "home(True)", "Select to start", show=False),
        Binding("super+shift+right", "end(True)", "Select to end", show=False),
        Binding("super+backspace", "delete_left_all", "Delete to start", show=False),
        Binding("super+a", "select_all", "Select all", show=False),
    ]
    existing_keys = {b.key for b in Input.BINDINGS}
    for b in _mac_bindings:
        if b.key not in existing_keys:
            Input.BINDINGS.append(b)

_patch_input_bindings()


class StyreneApp(App[None]):
    """Styrene fleet provisioning and management TUI.

    Attributes:
        config: Application configuration loaded at startup.
    """

    TITLE = "STYRENE"
    SUB_TITLE = "Management"

    CSS_PATH = Path(__file__).parent / "styles" / "styrene.tcss"

    # Keybinding hierarchy - see docs/KEYMAP.md for design rationale
    # Priority bindings bypass widget focus and always work
    # App-level bindings work when not overridden by screen/widget
    BINDINGS: ClassVar[list[BindingType]] = [
        # Priority bindings (always work regardless of focus)
        Binding("ctrl+c", "interrupt", "Quit", show=False, priority=True),
        # Global navigation
        Binding("?", "toggle_help", "Help", show=True),
        Binding("grave_accent", "open_admin", "Admin", show=True),
        Binding("n", "open_nodes", "Nodes", show=True),
        Binding("x", "open_exchange", "Exchange", show=True),
        Binding("m", "open_mail", "Mail", show=True),
        Binding("c", "open_comms", "Comms", show=False),
        Binding("b", "open_contacts", "Contacts", show=False),
        # Backward-compatible / admin-adjacent shortcuts
        Binding("i", "open_mail", "Mail", show=False),
        # Screen shortcuts (can be overridden by screens)
        Binding("p", "open_provision", "Provision", show=False),
        Binding("ctrl+r", "restart_daemon", "Restart Daemon", show=False),
        Binding("a", "announce", "Announce", show=True),
    ]

    SCREENS: ClassVar[dict[str, type[Screen[Any]]]] = {  # type: ignore[assignment]
        "comms": CommsScreen,
        "contacts": ContactsScreen,
        "dashboard": DashboardScreen,
        "exchange": ExchangeScreen,
        "exploration": ExplorationScreen,
        "provision": ProvisionScreen,
    }

    # Double ctrl+c to quit (single ctrl+c pops back to dashboard)
    _last_interrupt: float = 0.0
    _INTERRUPT_WINDOW: float = 1.0  # seconds

    def action_interrupt(self) -> None:
        """Handle ctrl+c: pop to dashboard on first press, quit on double press."""
        now = time.monotonic()
        if now - self._last_interrupt < self._INTERRUPT_WINDOW:
            # Double ctrl+c — exit
            self.exit()
            return
        self._last_interrupt = now

        # If we're on a non-default screen, pop back toward dashboard
        if len(self.screen_stack) > 1:
            self.pop_screen()
            return

        # Already on dashboard — notify about double-press to quit
        self.notify("Press Ctrl+C again to quit", severity="warning", timeout=2)

    def _screen_in_stack(self, screen_type: type) -> bool:
        """Return True if any screen in the current stack is an instance of screen_type."""
        return any(isinstance(s, screen_type) for s in self.screen_stack)

    def _current_screen_name(self) -> str:
        """Return the name/id of the current top-of-stack screen."""
        return getattr(self.screen, "name", "") or ""

    def _toggle_screen(self, name: str) -> None:
        """Switch to named screen, or return to dashboard if already there."""
        if self._current_screen_name() == name:
            self.switch_screen("dashboard")
        else:
            self.switch_screen(name)

    def action_open_admin(self) -> None:
        """Toggle the Admin/Settings overlay."""
        if self._screen_in_stack(SettingsScreen):
            self.pop_screen()
        else:
            self.push_screen(SettingsScreen(self.config))

    def action_push_screen_settings(self) -> None:
        """Backward-compatible alias for action_open_admin."""
        self.action_open_admin()

    def action_open_nodes(self) -> None:
        """Toggle the Mesh/Nodes workspace."""
        self._toggle_screen("exploration")

    def action_open_exchange(self) -> None:
        """Toggle the Exchange workspace."""
        self._toggle_screen("exchange")

    def action_open_mail(self) -> None:
        """Open Exchange on Mail tab, or return to dashboard if already on Exchange."""
        from styrened.tui.screens.exchange import ExchangeScreen, TAB_MAIL

        if self._current_screen_name() == "exchange":
            self.switch_screen("dashboard")
            return
        screen = self.get_screen("exchange")
        if isinstance(screen, ExchangeScreen):
            screen.focus_tab(TAB_MAIL)
        self.switch_screen("exchange")

    def action_open_inbox(self) -> None:
        """Backward-compatible alias for opening the Mail workspace."""
        self.action_open_mail()

    def action_open_comms(self) -> None:
        """Open Exchange on Direct tab, or return to dashboard if already on Exchange."""
        from styrened.tui.screens.exchange import ExchangeScreen, TAB_DIRECT

        if self._current_screen_name() == "exchange":
            self.switch_screen("dashboard")
            return
        screen = self.get_screen("exchange")
        if isinstance(screen, ExchangeScreen):
            screen.focus_tab(TAB_DIRECT)
        self.switch_screen("exchange")

    def action_open_contacts(self) -> None:
        """Open Exchange on Contacts tab, or return to dashboard if already on Exchange."""
        from styrened.tui.screens.exchange import ExchangeScreen, TAB_CONTACTS

        if self._current_screen_name() == "exchange":
            self.switch_screen("dashboard")
            return
        screen = self.get_screen("exchange")
        if isinstance(screen, ExchangeScreen):
            screen.focus_tab(TAB_CONTACTS)
        self.switch_screen("exchange")

    def action_open_provision(self) -> None:
        """Toggle the device provisioning workspace."""
        self._toggle_screen("provision")

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

    # Database engine for message persistence
    db_engine: Engine | None

    # Chat protocol for LXMF messaging
    chat_protocol: "ChatProtocol | None"

    # Local identity hash for message attribution
    local_identity_hash: str

    # ── TUIServices protocol implementation ──────────────────────────
    # Screens and widgets access daemon functionality via self.app.services
    # See styrened.tui.services.protocol.TUIServices for the contract.

    @property
    def services(self) -> "StyreneApp":
        """Typed service accessor for screens/widgets.

        Returns self (StyreneApp implements TUIServices protocol).
        """
        return self

    @property
    def bridge(self) -> IPCBridge | None:
        """IPC bridge for daemon communication.

        Part of the TUIServices protocol.  Screens should use
        ``self.app.services.bridge`` instead of reaching into
        ``self.app._lifecycle.ipc_bridge``.

        Returns None before IPC connection is established.
        """
        return self._lifecycle.ipc_bridge

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
        self._daemon_manager_from_setup: Any = None  # Set by DaemonSetupScreen

        # Unified device cache — started in _initialize_services once bridge is up.
        self.device_cache: DeviceCache = DeviceCache(bridge=None)

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

        self._apply_saved_theme()

    def _apply_saved_theme(self) -> None:
        """Register and apply the theme saved in tui.yaml.

        If a custom_theme_url is configured, fetch it (blocking, at startup).
        Falls back to the built-in Styrene theme on any error.
        """
        theme_name = self.config.tui.theme or STYRENE_THEME_KEY
        custom_colors = self.config.tui.custom_theme_colors
        custom_url = self.config.tui.custom_theme_url

        if custom_colors:
            # Prefer saved color dict — no network fetch needed
            try:
                from styrened.tui.themes.tweakcn import TweakcnProfile

                profile = TweakcnProfile.from_color_dict(
                    custom_colors,
                    name=theme_name,
                    source_url=custom_url,
                )
                theme = profile.to_textual_theme("dark")
                self.register_theme(theme)
                self._registered_themes[theme.name] = theme
                theme_name = theme.name
            except Exception as e:
                self.log.warning(f"Failed to apply saved theme colors: {e}")
                theme_name = STYRENE_THEME_KEY
        elif custom_url:
            try:
                from styrened.tui.themes.tweakcn import TweakcnProfile

                profile = TweakcnProfile.from_url(custom_url, timeout=8)
                theme = profile.to_textual_theme("dark")
                self.register_theme(theme)
                self._registered_themes[theme.name] = theme
                theme_name = theme.name
            except Exception as e:
                self.log.warning(f"Failed to fetch custom theme {custom_url!r}: {e}")
                theme_name = STYRENE_THEME_KEY

        if theme_name != STYRENE_THEME_KEY and theme_name not in self._registered_themes:
            # Unknown name — fall back gracefully
            self.log.warning(f"Saved theme {theme_name!r} not registered; using default")
            theme_name = STYRENE_THEME_KEY

        if theme_name != self.theme:
            self.theme = theme_name

    async def _initialize_services(self) -> None:
        """Initialize all services asynchronously via IPC.

        The daemon is spawned and connected before proceeding.
        RPC and chat go through the IPC bridge.
        """
        success = await self._lifecycle.initialize_async()

        if not success:
            self.log.warning("Service initialization failed - running in offline mode")

        # All RPC/chat flows through the IPC bridge.
        self.log.info("IPC mode active — all service calls via IPCBridge")

        # Wire the unified device cache to the live bridge.
        # Bulk priming is started after the initial screen paints so Home
        # liveness/status work is not coupled to startup hydration.
        self.device_cache.update_bridge(self.bridge)

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
        # Show intro animation while daemon connection is established.
        # SplashScreen runs _check_daemon() internally and dismisses with
        # True (daemon ok) or False (timed out → setup needed).
        self.push_screen(SplashScreen(), callback=self._on_splash_complete)

    async def _on_splash_complete(self, daemon_ok: bool) -> None:
        """Called when SplashScreen dismisses."""
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

        If no daemon is found, attempts to start one automatically before
        falling back to the setup screen.  This handles post-upgrade restarts
        where the old daemon was killed but the new one hasn't started yet.

        Returns:
            True if daemon is reachable, False otherwise.
        """
        if await self._ping_daemon():
            return True

        # Daemon not running — try starting it automatically
        self.log.info("Daemon not reachable, attempting auto-start...")
        await self._auto_start_daemon()

        # Poll for daemon readiness (up to 8 seconds)
        import asyncio

        for _ in range(16):
            await asyncio.sleep(0.5)
            if await self._ping_daemon():
                self.log.info("Daemon auto-started successfully")
                return True

        return False

    async def _ping_daemon(self) -> bool:
        """Single IPC ping attempt."""
        try:
            from styrened.ipc import ControlClient, get_default_socket_path

            socket_path = get_default_socket_path()
            if not socket_path.exists():
                return False

            client = ControlClient(socket_path=socket_path, timeout=3.0)
            try:
                await client.connect()
                return await client.ping(timeout=2.0)
            finally:
                await client.disconnect()
        except Exception:
            return False

    async def _auto_start_daemon(self) -> None:
        """Try to start the daemon in the background."""
        import shutil
        import subprocess

        exe = shutil.which("styrened")
        if not exe:
            self.log.warning("styrened binary not found in PATH")
            return
        try:
            subprocess.Popen(
                [exe, "daemon"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.log.info(f"Started daemon: {exe} daemon")
        except Exception as e:
            self.log.warning(f"Failed to auto-start daemon: {e}")

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
        """Push the upgrade modal screen (no-op if already in stack)."""
        from styrened.tui.screens.upgrade import UpgradeScreen

        if self._screen_in_stack(UpgradeScreen):
            return

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

        self.call_after_refresh(self._start_device_cache)

    def _start_device_cache(self) -> None:
        """Start shared device cache priming after initial UI paint."""
        self.device_cache.start(self)

    def _on_wizard_complete(self, result: bool | None) -> None:
        """Handle wizard completion.

        Args:
            result: True if config was created, False if skipped, None if dismissed.
        """
        if result:
            # User created config - daemon will pick up changes on restart
            self.log.info("Reticulum config created - restart daemon to apply")
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

        # Update the global ColorCascade to match the new theme
        self._sync_cascade_to_theme(new_theme)

        # Refresh all HighlightedPanel borders
        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        # Refresh dashboard panels that use Rich markup
        self._refresh_themed_panels()

    def _sync_cascade_to_theme(self, theme_name: str) -> None:
        """Sync the global ColorCascade to the active Textual theme."""
        if theme_name == STYRENE_THEME_KEY:
            set_color_cascade(create_styrene_cascade())
        elif theme_name in FORGE_WORLD_PRESETS:
            set_color_cascade(ColorCascade.from_preset(theme_name))
        else:
            # Custom/tweakcn/builtin theme — derive cascade from Theme object
            try:
                theme_obj = self._registered_themes.get(theme_name)
                if theme_obj is None:
                    # Try Textual built-in themes (nord, dracula, etc.)
                    from textual.theme import BUILTIN_THEMES
                    theme_obj = BUILTIN_THEMES.get(theme_name)
                if theme_obj is not None:
                    set_color_cascade(ColorCascade.from_textual_theme(theme_obj))
            except Exception:
                pass  # Keep existing cascade on error

    def _refresh_themed_panels(self) -> None:
        """Refresh panels that use Rich markup with cascade colors."""
        # Import here to avoid circular imports
        from styrened.tui.widgets.node_info_panel import NodeInfoPanel

        # Refresh NodeInfoPanel
        for panel in self.query(NodeInfoPanel):
            panel.refresh_data()

    def on_device_cache_devices_updated(self, message: "DeviceCache.DevicesUpdated") -> None:
        """Fan-out DevicesUpdated to all mounted screens.

        DeviceCache.post_message delivers to the App widget only — Textual
        messages bubble up, not down.  This handler re-posts to every Screen
        currently in the DOM so each can react independently.
        """
        from textual.screen import Screen

        for screen in self.query(Screen):
            try:
                screen.post_message(message.__class__(message.devices))
            except Exception:
                pass

    async def on_shutdown(self) -> None:
        """Cleanup on app exit.

        Stops discovery, disconnects from hub, and shuts down RNS service.
        Uses async shutdown to properly clean up IPC connections.
        """
        try:
            self.device_cache.stop()
        except Exception:
            pass
        try:
            await self._lifecycle.shutdown_async()
        except Exception as e:
            self.log.error(f"Error during shutdown: {e}")
