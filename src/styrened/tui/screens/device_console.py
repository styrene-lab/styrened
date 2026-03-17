"""Device Console Screen - SSH-like interface for device management over LXMF."""

import logging
from datetime import timedelta
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, RichLog, Static

from styrened.rpc.errors import RPCTimeoutError
from styrened.rpc.messages import (
    ExecResult,
    RebootResult,
    StatusResponse,
    UpdateConfigResult,
)
from styrened.tui.widgets.safe_header import Header

logger = logging.getLogger(__name__)


class DeviceConsoleScreen(Screen[None]):
    """SSH-like console for device management over LXMF.

    Sends RPC commands to a remote device via ``self.app.services.bridge``
    (IPCBridge) — never via a directly-held RPCClient instance, which would
    require a live RNS/LXMF layer in the TUI process.

    Imperial CRT theme: #39ff14 green phosphor on #0a0a0a black.

    Attributes:
        device_hash: Target device destination hash.
        command_history: Last 100 command/response dicts.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+l", "clear_history", "Clear"),
    ]

    CSS = """
    DeviceConsoleScreen {
        background: #0a0a0a;
    }

    DeviceConsoleScreen Static {
        color: #39ff14;
        background: #0a0a0a;
    }

    DeviceConsoleScreen Input {
        background: #0a0a0a;
        color: #39ff14;
        border: solid #39ff14;
    }

    DeviceConsoleScreen Input:focus {
        border: double #39ff14;
    }

    DeviceConsoleScreen #header-bar {
        background: #0a0a0a;
        color: #39ff14;
        height: 3;
        border: solid #39ff14;
        content-align: center middle;
    }

    DeviceConsoleScreen #command-input {
        dock: bottom;
        height: 3;
        border: solid #39ff14;
    }

    DeviceConsoleScreen #history-log {
        height: 1fr;
        scrollbar-gutter: stable;
        border: solid #39ff14;
        background: #0a0a0a;
        color: #39ff14;
    }

    DeviceConsoleScreen .command-prompt {
        color: #39ff14;
    }
    """

    def __init__(self, device_hash: str) -> None:
        """Initialize device console screen.

        Args:
            device_hash: Target device destination hash.  RPC calls are
                routed through ``self.app.services.bridge`` at runtime.
        """
        super().__init__()
        self.device_hash = device_hash
        self.command_history: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        """Compose device console UI."""
        yield Header()

        with Container(id="header-bar"):
            yield Static(f"Device Console: {self.device_hash[:16]}...", id="device-info")

        # RichLog renders each write() as a new line — no full-string rebuild.
        yield RichLog(id="history-log", highlight=False, markup=True, wrap=True)

        with Horizontal(id="command-input"):
            yield Static("$ ", classes="command-prompt")
            yield Input(
                placeholder="Enter command (status, exec, reboot, update-config)",
                id="cmd-input",
            )

        yield Footer()

    def on_mount(self) -> None:
        """Focus command input on mount."""
        try:
            self.query_one("#cmd-input", Input).focus()
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input submission."""
        if event.input.id != "cmd-input":
            return

        command_string = event.value.strip()
        if not command_string:
            return

        event.input.value = ""
        await self._execute_command(command_string)

    async def _execute_command(self, command_string: str) -> None:
        """Parse and execute RPC command via IPCBridge.

        Supported commands:
        - status: Display device status
        - exec <cmd> [args...]: Execute shell command
        - reboot [delay]: Reboot device (optional delay in seconds)
        - update-config <key> <value>: Update configuration

        Args:
            command_string: Full command string from input.
        """
        parts = command_string.split()
        if not parts:
            return

        command = parts[0].lower()

        try:
            if command == "status":
                await self._handle_status_command()
            elif command == "exec":
                await self._handle_exec_command(parts[1:])
            elif command == "reboot":
                await self._handle_reboot_command(parts[1:])
            elif command == "update-config":
                await self._handle_update_config_command(parts[1:])
            else:
                self._add_to_history(
                    command_string,
                    "Unknown command. Available: status, exec, reboot, update-config",
                )
        except Exception as e:
            logger.error("Unhandled error in _execute_command for %r: %s", command_string, e)
            self._add_to_history(command_string, f"Error: {e!s}")

    async def _handle_status_command(self) -> None:
        """Handle status command via IPCBridge."""
        try:
            bridge = self.app.services.bridge  # type: ignore[attr-defined]
            result = await bridge.query_device_status(self.device_hash, timeout=30.0)
            # Convert RemoteStatusInfo → StatusResponse for shared formatter.
            status = StatusResponse(
                ip=result.ip,
                uptime=int(result.uptime),
                services=list(result.services),
                disk_used=result.disk_used,
                disk_total=result.disk_total,
            )
            response = self._format_status_response(status)
            self._add_to_history("status", response)
        except RPCTimeoutError as e:
            logger.warning("Status command timed out for %s: %s", self.device_hash, e)
            self._add_to_history("status", str(e))
        except Exception as e:
            logger.error("Status command failed for %s: %s", self.device_hash, e)
            self._add_to_history("status", f"Error: {e}")

    async def _handle_exec_command(self, args: list[str]) -> None:
        """Handle exec command via IPCBridge.

        Args:
            args: Command and arguments to execute.
        """
        if not args:
            self._add_to_history("exec", "Error: exec requires a command")
            return

        command = args[0]
        command_args = args[1:]

        try:
            bridge = self.app.services.bridge  # type: ignore[attr-defined]
            result = await bridge.send_rpc(
                self.device_hash,
                command=command,
                args=command_args,
                timeout=30.0,
            )
            exec_result = ExecResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            response = self._format_exec_result(exec_result)
            self._add_to_history(f"exec {command} {' '.join(command_args)}", response)
        except RPCTimeoutError as e:
            logger.warning("Exec command timed out for %s: %s", self.device_hash, e)
            self._add_to_history(f"exec {command}", str(e))
        except Exception as e:
            logger.error("Exec command failed for %s %r: %s", self.device_hash, command, e)
            self._add_to_history(f"exec {command}", f"Error: {e}")

    async def _handle_reboot_command(self, args: list[str]) -> None:
        """Handle reboot command via IPCBridge.

        Args:
            args: Optional delay in seconds.
        """
        delay = 0
        if args:
            try:
                delay = int(args[0])
            except ValueError:
                self._add_to_history(
                    "reboot",
                    f"Error: invalid delay '{args[0]}', expected integer",
                )
                return

        try:
            bridge = self.app.services.bridge  # type: ignore[attr-defined]
            result = await bridge.reboot_device(self.device_hash, delay=delay, timeout=30.0)
            reboot_result = RebootResult(
                success=result.success,
                message=result.message,
                scheduled_time=None,
            )
            response = self._format_reboot_result(reboot_result)
            command_str = f"reboot {delay}" if delay > 0 else "reboot"
            self._add_to_history(command_str, response)
        except RPCTimeoutError as e:
            logger.warning("Reboot command timed out for %s: %s", self.device_hash, e)
            self._add_to_history("reboot", str(e))
        except Exception as e:
            logger.error("Reboot command failed for %s: %s", self.device_hash, e)
            self._add_to_history("reboot", f"Error: {e}")

    async def _handle_update_config_command(self, args: list[str]) -> None:
        """Handle update-config command.

        Currently stubbed: ``update_config`` has no dedicated IPC bridge
        method yet.  The route through RPCClient is unavailable in the TUI
        process (C4); a follow-up task should add
        ``IPCBridge.update_remote_config()``.

        Args:
            args: Key and value to update.
        """
        if len(args) < 2:
            self._add_to_history("update-config", "Error: update-config requires <key> <value>")
            return

        key = args[0]
        value = " ".join(args[1:])

        logger.info("update-config called for %s key=%r (stub — no IPC bridge method yet)", self.device_hash, key)
        # Stub: return a success-shaped UpdateConfigResult so the formatter
        # works while the full IPC bridge method is added in a follow-up.
        result = UpdateConfigResult(
            success=False,
            message="update-config is not yet supported via IPC bridge",
            updated_keys=[],
        )
        response = self._format_update_config_result(result)
        self._add_to_history(f"update-config {key} {value}", response)

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _format_status_response(self, status: StatusResponse) -> str:
        """Format status response for display."""
        uptime_str = str(timedelta(seconds=status.uptime))
        disk_percent = (
            int((status.disk_used / status.disk_total) * 100)
            if status.disk_total > 0
            else 0
        )
        lines = [
            f"IP Address: {status.ip}",
            f"Uptime: {uptime_str} ({status.uptime}s)",
            f"Services: {', '.join(status.services)}",
            f"Disk Usage: {disk_percent}% ({status.disk_used}/{status.disk_total} bytes)",
        ]
        return "\n".join(lines)

    def _format_exec_result(self, result: ExecResult) -> str:
        """Format exec result for display."""
        lines: list[str] = [f"Exit Code: {result.exit_code}"]
        if result.stdout:
            lines.append(f"Output:\n{result.stdout}")
        if result.stderr:
            lines.append(f"Error Output:\n{result.stderr}")
        lines.append("[Success]" if result.exit_code == 0 else "[Failed]")
        return "\n".join(lines)

    def _format_reboot_result(self, result: RebootResult) -> str:
        """Format reboot result for display."""
        if result.success:
            if result.scheduled_time:
                return f"Success: {result.message} at {result.scheduled_time}"
            return f"Success: {result.message}"
        return f"Failed: {result.message}"

    def _format_update_config_result(self, result: UpdateConfigResult) -> str:
        """Format update-config result for display."""
        if result.success:
            keys_str = ", ".join(result.updated_keys)
            return f"Success: {result.message}\nUpdated keys: {keys_str}"
        return f"Failed: {result.message}"

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _add_to_history(self, command: str, response: str) -> None:
        """Append a command/response pair to history.

        Uses ``RichLog.write()`` for incremental display instead of
        rebuilding the full history string on every entry (W2 fix).
        Maintains at most 100 entries in ``self.command_history``.

        Args:
            command: Command string executed.
            response: Response text to display.
        """
        self.command_history.append({"command": command, "response": response})
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-100:]

        try:
            log = self.query_one("#history-log", RichLog)
            log.write(f"[bold]$ {command}[/bold]")
            log.write(response)
            log.write("")
        except Exception as e:
            logger.error("Failed to write to history log: %s", e)

    def _update_history_display(self) -> None:
        """Rebuild history display from scratch (used by clear_history).

        For incremental appends, use ``_add_to_history()`` instead.
        """
        try:
            log = self.query_one("#history-log", RichLog)
            log.clear()
            for entry in self.command_history:
                log.write(f"[bold]$ {entry['command']}[/bold]")
                log.write(entry["response"])
                log.write("")
        except Exception as e:
            logger.error("Failed to rebuild history display: %s", e)

    def action_clear_history(self) -> None:
        """Clear command history (bound to ctrl+l)."""
        self.command_history = []
        self._update_history_display()
