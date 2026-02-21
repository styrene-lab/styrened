"""Command execution widget for running commands on devices via RPC."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Input, Static

from styrened.rpc import ExecResult, RPCTimeoutError


class CommandWidget(Static):
    """Widget for executing commands on device via RPC.

    Attributes:
        device_identity: Reticulum identity hash of target device.
        result: Last command execution result (or None).
        executing: Whether command is currently executing.
    """

    result: reactive[ExecResult | None] = reactive(None)
    executing: reactive[bool] = reactive(False)

    def __init__(self, device_identity: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Initialize command widget.

        Args:
            device_identity: Device identity hash.
            **kwargs: Additional widget arguments.
        """
        super().__init__(**kwargs)
        self.device_identity = device_identity

    def compose(self) -> ComposeResult:
        """Compose widget content."""
        # Command input row
        with Horizontal(classes="command-input-row"):
            yield Input(placeholder="Enter command...", id="cmd-input")
            yield Button("Execute", id="cmd-execute", variant="primary")

        # Executing state
        if self.executing:
            yield Static("[dim]Executing...[/]", classes="command-executing")

        # Result display
        if self.result and not self.executing:
            with Container(classes="command-result"):
                # Exit code
                if self.result.success:
                    yield Static(
                        f"[bold green]Exit Code:[/] {self.result.exit_code}",
                        classes="exit-code-success",
                    )
                else:
                    yield Static(
                        f"[bold red]Exit Code:[/] {self.result.exit_code}",
                        classes="exit-code-error",
                    )

                # Output
                if self.result.stdout:
                    with Container(classes="command-output"):
                        yield Static("[bold]Output:[/]", classes="output-label")
                        yield Static(self.result.stdout, classes="stdout")

                if self.result.stderr:
                    with Container(classes="command-error"):
                        yield Static("[bold]Error:[/]", classes="error-label")
                        yield Static(self.result.stderr, classes="stderr")

    def watch_result(self, result: ExecResult | None) -> None:
        """React to result changes.

        Args:
            result: New result value.
        """
        # Only recompose if widget is already mounted
        if self.is_mounted:
            self._recompose()

    def watch_executing(self, executing: bool) -> None:
        """React to executing state changes.

        Args:
            executing: New executing state.
        """
        # Only recompose if widget is already mounted
        if self.is_mounted:
            self._recompose()

    def _recompose(self) -> None:
        """Re-compose widget with current state."""
        # Get current input value before removing children
        current_value = ""
        try:
            cmd_input = self.query_one("#cmd-input", Input)
            current_value = cmd_input.value
        except Exception:
            pass

        # Remove all children except input row
        for child in list(self.children):
            if not any(child.query("#cmd-input")):
                child.remove()

        # Re-compose dynamic content
        new_children = []
        for child in self.compose():
            # Skip the input row since it's already mounted
            if not any(child.query("#cmd-input")):
                new_children.append(child)

        if new_children:
            self.mount(*new_children)

        # Restore input value
        try:
            cmd_input = self.query_one("#cmd-input", Input)
            cmd_input.value = current_value
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button pressed event.
        """
        if str(event.button.id) == "cmd-execute":
            await self._execute_command()

    async def _execute_command(self) -> None:
        """Execute command from input field."""
        try:
            cmd_input = self.query_one("#cmd-input", Input)
            command_string = cmd_input.value.strip()
        except Exception:
            return

        if not command_string:
            return

        await self._execute_command_string(command_string)

    async def _execute_command_string(self, command_string: str) -> None:
        """Execute command string via RPC.

        Args:
            command_string: Full command string (e.g., "systemctl status reticulum").
        """
        if not command_string.strip():
            return

        # Parse command and args
        parts = command_string.split()
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        # Set executing state
        self.executing = True
        self.result = None

        try:
            # Execute via RPC client
            # Note: self.app is StyreneApp which has rpc_client attribute
            result = await self.app.rpc_client.call_exec(  # type: ignore[attr-defined]
                self.device_identity,
                command,
                args,
                timeout=60.0,
            )

            self.result = result

        except RPCTimeoutError:
            self.notify(
                "Command timed out - device may be slow or offline",
                title="Timeout",
                severity="warning",
            )
            self.result = ExecResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
            )

        except Exception as e:
            self.notify(
                f"Error executing command: {e}",
                title="Error",
                severity="error",
            )
            self.result = ExecResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )

        finally:
            self.executing = False
