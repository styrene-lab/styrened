"""Color picker modal for the TUI theme editor.

Opens as a modal screen when a color swatch is clicked. Provides:
- HSL hue bar with arrow-key navigation
- Saturation/lightness 2D grid
- Hex input with live preview
- Preset palette with clickable swatches
- OK/Cancel buttons

Returns the selected hex color string or None on cancel.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from textual import on
from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

# CRT-appropriate palette presets
PRESET_COLORS: list[str] = [
    "#0a0e14",  # deep black
    "#1a1e24",  # dark surface
    "#2a3040",  # slate
    "#3a4a5a",  # steel
    "#5a7a7a",  # muted teal
    "#4a9a8a",  # teal
    "#3adaba",  # bright teal
    "#7affcc",  # mint
    "#c8f0e0",  # pale mint
    "#ffffff",  # white
    "#e8b060",  # amber
    "#e07838",  # orange
    "#d04040",  # red
    "#c060a0",  # pink
    "#8060c0",  # purple
    "#6080e0",  # blue
]


class HueBar(Widget):
    """Horizontal hue bar — click or arrow keys to select hue."""

    DEFAULT_CSS = """
    HueBar {
        height: 2;
        width: 1fr;
        margin: 0 1;
    }
    """

    can_focus = True

    hue: reactive[float] = reactive(0.0)  # 0.0-360.0

    @dataclass
    class Changed(Message):
        hue: float

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip.blank(width)

        segments: list[Segment] = []
        cursor_x = int(self.hue / 360.0 * (width - 1))

        for x in range(width):
            h = x / max(width - 1, 1)
            r, g, b = colorsys.hls_to_rgb(h, 0.5, 1.0)
            color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            if x == cursor_x and y == 0:
                segments.append(Segment("▼", Style(color=color, bold=True)))
            elif x == cursor_x and y == 1:
                segments.append(Segment("█", Style(color="white", bgcolor=color)))
            else:
                segments.append(Segment("█", Style(color=color)))

        return Strip(segments)

    def on_click(self, event: Click) -> None:
        if self.size.width > 0:
            self.hue = event.x / max(self.size.width - 1, 1) * 360.0
            self.post_message(self.Changed(self.hue))

    def action_hue_left(self) -> None:
        self.hue = max(0.0, self.hue - 5.0)
        self.post_message(self.Changed(self.hue))

    def action_hue_right(self) -> None:
        self.hue = min(360.0, self.hue + 5.0)
        self.post_message(self.Changed(self.hue))

    BINDINGS = [
        ("left", "hue_left", "Hue left"),
        ("right", "hue_right", "Hue right"),
    ]

    def watch_hue(self) -> None:
        self.refresh()


class SatLightGrid(Widget):
    """2D saturation (x) × lightness (y) grid. Click or arrow keys."""

    DEFAULT_CSS = """
    SatLightGrid {
        height: 12;
        width: 1fr;
        margin: 0 1;
    }
    """

    can_focus = True

    hue: reactive[float] = reactive(0.0)
    saturation: reactive[float] = reactive(1.0)  # 0.0-1.0
    lightness: reactive[float] = reactive(0.5)  # 0.0-1.0

    @dataclass
    class Changed(Message):
        saturation: float
        lightness: float

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        height = self.size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        # y=0 is top (light=1.0), y=height-1 is bottom (light=0.0)
        light = 1.0 - (y / max(height - 1, 1))

        cursor_x = int(self.saturation * (width - 1))
        cursor_y = int((1.0 - self.lightness) * (height - 1))

        segments: list[Segment] = []
        h = self.hue / 360.0

        for x in range(width):
            sat = x / max(width - 1, 1)
            r, g, b = colorsys.hls_to_rgb(h, light, sat)
            color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

            is_cursor = (x == cursor_x and y == cursor_y)
            if is_cursor:
                # Crosshair — contrasting color
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                fg = "#000000" if lum > 0.5 else "#ffffff"
                segments.append(Segment("◉", Style(color=fg, bgcolor=color)))
            else:
                segments.append(Segment("▓", Style(color=color)))

        return Strip(segments)

    def on_click(self, event: Click) -> None:
        w = max(self.size.width - 1, 1)
        h = max(self.size.height - 1, 1)
        self.saturation = max(0.0, min(1.0, event.x / w))
        self.lightness = max(0.0, min(1.0, 1.0 - event.y / h))
        self.post_message(self.Changed(self.saturation, self.lightness))

    def action_sat_left(self) -> None:
        self.saturation = max(0.0, self.saturation - 0.05)
        self.post_message(self.Changed(self.saturation, self.lightness))

    def action_sat_right(self) -> None:
        self.saturation = min(1.0, self.saturation + 0.05)
        self.post_message(self.Changed(self.saturation, self.lightness))

    def action_light_up(self) -> None:
        self.lightness = min(1.0, self.lightness + 0.05)
        self.post_message(self.Changed(self.saturation, self.lightness))

    def action_light_down(self) -> None:
        self.lightness = max(0.0, self.lightness - 0.05)
        self.post_message(self.Changed(self.saturation, self.lightness))

    BINDINGS = [
        ("left", "sat_left", "Less saturated"),
        ("right", "sat_right", "More saturated"),
        ("up", "light_up", "Lighter"),
        ("down", "light_down", "Darker"),
    ]

    def watch_hue(self) -> None:
        self.refresh()

    def watch_saturation(self) -> None:
        self.refresh()

    def watch_lightness(self) -> None:
        self.refresh()


class PresetPalette(Widget):
    """Row of clickable preset color swatches."""

    DEFAULT_CSS = """
    PresetPalette {
        height: 2;
        width: 1fr;
        margin: 0 1;
        layout: horizontal;
    }

    PresetPalette .preset-swatch {
        width: 4;
        height: 2;
        content-align: center middle;
    }
    """

    @dataclass
    class Selected(Message):
        color: str

    def compose(self) -> ComposeResult:
        for i, color in enumerate(PRESET_COLORS):
            yield Static(
                f"[on {color}]    [/]\n[on {color}]    [/]",
                classes="preset-swatch",
                id=f"preset-{i}",
            )

    def on_click(self, event: Click) -> None:
        # Find which preset was clicked
        try:
            widget = self.screen.get_widget_at(event.screen_x, event.screen_y)[0]
            if hasattr(widget, "id") and widget.id and widget.id.startswith("preset-"):
                idx = int(widget.id.split("-")[1])
                if 0 <= idx < len(PRESET_COLORS):
                    self.post_message(self.Selected(PRESET_COLORS[idx]))
        except Exception:
            pass


class ColorPickerDialog(ModalScreen[str | None]):
    """Modal color picker dialog.

    Args:
        token_name: The color token being edited (for display).
        initial_color: Starting hex color (e.g. '#4a9a8a').

    Returns the selected hex color string on OK, or None on cancel.
    """

    CSS = """
    ColorPickerDialog {
        align: center middle;
    }

    #color-picker-container {
        width: 64;
        height: auto;
        max-height: 90%;
        background: $background;
        border: round $primary;
        padding: 1 2;
    }

    #color-picker-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #color-picker-preview-row {
        height: 3;
        margin: 1 1;
        align: center middle;
    }

    #color-picker-old-preview {
        width: 12;
        height: 3;
        content-align: center middle;
    }

    #color-picker-arrow {
        width: 5;
        height: 3;
        content-align: center middle;
    }

    #color-picker-new-preview {
        width: 12;
        height: 3;
        content-align: center middle;
    }

    #color-picker-hex-row {
        height: 3;
        margin: 0 1;
        align: center middle;
    }

    #color-picker-hex-label {
        width: auto;
        margin-right: 1;
    }

    #color-picker-hex-input {
        width: 20;
    }

    #color-picker-hue-label, #color-picker-sl-label {
        margin: 1 1 0 1;
        color: $text-muted;
    }

    #color-picker-preset-label {
        margin: 1 1 0 1;
        color: $text-muted;
    }

    #color-picker-actions {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #color-picker-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    current_color: reactive[str] = reactive("#000000")

    def __init__(
        self,
        token_name: str,
        initial_color: str = "#000000",
    ) -> None:
        super().__init__()
        self._token_name = token_name
        self._initial_color = initial_color or "#000000"
        self.current_color = self._initial_color

    def compose(self) -> ComposeResult:
        with Vertical(id="color-picker-container"):
            yield Static(
                f"Pick color for [bold]{self._token_name}[/bold]",
                id="color-picker-title",
            )

            # Old → New preview
            with Horizontal(id="color-picker-preview-row"):
                yield Static(
                    self._render_preview(self._initial_color),
                    id="color-picker-old-preview",
                )
                yield Static("  →  ", id="color-picker-arrow")
                yield Static(
                    self._render_preview(self._initial_color),
                    id="color-picker-new-preview",
                )

            # Hex input
            with Horizontal(id="color-picker-hex-row"):
                yield Label("Hex:", id="color-picker-hex-label")
                yield Input(
                    value=self._initial_color,
                    placeholder="#rrggbb",
                    id="color-picker-hex-input",
                    max_length=7,
                )

            # Hue bar
            yield Static("Hue", id="color-picker-hue-label")
            yield HueBar(id="color-picker-hue")

            # Sat/Light grid
            yield Static("Saturation / Lightness", id="color-picker-sl-label")
            yield SatLightGrid(id="color-picker-sl")

            # Presets
            yield Static("Presets", id="color-picker-preset-label")
            yield PresetPalette(id="color-picker-presets")

            # Actions
            with Horizontal(id="color-picker-actions"):
                yield Button("OK", variant="primary", id="color-picker-ok")
                yield Button("Cancel", variant="default", id="color-picker-cancel")

    def on_mount(self) -> None:
        self._sync_hsl_from_hex(self._initial_color)

    @staticmethod
    def _render_preview(hex_color: str) -> str:
        return f"[on {hex_color}]            [/]\n[on {hex_color}]   {hex_color}  [/]\n[on {hex_color}]            [/]"

    def _sync_hsl_from_hex(self, hex_color: str) -> None:
        """Update hue bar and SL grid from a hex color."""
        try:
            c = Color.parse(hex_color)
            hsl = c.hsl
            hue_bar = self.query_one("#color-picker-hue", HueBar)
            sl_grid = self.query_one("#color-picker-sl", SatLightGrid)
            hue_bar.hue = hsl.h * 360.0
            sl_grid.hue = hsl.h * 360.0
            sl_grid.saturation = hsl.s
            sl_grid.lightness = hsl.l
        except Exception:
            pass

    def _hex_from_hsl(self) -> str:
        """Compute hex from current hue bar + SL grid state."""
        hue_bar = self.query_one("#color-picker-hue", HueBar)
        sl_grid = self.query_one("#color-picker-sl", SatLightGrid)
        h = hue_bar.hue / 360.0
        r, g, b = colorsys.hls_to_rgb(h, sl_grid.lightness, sl_grid.saturation)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    def _update_from_hsl(self) -> None:
        """Recompute hex from HSL widgets and update preview + input."""
        hex_color = self._hex_from_hsl()
        self.current_color = hex_color
        try:
            inp = self.query_one("#color-picker-hex-input", Input)
            inp.value = hex_color
        except Exception:
            pass
        self._update_preview(hex_color)

    def _update_preview(self, hex_color: str) -> None:
        try:
            preview = self.query_one("#color-picker-new-preview", Static)
            preview.update(self._render_preview(hex_color))
        except Exception:
            pass

    @on(HueBar.Changed)
    def _on_hue_changed(self, event: HueBar.Changed) -> None:
        sl_grid = self.query_one("#color-picker-sl", SatLightGrid)
        sl_grid.hue = event.hue
        self._update_from_hsl()

    @on(SatLightGrid.Changed)
    def _on_sl_changed(self, event: SatLightGrid.Changed) -> None:
        self._update_from_hsl()

    @on(PresetPalette.Selected)
    def _on_preset_selected(self, event: PresetPalette.Selected) -> None:
        self.current_color = event.color
        self._sync_hsl_from_hex(event.color)
        try:
            inp = self.query_one("#color-picker-hex-input", Input)
            inp.value = event.color
        except Exception:
            pass
        self._update_preview(event.color)

    @on(Input.Changed, "#color-picker-hex-input")
    def _on_hex_input_changed(self, event: Input.Changed) -> None:
        val = event.value.strip()
        if val and val.startswith("#") and len(val) == 7:
            try:
                Color.parse(val)
                self.current_color = val
                self._sync_hsl_from_hex(val)
                self._update_preview(val)
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "color-picker-ok":
            self.dismiss(self.current_color)
        elif event.button.id == "color-picker-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
