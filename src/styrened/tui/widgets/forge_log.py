"""ForgeLog widget — consumes MediaEvent stream from the forge pipeline."""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Static

from styrened.tui.forge.models import STAGE_NAMES, STAGE_ORDER, MediaEvent, StageKey
from styrened.tui.lifecycle import WidgetResourceScope
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class ForgeLog(Widget):
    """Displays forge pipeline progress via MediaEvent stream.

    Three sections:
    - Stage bar: horizontal row of stage labels with cascade coloring
    - Log area: scrollable log output
    - Status line: completion or error state
    """

    DEFAULT_CSS = """
    ForgeLog {
        height: 1fr;
    }

    #forge-stage-bar {
        height: 1;
        padding: 0 1;
    }

    #forge-log-scroll {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
        scrollbar-background: transparent;
        scrollbar-color: $border;
    }

    #forge-log-output {
        height: auto;
    }

    #forge-status-line {
        height: 1;
        padding: 0 1;
    }

    #forge-abort-row {
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }

    #forge-mesh-watch {
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }

    #forge-mesh-watch.hidden {
        display: none;
    }
    """

    class Aborted(Message):
        """Posted when the user clicks the abort button."""

    class FlashComplete(Message):
        """Posted when the forge pipeline completes successfully."""

        def __init__(self, hostname: str) -> None:
            super().__init__()
            self.hostname = hostname

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._current_stage: StageKey | None = None
        self._completed_stages: set[StageKey] = set()
        self._log_lines: list[str] = []
        self._is_complete = False
        self._is_error = False
        self._hostname: str = ""
        self._mesh_watch_start: float | None = None
        self._mesh_watch_timer: Timer | None = None
        self._resources = WidgetResourceScope(self)

    def compose(self) -> ComposeResult:
        yield Horizontal(id="forge-stage-bar")
        with VerticalScroll(id="forge-log-scroll"):
            yield Static("", id="forge-log-output")
        yield Static("", id="forge-status-line")
        with Horizontal(id="forge-abort-row"):
            yield Button("Abort", id="btn-forge-abort", variant="error")
        with Vertical(id="forge-mesh-watch", classes="hidden"):
            yield Static("", id="forge-mesh-status")

    def on_mount(self) -> None:
        self._render_stage_bar()

    @property
    def is_complete(self) -> bool:
        return self._is_complete

    @property
    def is_error(self) -> bool:
        return self._is_error

    def set_hostname(self, hostname: str) -> None:
        """Set the hostname for post-flash mesh watch."""
        self._hostname = hostname

    def handle_event(self, event: MediaEvent) -> None:
        """Process a single MediaEvent from the forge pipeline."""
        if event.kind == "stage" and event.stage is not None:
            if self._current_stage is not None:
                self._completed_stages.add(self._current_stage)
            self._current_stage = event.stage
            self._render_stage_bar()
            self._append_log(event.message)

        elif event.kind == "log":
            self._append_log(event.message)

        elif event.kind == "error":
            self._is_error = True
            cascade = get_color_cascade()
            self._append_log(f"[{cascade.bright}]ERROR:[/] {event.message}")
            self._set_status(f"[{cascade.bright}]Error: {event.message}[/]")
            self._show_close_button()

        elif event.kind == "complete":
            if self._current_stage is not None:
                self._completed_stages.add(self._current_stage)
                self._current_stage = None
            self._is_complete = True
            self._render_stage_bar()
            cascade = get_color_cascade()
            self._append_log(f"[{cascade.bright}]{event.message}[/]")
            self._set_status(f"[{cascade.bright}]Complete[/]")
            self._show_close_button()
            self.post_message(self.FlashComplete(self._hostname))

    def start_mesh_watch(self) -> None:
        """Transition to mesh-watch state after successful flash."""
        self._mesh_watch_start = time.monotonic()
        self._stop_mesh_watch_timer()
        try:
            watch_panel = self.query_one("#forge-mesh-watch", Vertical)
            watch_panel.remove_class("hidden")
            self._update_mesh_watch_display()
            self._mesh_watch_timer = self._resources.set_interval(
                "_mesh_watch_timer",
                1.0,
                self._update_mesh_watch_display,
            )
        except Exception:
            pass

    def _update_mesh_watch_display(self) -> None:
        """Update the mesh watch elapsed timer."""
        if self._mesh_watch_start is None:
            return
        elapsed = int(time.monotonic() - self._mesh_watch_start)
        cascade = get_color_cascade()
        try:
            self.query_one("#forge-mesh-status", Static).update(
                f"[{cascade.medium}]Watching for {self._hostname} on mesh...[/] "
                f"[{cascade.dim}]({elapsed}s)[/]"
            )
        except Exception:
            pass

    def mesh_node_found(self, hostname: str) -> None:
        """Called when the provisioned node is detected on mesh."""
        cascade = get_color_cascade()
        try:
            self.query_one("#forge-mesh-status", Static).update(
                f"[{cascade.bright}]Node {hostname} joined the mesh[/]"
            )
        except Exception:
            pass
        self._mesh_watch_start = None
        self._stop_mesh_watch_timer()

    def on_unmount(self) -> None:
        """Stop mesh-watch timer when the widget is removed."""
        self._resources.release()

    def reset(self) -> None:
        """Reset the widget for a new forge run."""
        self._current_stage = None
        self._completed_stages.clear()
        self._log_lines.clear()
        self._is_complete = False
        self._is_error = False
        self._mesh_watch_start = None
        self._stop_mesh_watch_timer()
        self._render_stage_bar()
        try:
            self.query_one("#forge-log-output", Static).update("")
            self.query_one("#forge-status-line", Static).update("")
            self.query_one("#forge-mesh-watch", Vertical).add_class("hidden")
            abort_btn = self.query_one("#btn-forge-abort", Button)
            abort_btn.label = "Abort"
            abort_btn.disabled = False
        except Exception:
            pass

    def _stop_mesh_watch_timer(self) -> None:
        """Stop the mesh-watch timer if one is active."""
        self._resources.stop_timer("_mesh_watch_timer")

    def _render_stage_bar(self) -> None:
        """Render the horizontal stage indicator bar."""
        cascade = get_color_cascade()
        parts: list[str] = []

        for i, stage_key in enumerate(STAGE_ORDER):
            label = STAGE_NAMES[i]
            if stage_key in self._completed_stages:
                parts.append(f"[{cascade.bright}]{label}[/]")
            elif stage_key == self._current_stage:
                parts.append(f"[{cascade.bright} bold]{label}[/]")
            else:
                parts.append(f"[{cascade.dim}]{label}[/]")

        try:
            self.query_one("#forge-stage-bar", Horizontal).remove_children()
            self.query_one("#forge-stage-bar", Horizontal).mount(Static(" > ".join(parts)))
        except Exception:
            pass

    def _append_log(self, message: str) -> None:
        """Append a line to the log area and auto-scroll."""
        self._log_lines.append(message)
        try:
            output = self.query_one("#forge-log-output", Static)
            output.update("\n".join(self._log_lines))
            scroll = self.query_one("#forge-log-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        """Set the status line text."""
        try:
            self.query_one("#forge-status-line", Static).update(text)
        except Exception:
            pass

    def _show_close_button(self) -> None:
        """Transform abort button into close/done button."""
        try:
            btn = self.query_one("#btn-forge-abort", Button)
            btn.label = "Done"
            btn.variant = "default"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-forge-abort":
            if self._is_complete or self._is_error:
                # Done state — let parent handle return to selection
                self.post_message(self.Aborted())
            else:
                # Active forge — abort
                self.post_message(self.Aborted())
