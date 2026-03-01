"""Upgrade confirmation and execution screen."""

from __future__ import annotations

import os
import subprocess
import sys

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Log, Static

from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade


class UpgradeScreen(ModalScreen[bool]):
    """Modal screen for upgrading styrene to the latest version.

    Shows current/latest version info, runs upgrade in background,
    streams output to a log widget.  Returns True if the user wants
    to restart the TUI after a successful upgrade.
    """

    CSS = """
    UpgradeScreen {
        align: center middle;
    }

    #upgrade-container {
        width: 72;
        height: auto;
        max-height: 80%;
    }

    #upgrade-content {
        padding: 1 2;
    }

    #upgrade-info {
        margin: 0 0 1 0;
    }

    #upgrade-log {
        height: 12;
        margin: 1 0;
        display: none;
    }

    #upgrade-actions {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #upgrade-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current: str, latest: str) -> None:
        super().__init__()
        self._current = current
        self._latest = latest

    def compose(self) -> ComposeResult:
        cascade = get_color_cascade()

        with HighlightedPanel(title="UPGRADE AVAILABLE", id="upgrade-container"):
            with Vertical(id="upgrade-content"):
                yield Static(
                    f"[{cascade.medium}]Current:[/] v{self._current}  →  "
                    f"[{cascade.bright} bold]v{self._latest}[/]",
                    id="upgrade-info",
                )
                yield Log(id="upgrade-log")
                with Horizontal(id="upgrade-actions"):
                    yield Button(
                        "Upgrade Now",
                        id="btn-upgrade",
                        variant="success",
                    )
                    yield Button(
                        "Later",
                        id="btn-cancel",
                        variant="default",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-upgrade":
            self._start_upgrade()
        elif event.button.id == "btn-cancel":
            self.dismiss(False)
        elif event.button.id == "btn-restart":
            self.dismiss(True)
        elif event.button.id == "btn-close":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @staticmethod
    def _build_upgrade_cmd() -> list[str]:
        """Determine the right upgrade command (pipx vs pip)."""
        exe = sys.executable
        pipx_venvs = os.path.join(
            os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/pipx")),
            "venvs",
        )
        if pipx_venvs in exe:
            return ["pipx", "upgrade", "styrene"]
        return [exe, "-m", "pip", "install", "--upgrade", "styrene"]

    def _start_upgrade(self) -> None:
        """Disable buttons, show log, kick off background worker."""
        self.query_one("#btn-upgrade", Button).disabled = True
        self.query_one("#btn-cancel", Button).disabled = True
        log_widget = self.query_one("#upgrade-log", Log)
        log_widget.styles.display = "block"
        log_widget.write_line("Starting upgrade...")
        self._do_upgrade()

    @work(thread=True, exclusive=True)
    def _do_upgrade(self) -> None:
        """Run the upgrade subprocess in a background thread."""
        cmd = self._build_upgrade_cmd()
        log = self.query_one("#upgrade-log", Log)

        self.call_from_thread(log.write_line, f"$ {' '.join(cmd)}\n")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = result.stdout + result.stderr
            for line in output.splitlines():
                self.call_from_thread(log.write_line, line)

            if result.returncode == 0:
                self.call_from_thread(log.write_line, "\n✅ Upgrade complete!")
                self.call_from_thread(log.write_line, "Restarting daemon...")
                subprocess.run(["pkill", "-f", "styrened daemon"], capture_output=True)
                self.call_from_thread(self._swap_to_restart)
            else:
                self.call_from_thread(
                    log.write_line,
                    f"\n❌ Upgrade failed (exit code {result.returncode})",
                )
                self.call_from_thread(self._swap_to_close)

        except subprocess.TimeoutExpired:
            self.call_from_thread(log.write_line, "\n❌ Upgrade timed out")
            self.call_from_thread(self._swap_to_close)
        except Exception as e:
            self.call_from_thread(log.write_line, f"\n❌ Error: {e}")
            self.call_from_thread(self._swap_to_close)

    def _swap_to_restart(self) -> None:
        """Replace action buttons with a restart prompt."""
        actions = self.query_one("#upgrade-actions", Horizontal)
        actions.remove_children()
        actions.mount(Button("Restart TUI", id="btn-restart", variant="success"))

    def _swap_to_close(self) -> None:
        """Replace action buttons with a close button."""
        actions = self.query_one("#upgrade-actions", Horizontal)
        actions.remove_children()
        actions.mount(Button("Close", id="btn-close", variant="default"))
