"""Fleet operations widget for executing whitelisted commands on devices via RPC.

Structured fleet operations over LXMF store-and-forward — this is NOT a shell.
Commands are restricted to a server-side whitelist discovered via ping.

Features:
- Ping: Measures RTT and populates available_commands from server whitelist
- Available commands: Displayed as informational text (server capabilities)
- Presets: Common operation combos filtered against available_commands
- Reboot: Double-tap confirmation with 3s auto-cancel
- Session log: Scrollable output with color-coded exit codes
- Routes all commands through IPCBridge (daemon IPC)
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Static

logger = logging.getLogger(__name__)

# Reboot confirmation timeout (seconds)
_REBOOT_CONFIRM_TIMEOUT = 3.0

# Update confirmation timeout (seconds)
_UPDATE_CONFIRM_TIMEOUT = 3.0

# Fleet operation presets
FLEET_OP_PRESETS: list[tuple[str, str]] = [
    ("uptime", "uptime"),
    ("df -h", "df -h"),
    ("free -h", "free -h"),
    ("uname -a", "uname -a"),
    ("failed units", "systemctl list-units --failed"),
    ("styrened logs", "journalctl -u styrened --no-pager -n 20"),
    ("rnstatus", "rnstatus"),
    ("ps aux", "ps aux"),
]


@dataclass
class OutputEntry:
    """A single entry in the session log."""

    command: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    rtt_ms: float | None = None
    entry_type: str = "exec"  # exec, ping, reboot, system


class CommandWidget(Widget):
    """Fleet operations widget for structured RPC commands over LXMF.

    Executes whitelisted commands on remote devices via store-and-forward
    RPC — not an interactive shell. Commands are restricted to a server-side
    whitelist discovered via ping.

    Provides a toolbar, available command display, presets, and session log.

    Attributes:
        device_identity: Reticulum identity hash of target device.
    """

    BINDINGS: ClassVar[list[BindingType]] = []

    executing: reactive[bool] = reactive(False)

    def __init__(
        self,
        device_identity: str,
        initial_available_commands: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.device_identity = device_identity
        self._available_commands: list[str] = initial_available_commands or []
        self._output_entries: list[OutputEntry] = []
        self._reboot_armed: bool = False
        self._reboot_confirm_timer: Timer | None = None
        self._update_armed: bool = False
        self._update_confirm_timer: Timer | None = None

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app.services.bridge
        except Exception:
            return None

    def _no_bridge_error(self, label: str, entry_type: str = "system") -> None:
        """Show error when IPC bridge is unavailable.

        Args:
            label: Command label for the output entry.
            entry_type: Entry type for rendering (e.g. "ping", "reboot").
        """
        self._append_output(OutputEntry(
            command=label,
            stderr="Not connected to daemon (IPC bridge unavailable)",
            entry_type=entry_type,
        ))

    def compose(self) -> ComposeResult:
        """Compose widget layout."""
        # Toolbar
        with Horizontal(id="cmd-toolbar"):
            yield Button("Ping", id="cmd-ping", variant="default")
            yield Button("Reboot...", id="cmd-reboot", classes="-danger")
            yield Button("Update...", id="cmd-update", classes="-danger")
            yield Button("Clear", id="cmd-clear", variant="default")
            yield Static("", id="cmd-status", classes="cmd-status-text")

        # Available commands (informational)
        yield Static("", id="cmd-available", classes="cmd-available-bar")

        # Presets
        with Horizontal(id="cmd-presets"):
            pass  # Populated dynamically

        # Session log
        with VerticalScroll(id="cmd-session-log"):
            yield Static("", id="cmd-log-content", classes="cmd-log-content")

    def on_mount(self) -> None:
        """Populate available commands and presets on mount."""
        self._refresh_available_display()
        self._refresh_presets()
        if not self._available_commands:
            # Auto-ping to populate available commands
            self.run_worker(self._do_ping(), name="auto-ping")

    def _refresh_available_display(self) -> None:
        """Update the available commands display."""
        try:
            label = self.query_one("#cmd-available", Static)
        except Exception:
            return

        if not self._available_commands:
            label.update("[dim]No available commands yet — ping to discover server whitelist[/]")
        else:
            tags = "  ".join(self._available_commands)
            label.update(f"[bold]Available:[/] {tags}")

    def _refresh_presets(self) -> None:
        """Refresh preset buttons filtered by available commands."""
        try:
            container = self.query_one("#cmd-presets", Horizontal)
        except Exception:
            return

        # Remove existing preset buttons
        for child in list(container.children):
            child.remove()

        # Filter presets by available commands
        for label, cmd_string in FLEET_OP_PRESETS:
            base_cmd = cmd_string.split()[0]
            if not self._available_commands or base_cmd in self._available_commands:
                btn = Button(
                    label,
                    classes="cmd-preset-btn",
                    name=cmd_string,
                )
                container.mount(btn)

    def _set_status(self, text: str) -> None:
        """Update the status text in the toolbar."""
        try:
            status = self.query_one("#cmd-status", Static)
            status.update(text)
        except Exception:
            pass

    def _append_output(self, entry: OutputEntry) -> None:
        """Add an entry to the session log and refresh display."""
        self._output_entries.append(entry)
        self._refresh_log()

    def _refresh_log(self) -> None:
        """Re-render the session log from entries."""
        try:
            log_widget = self.query_one("#cmd-log-content", Static)
            scroll = self.query_one("#cmd-session-log", VerticalScroll)
        except Exception:
            return

        lines: list[str] = []
        for entry in self._output_entries:
            if entry.entry_type == "ping":
                if entry.rtt_ms is not None:
                    lines.append(f"[bold]PING[/] → [green]OK[/] ({entry.rtt_ms:.0f}ms)")
                else:
                    lines.append(f"[bold]PING[/] → [red]FAILED[/]: {entry.stderr}")
            elif entry.entry_type == "reboot":
                if entry.exit_code == 0:
                    lines.append(f"[bold]REBOOT[/] → [green]{entry.stdout}[/]")
                else:
                    lines.append(f"[bold]REBOOT[/] → [red]{entry.stderr}[/]")
            elif entry.entry_type == "system":
                lines.append(f"[dim]{entry.stdout}[/]")
            else:
                # exec
                lines.append(f"[bold]$ {entry.command}[/]")
                if entry.stdout:
                    lines.append(entry.stdout.rstrip())
                if entry.stderr:
                    lines.append(f"[red]{entry.stderr.rstrip()}[/]")
                if entry.exit_code is not None:
                    if entry.exit_code == 0:
                        lines.append(f"[green][exit {entry.exit_code}][/]")
                    else:
                        lines.append(f"[red][exit {entry.exit_code}][/]")
                lines.append("")  # blank separator

        log_widget.update("\n".join(lines) if lines else "[dim]No fleet operations executed yet — ping to discover available commands[/]")
        # Auto-scroll to bottom
        scroll.scroll_end(animate=False)

    # -------------------------------------------------------------------------
    # Actions / Handlers
    # -------------------------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button_id = str(event.button.id)

        if button_id == "cmd-ping":
            self.run_worker(self._do_ping(), name="ping")
        elif button_id == "cmd-reboot":
            await self._handle_reboot()
        elif button_id == "cmd-update":
            await self._handle_update()
        elif button_id == "cmd-clear":
            self._output_entries.clear()
            self._refresh_log()

        # Preset buttons have no id, use name
        if event.button.name and event.button.has_class("cmd-preset-btn"):
            self.run_worker(
                self._execute_command_string(event.button.name),
                name="preset-exec",
            )

    # -------------------------------------------------------------------------
    # Reboot double-tap confirmation
    # -------------------------------------------------------------------------

    async def _handle_reboot(self) -> None:
        """Handle reboot button — requires double-tap within timeout."""
        if self._reboot_armed:
            # Second tap — execute reboot
            self._disarm_reboot()
            self.run_worker(self._do_reboot(), name="reboot")
        else:
            # First tap — arm
            self._reboot_armed = True
            try:
                btn = self.query_one("#cmd-reboot", Button)
                btn.label = "CONFIRM?"
            except Exception:
                pass
            self._set_status("[bold red]Press Reboot again within 3s to confirm[/]")
            self._reboot_confirm_timer = self.set_timer(
                _REBOOT_CONFIRM_TIMEOUT, self._disarm_reboot
            )

    def _disarm_reboot(self) -> None:
        """Cancel reboot confirmation state."""
        self._reboot_armed = False
        if self._reboot_confirm_timer is not None:
            self._reboot_confirm_timer.stop()
            self._reboot_confirm_timer = None
        try:
            btn = self.query_one("#cmd-reboot", Button)
            btn.label = "Reboot..."
        except Exception:
            pass
        self._set_status("")

    # -------------------------------------------------------------------------
    # Update double-tap confirmation
    # -------------------------------------------------------------------------

    async def _handle_update(self) -> None:
        """Handle update button — requires double-tap within timeout."""
        if self._update_armed:
            # Second tap — execute update
            self._disarm_update()
            self.run_worker(self._do_update(), name="update")
        else:
            # First tap — arm
            self._update_armed = True
            try:
                btn = self.query_one("#cmd-update", Button)
                btn.label = "CONFIRM?"
            except Exception:
                pass
            self._set_status("[bold red]Press Update again within 3s to confirm[/]")
            self._update_confirm_timer = self.set_timer(
                _UPDATE_CONFIRM_TIMEOUT, self._disarm_update
            )

    def _disarm_update(self) -> None:
        """Cancel update confirmation state."""
        self._update_armed = False
        if self._update_confirm_timer is not None:
            self._update_confirm_timer.stop()
            self._update_confirm_timer = None
        try:
            btn = self.query_one("#cmd-update", Button)
            btn.label = "Update..."
        except Exception:
            pass
        self._set_status("")

    # -------------------------------------------------------------------------
    # Command execution
    # -------------------------------------------------------------------------

    async def _execute_command_string(self, command_string: str) -> None:
        """Execute a command string via RPC (IPC bridge or legacy client)."""
        if not command_string.strip():
            return

        parts = command_string.split()
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        self.executing = True
        self._set_status(f"[dim]Executing: {command_string}[/]")

        try:
            bridge = self._ipc_bridge
            if bridge is not None:
                result = await bridge.send_rpc(
                    destination=self.device_identity,
                    command=command,
                    args=args,
                    timeout=60.0,
                )
                entry = OutputEntry(
                    command=command_string,
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    entry_type="exec",
                )
            else:
                self._no_bridge_error(command_string)
                return

            self._append_output(entry)
            self._set_status("")

        except Exception as e:
            self._append_output(OutputEntry(
                command=command_string,
                exit_code=-1,
                stderr=str(e),
                entry_type="exec",
            ))
            self._set_status(f"[red]Error: {e}[/]")

        finally:
            self.executing = False

    async def _do_ping(self) -> None:
        """Ping the device — measures RTT and populates available_commands."""
        self._set_status("[dim]Pinging...[/]")
        start = time.monotonic()

        try:
            bridge = self._ipc_bridge
            if bridge is not None:
                status = await bridge.query_device_status(
                    destination=self.device_identity,
                    timeout=10.0,
                )
                rtt_ms = (time.monotonic() - start) * 1000
                self._available_commands = status.available_commands or []
                self._append_output(OutputEntry(
                    command="ping",
                    rtt_ms=rtt_ms,
                    entry_type="ping",
                ))
            else:
                self._no_bridge_error("ping", entry_type="ping")
                return

            self._refresh_available_display()
            self._refresh_presets()
            self._set_status("")

        except Exception as e:
            self._append_output(OutputEntry(
                command="ping",
                stderr=str(e),
                entry_type="ping",
            ))
            self._set_status("[red]Ping failed[/]")

    async def _do_reboot(self) -> None:
        """Send reboot command to the device."""
        self._set_status("[dim]Sending reboot...[/]")

        try:
            bridge = self._ipc_bridge
            if bridge is not None:
                result = await bridge.reboot_device(
                    destination=self.device_identity,
                    delay=0,
                    timeout=10.0,
                )
                if result.success:
                    self._append_output(OutputEntry(
                        command="reboot",
                        exit_code=0,
                        stdout=result.message,
                        entry_type="reboot",
                    ))
                else:
                    self._append_output(OutputEntry(
                        command="reboot",
                        exit_code=1,
                        stderr=result.message,
                        entry_type="reboot",
                    ))
            else:
                self._no_bridge_error("reboot", entry_type="reboot")
                return

            self._set_status("")

        except Exception as e:
            self._append_output(OutputEntry(
                command="reboot",
                exit_code=1,
                stderr=str(e),
                entry_type="reboot",
            ))
            self._set_status(f"[red]Reboot failed: {e}[/]")

    async def _do_update(self) -> None:
        """Send self-update command to the device."""
        self._set_status("[dim]Sending self-update...[/]")

        try:
            bridge = self._ipc_bridge
            if bridge is not None:
                result = await bridge.self_update_device(
                    destination=self.device_identity,
                    timeout=120.0,
                )
                if result.success:
                    self._append_output(OutputEntry(
                        command="update",
                        exit_code=0,
                        stdout=result.message,
                        entry_type="system",
                    ))
                else:
                    self._append_output(OutputEntry(
                        command="update",
                        exit_code=1,
                        stderr=result.message,
                        entry_type="system",
                    ))
            else:
                self._no_bridge_error("update", entry_type="update")
                return

            self._set_status("")

        except Exception as e:
            self._append_output(OutputEntry(
                command="update",
                exit_code=1,
                stderr=str(e),
                entry_type="system",
            ))
            self._set_status(f"[red]Update failed: {e}[/]")
