"""Device Console Screen - SSH-like interface for device management over LXMF."""

import logging
from datetime import timedelta
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from styrened.rpc import RPCClient
from styrened.rpc.errors import RPCTimeoutError
from styrened.rpc.messages import (
    ExecResult,
    RebootResult,
    StatusResponse,
    UpdateConfigResult,
)

logger = logging.getLogger(__name__)


class DeviceConsoleScreen(Screen[None]):
    """SSH-like console for device management over LXMF.

    Allows sending RPC commands to remote devices and displaying responses.
    Uses Imperial CRT theme (#39ff14 green phosphor on #0a0a0a black).

    Attributes:
        device_hash: Target device identity hash.
        rpc_client: RPCClient instance for sending commands.
        command_history: List of command/response dicts (last 100 entries).
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

    DeviceConsoleScreen #history-container {
        height: 1fr;
        scrollbar-gutter: stable;
        border: solid #39ff14;
    }

    DeviceConsoleScreen .history-entry {
        padding: 1;
        border-bottom: solid #39ff14;
    }

    DeviceConsoleScreen .command-prompt {
        color: #39ff14;
    }

    DeviceConsoleScreen .response-text {
        color: #39ff14;
        padding-left: 2;
    }

    DeviceConsoleScreen .error-text {
        color: red;
        padding-left: 2;
    }
    """

    def __init__(
        self,
        device_hash: str,
        rpc_client: RPCClient,
    ) -> None:
        """Initialize device console screen.

        Args:
            device_hash: Target device identity hash.
            rpc_client: RPC client for sending commands.
        """
        super().__init__()
        self.device_hash = device_hash
        self.rpc_client = rpc_client
        self.command_history: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        """Compose device console UI."""
        yield Header()

        # Device info header
        with Container(id="header-bar"):
            yield Static(f"Device Console: {self.device_hash[:16]}...", id="device-info")

        # Command history display
        with ScrollableContainer(id="history-container"):
            yield Static("", id="history-display")

        # Command input at bottom
        with Horizontal(id="command-input"):
            yield Static("$ ", classes="command-prompt")
            yield Input(placeholder="Enter command (status, exec, reboot, update-config)", id="cmd-input")

        yield Footer()

    def on_mount(self) -> None:
        """Focus command input on mount."""
        try:
            cmd_input = self.query_one("#cmd-input", Input)
            cmd_input.focus()
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input submission.

        Args:
            event: Input submitted event.
        """
        if event.input.id != "cmd-input":
            return

        command_string = event.value.strip()
        if not command_string:
            return

        # Clear input
        event.input.value = ""

        # Execute command
        await self._execute_command(command_string)

    async def _execute_command(self, command_string: str) -> None:
        """Parse and execute RPC command.

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
                self._add_to_history(command_string, "Unknown command. Available: status, exec, reboot, update-config")
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            self._add_to_history(command_string, f"Error: {e!s}")

    async def _handle_status_command(self) -> None:
        """Handle status command."""
        try:
            status = await self.rpc_client.call_status(self.device_hash, timeout=30.0)
            response = self._format_status_response(status)
            self._add_to_history("status", response)
        except RPCTimeoutError as e:
            self._add_to_history("status", str(e))
        except Exception as e:
            self._add_to_history("status", f"Error: {e}")

    async def _handle_exec_command(self, args: list[str]) -> None:
        """Handle exec command.

        Args:
            args: Command and arguments to execute.
        """
        if not args:
            self._add_to_history("exec", "Error: exec requires a command")
            return

        command = args[0]
        command_args = args[1:]

        try:
            result = await self.rpc_client.call_exec(
                self.device_hash,
                command=command,
                args=command_args,
                timeout=30.0,
            )
            response = self._format_exec_result(result)
            self._add_to_history(f"exec {command} {' '.join(command_args)}", response)
        except RPCTimeoutError as e:
            self._add_to_history(f"exec {command}", str(e))
        except Exception as e:
            self._add_to_history(f"exec {command}", f"Error: {e}")

    async def _handle_reboot_command(self, args: list[str]) -> None:
        """Handle reboot command.

        Args:
            args: Optional delay in seconds.
        """
        delay = 0
        if args:
            try:
                delay = int(args[0])
            except ValueError:
                self._add_to_history("reboot", f"Error: invalid delay '{args[0]}', expected integer")
                return

        try:
            result = await self.rpc_client.call_reboot(
                self.device_hash,
                delay=delay,
                timeout=30.0,
            )
            response = self._format_reboot_result(result)
            command_str = f"reboot {delay}" if delay > 0 else "reboot"
            self._add_to_history(command_str, response)
        except RPCTimeoutError as e:
            self._add_to_history("reboot", str(e))
        except Exception as e:
            self._add_to_history("reboot", f"Error: {e}")

    async def _handle_update_config_command(self, args: list[str]) -> None:
        """Handle update-config command.

        Args:
            args: Key and value to update.
        """
        if len(args) < 2:
            self._add_to_history("update-config", "Error: update-config requires <key> <value>")
            return

        key = args[0]
        value = " ".join(args[1:])  # Join remaining args as value

        try:
            result = await self.rpc_client.call_update_config(
                self.device_hash,
                config_updates={key: value},
                timeout=30.0,
            )
            response = self._format_update_config_result(result)
            self._add_to_history(f"update-config {key} {value}", response)
        except RPCTimeoutError as e:
            self._add_to_history("update-config", str(e))
        except Exception as e:
            self._add_to_history("update-config", f"Error: {e}")

    def _format_status_response(self, status: StatusResponse) -> str:
        """Format status response for display.

        Args:
            status: Status response from device.

        Returns:
            Formatted status string.
        """
        uptime_str = str(timedelta(seconds=status.uptime))
        disk_percent = int((status.disk_used / status.disk_total) * 100) if status.disk_total > 0 else 0

        lines = [
            f"IP Address: {status.ip}",
            f"Uptime: {uptime_str} ({status.uptime}s)",
            f"Services: {', '.join(status.services)}",
            f"Disk Usage: {disk_percent}% ({status.disk_used}/{status.disk_total} bytes)",
        ]
        return "\n".join(lines)

    def _format_exec_result(self, result: ExecResult) -> str:
        """Format exec result for display.

        Args:
            result: Exec result from device.

        Returns:
            Formatted result string.
        """
        lines = [f"Exit Code: {result.exit_code}"]

        if result.stdout:
            lines.append(f"Output:\n{result.stdout}")

        if result.stderr:
            lines.append(f"Error Output:\n{result.stderr}")

        if result.exit_code != 0:
            lines.append("[Failed]")
        else:
            lines.append("[Success]")

        return "\n".join(lines)

    def _format_reboot_result(self, result: RebootResult) -> str:
        """Format reboot result for display.

        Args:
            result: Reboot result from device.

        Returns:
            Formatted result string.
        """
        if result.success:
            if result.scheduled_time:
                return f"Success: {result.message} at {result.scheduled_time}"
            return f"Success: {result.message}"
        return f"Failed: {result.message}"

    def _format_update_config_result(self, result: UpdateConfigResult) -> str:
        """Format update-config result for display.

        Args:
            result: Update config result from device.

        Returns:
            Formatted result string.
        """
        if result.success:
            keys_str = ", ".join(result.updated_keys)
            return f"Success: {result.message}\nUpdated keys: {keys_str}"
        return f"Failed: {result.message}"

    def _add_to_history(self, command: str, response: str) -> None:
        """Add command and response to history.

        Maintains last 100 entries.

        Args:
            command: Command string executed.
            response: Response text to display.
        """
        self.command_history.append({
            "command": command,
            "response": response,
        })

        # Limit to last 100 entries
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-100:]

        # Update display
        self._update_history_display()

    def _update_history_display(self) -> None:
        """Update history display widget with current history."""
        try:
            history_display = self.query_one("#history-display", Static)

            # Build history text
            lines = []
            for entry in self.command_history:
                lines.append(f"$ {entry['command']}")
                lines.append(entry['response'])
                lines.append("")  # Blank line between entries

            history_display.update("\n".join(lines))

            # Scroll to bottom
            try:
                container = self.query_one("#history-container", ScrollableContainer)
                container.scroll_end(animate=False)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Failed to update history display: {e}")

    def action_clear_history(self) -> None:
        """Clear command history (bound to ctrl+l)."""
        self.command_history = []
        self._update_history_display()
