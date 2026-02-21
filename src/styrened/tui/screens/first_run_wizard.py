"""First-run wizard for Reticulum setup."""

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static


class FirstRunWizardScreen(Screen[bool]):
    """First-run wizard for Reticulum configuration.

    Guides new users through minimal Reticulum setup:
    1. Welcome and explanation
    2. Interface selection (AutoInterface, TCP, or skip)
    3. Config generation and validation
    4. Proceed to main application

    Returns:
        bool: True if config was created, False if skipped.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Skip Setup"),
    ]

    def __init__(self) -> None:
        """Initialize wizard."""
        super().__init__()
        self.step = 1
        self.interface_choice = "auto"  # Default to AutoInterface

    def compose(self) -> ComposeResult:
        """Compose the wizard layout."""
        yield Static("RETICULUM SETUP WIZARD", classes="wizard-title")

        with Container(id="wizard-content"):
            yield Static("", id="wizard-step-indicator")

            # Step 1: Welcome
            with Vertical(id="step-welcome", classes="wizard-step"):
                yield Static(
                    """
[bold green]Welcome to Styrene TUI[/]

Reticulum is not configured on this system. Reticulum provides
encrypted mesh networking for device discovery and communication.

This wizard will create a minimal configuration to get you started.

You can always reconfigure later by editing ~/.reticulum/config
or running 'rnsd --config'.
                    """.strip(),
                    classes="wizard-text",
                )
                yield Label("")
                yield Button("Continue", variant="primary", id="step1-continue")
                yield Button("Skip Setup (Offline Mode)", id="step1-skip")

            # Step 2: Interface Selection
            with Vertical(id="step-interface", classes="wizard-step hidden"):
                yield Static(
                    """
[bold green]Network Interface Selection[/]

Reticulum needs at least one network interface to communicate.
Choose the interface type that best fits your setup:
                    """.strip(),
                    classes="wizard-text",
                )
                yield Label("")

                with RadioSet(id="interface-selection"):
                    yield RadioButton(
                        "AutoInterface (Recommended)",
                        value=True,
                        id="interface-auto",
                    )
                    yield Static(
                        "  [dim]Automatic local network discovery via UDP multicast.[/]",
                        classes="wizard-help",
                    )
                    yield Static(
                        "  [dim]Works on LANs without router configuration.[/]",
                        classes="wizard-help",
                    )
                    yield Label("")

                    yield RadioButton("TCP Client Interface", id="interface-tcp")
                    yield Static(
                        "  [dim]Connect to a specific Reticulum node by IP:port.[/]",
                        classes="wizard-help",
                    )
                    yield Static(
                        "  [dim]Useful for connecting to a known gateway or hub.[/]",
                        classes="wizard-help",
                    )
                    yield Label("")

                    yield RadioButton(
                        "TCP Server Interface", id="interface-tcp-server"
                    )
                    yield Static(
                        "  [dim]Listen for incoming connections from other nodes.[/]",
                        classes="wizard-help",
                    )
                    yield Static(
                        "  [dim]Acts as a gateway for other devices.[/]",
                        classes="wizard-help",
                    )

                yield Label("")
                yield Button("Continue", variant="primary", id="step2-continue")
                yield Button("Back", id="step2-back")

            # Step 3: Finalization
            with Vertical(id="step-finalize", classes="wizard-step hidden"):
                yield Static("", id="finalize-status", classes="wizard-text")
                yield Label("")
                yield Button(
                    "Create Configuration & Continue",
                    variant="primary",
                    id="step3-create",
                )
                yield Button("Back", id="step3-back")

        # Status message
        yield Static("", id="wizard-status")

    def on_mount(self) -> None:
        """Update step indicator on mount."""
        self._update_step_indicator()

    def _update_step_indicator(self) -> None:
        """Update the step indicator text."""
        indicator = self.query_one("#wizard-step-indicator", Static)
        indicator.update(f"Step {self.step} of 3")

    def _show_step(self, step_num: int) -> None:
        """Show a specific wizard step.

        Args:
            step_num: Step number to show (1-3).
        """
        self.step = step_num
        self._update_step_indicator()

        # Hide all steps
        for step_id in ["step-welcome", "step-interface", "step-finalize"]:
            step = self.query_one(f"#{step_id}")
            step.add_class("hidden")

        # Show requested step
        if step_num == 1:
            self.query_one("#step-welcome").remove_class("hidden")
        elif step_num == 2:
            self.query_one("#step-interface").remove_class("hidden")
        elif step_num == 3:
            self._prepare_finalize_step()
            self.query_one("#step-finalize").remove_class("hidden")

    def _prepare_finalize_step(self) -> None:
        """Prepare the finalization step with selected options."""
        status = self.query_one("#finalize-status", Static)

        interface_name = {
            "auto": "AutoInterface (UDP multicast)",
            "tcp": "TCP Client Interface",
            "tcp-server": "TCP Server Interface",
        }.get(self.interface_choice, "Unknown")

        status.update(
            f"""
[bold green]Ready to Create Configuration[/]

The following configuration will be created:

  • Config location: ~/.reticulum/config
  • Interface type: {interface_name}
  • Transport mode: Disabled (not a routing node)
  • Shared instance: Enabled

This configuration is minimal and can be customized later.
        """.strip()
        )

    # Step 1 Actions
    @on(Button.Pressed, "#step1-continue")
    def on_step1_continue(self) -> None:
        """Continue from welcome to interface selection."""
        self._show_step(2)

    @on(Button.Pressed, "#step1-skip")
    def on_step1_skip(self) -> None:
        """Skip setup and run in offline mode."""
        self.dismiss(False)

    # Step 2 Actions
    @on(Button.Pressed, "#step2-continue")
    def on_step2_continue(self) -> None:
        """Continue from interface selection to finalization."""
        # Get selected interface
        radio_set = self.query_one("#interface-selection", RadioSet)
        if radio_set.pressed_button:
            if radio_set.pressed_button.id == "interface-auto":
                self.interface_choice = "auto"
            elif radio_set.pressed_button.id == "interface-tcp":
                self.interface_choice = "tcp"
            elif radio_set.pressed_button.id == "interface-tcp-server":
                self.interface_choice = "tcp-server"

        self._show_step(3)

    @on(Button.Pressed, "#step2-back")
    def on_step2_back(self) -> None:
        """Go back to welcome."""
        self._show_step(1)

    # Step 3 Actions
    @on(Button.Pressed, "#step3-create")
    def on_step3_create(self) -> None:
        """Create configuration and exit wizard."""
        try:
            from styrened.tui.services.reticulum import create_default_reticulum_config

            config_path = create_default_reticulum_config(
                interface_type=self.interface_choice
            )
            self._show_status(
                f"Configuration created at {config_path}", success=True
            )
            # Schedule dismissal with result=True
            self.set_timer(1.5, lambda: self.dismiss(True))

        except Exception as e:
            self._show_status(f"Failed to create config: {e}", success=False)

    @on(Button.Pressed, "#step3-back")
    def on_step3_back(self) -> None:
        """Go back to interface selection."""
        self._show_step(2)

    def action_cancel(self) -> None:
        """Skip setup via escape key."""
        self.dismiss(False)

    def _show_status(self, message: str, success: bool = True) -> None:
        """Show status message.

        Args:
            message: Status message to display.
            success: Whether this is a success (green) or error (red) message.
        """
        status = self.query_one("#wizard-status", Static)
        if success:
            status.update(f"[green]{message}[/green]")
        else:
            status.update(f"[red]{message}[/red]")
