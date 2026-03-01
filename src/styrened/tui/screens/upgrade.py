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

# Use a specific match pattern for pkill to avoid killing unrelated processes.
# The anchored regex matches the actual daemon invocation, not grep/editor buffers.
_DAEMON_PKILL_PATTERN = r"^.*/styrened daemon"


def _kill_daemon() -> None:
    """Kill the running styrened daemon process.

    Uses a specific pattern to avoid killing unrelated processes.
    """
    try:
        subprocess.run(
            ["pkill", "-f", _DAEMON_PKILL_PATTERN],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


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
        background: $surface;
        border: none;
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
        self._upgrading = False

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
        # Don't dismiss if upgrade is in progress
        if not self._upgrading:
            self.dismiss(False)

    @staticmethod
    def _build_upgrade_cmd() -> list[str]:
        """Determine the right upgrade command (pipx vs pip).

        For pipx, uses --pip-args with eager upgrade strategy so that
        transitive dependencies (styrened) are always pulled to latest,
        not just when the version constraint forces it.
        """
        exe = sys.executable
        # Check PIPX_BIN_DIR (set by pipx itself inside managed venvs),
        # then fall back to path heuristic using PIPX_HOME or default.
        pipx_bin_dir = os.environ.get("PIPX_BIN_DIR", "")
        pipx_venvs = os.path.join(
            os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/pipx")),
            "venvs",
        )
        if pipx_bin_dir or pipx_venvs in exe:
            return [
                "pipx", "upgrade", "styrene",
                "--pip-args", "--upgrade-strategy=eager",
            ]
        return [exe, "-m", "pip", "install", "--upgrade", "--upgrade-strategy=eager", "styrene"]

    def _start_upgrade(self) -> None:
        """Disable buttons, show log, kick off background worker."""
        self._upgrading = True
        self.query_one("#btn-upgrade", Button).disabled = True
        self.query_one("#btn-cancel", Button).disabled = True
        log_widget = self.query_one("#upgrade-log", Log)
        log_widget.styles.display = "block"
        log_widget.write_line("Starting upgrade...")
        self._do_upgrade()

    def _safe_log(self, message: str) -> None:
        """Write to the log widget if the screen is still mounted."""
        try:
            if not self.is_mounted:
                return
            log = self.query_one("#upgrade-log", Log)
            log.write_line(message)
        except Exception:
            pass

    @work(thread=True, exclusive=True)
    def _do_upgrade(self) -> None:
        """Run the upgrade subprocess in a background thread."""
        cmd = self._build_upgrade_cmd()

        self.app.call_from_thread(self._safe_log, f"$ {' '.join(cmd)}\n")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = result.stdout + result.stderr
            for line in output.splitlines():
                self.app.call_from_thread(self._safe_log, line)

            if result.returncode == 0:
                self.app.call_from_thread(self._safe_log, "\n✅ Upgrade complete!")
                self.app.call_from_thread(self._safe_log, "Restarting daemon...")
                _kill_daemon()
                self.app.call_from_thread(self._finish_success)
            else:
                self.app.call_from_thread(
                    self._safe_log,
                    f"\n❌ Upgrade failed (exit code {result.returncode})",
                )
                self.app.call_from_thread(self._finish_failure)

        except subprocess.TimeoutExpired:
            self.app.call_from_thread(self._safe_log, "\n❌ Upgrade timed out")
            self.app.call_from_thread(self._finish_failure)
        except Exception as e:
            self.app.call_from_thread(self._safe_log, f"\n❌ Error: {e}")
            self.app.call_from_thread(self._finish_failure)

    def _finish_success(self) -> None:
        """Replace action buttons with a restart prompt (guarded)."""
        self._upgrading = False
        if not self.is_mounted:
            return
        try:
            actions = self.query_one("#upgrade-actions", Horizontal)
            actions.remove_children()
            actions.mount(Button("Restart TUI", id="btn-restart", variant="success"))
        except Exception:
            pass

    def _finish_failure(self) -> None:
        """Replace action buttons with a close button (guarded)."""
        self._upgrading = False
        if not self.is_mounted:
            return
        try:
            actions = self.query_one("#upgrade-actions", Horizontal)
            actions.remove_children()
            actions.mount(Button("Close", id="btn-close", variant="default"))
        except Exception:
            pass
