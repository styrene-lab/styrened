"""Animated status indicators for device and connection states.

Provides widgets that animate while in transitional states (scanning, pending)
and display static indicators for stable states (online, offline).
"""

from typing import ClassVar

from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from styrened.tui.themes.semantic import SemanticSymbols


class AnimatedStatusIndicator(Static):
    """Status indicator that animates during transitional states.

    Static states (online, offline) display fixed symbols.
    Transitional states (scanning, pending) animate through frames.

    Example:
        indicator = AnimatedStatusIndicator()
        indicator.status = "scanning"  # Starts animation
        indicator.status = "online"    # Stops animation, shows ● ONLINE
    """

    # Animation frames for different states
    SCAN_FRAMES: ClassVar[list[str]] = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
    PENDING_FRAMES: ClassVar[list[str]] = ["◴", "◷", "◶", "◵"]

    STATIC_SYMBOLS: ClassVar[dict[str, str]] = {
        "online": SemanticSymbols.ONLINE,
        "offline": SemanticSymbols.OFFLINE,
        "info": SemanticSymbols.INFO,
    }

    status: reactive[str] = reactive("offline")
    _frame_index: reactive[int] = reactive(0)

    def __init__(
        self,
        status: str = "offline",
        label: str | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the animated status indicator.

        Args:
            status: Initial status state (online, offline, pending, scanning, info).
            label: Optional label to display after the symbol. Uses status name if None.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._label = label
        self._timer: Timer | None = None
        self.status = status

    def on_mount(self) -> None:
        """Start animation timer on mount."""
        self._timer = self.set_interval(0.1, self._advance_frame, pause=not self._is_animated())
        self._update_display()

    def _advance_frame(self) -> None:
        """Advance to the next animation frame."""
        frames = self._get_frames()
        if frames:
            self._frame_index = (self._frame_index + 1) % len(frames)

    def _get_frames(self) -> list[str]:
        """Get animation frames for current status."""
        if self.status == "scanning":
            return self.SCAN_FRAMES
        if self.status == "pending":
            return self.PENDING_FRAMES
        return []

    def _is_animated(self) -> bool:
        """Check if current status should animate."""
        return self.status in ("scanning", "pending")

    def watch_status(self, status: str) -> None:  # noqa: ARG002
        """Handle status changes — start/stop animation."""
        if self._timer is None:
            return  # Not mounted yet

        if self._is_animated():
            self._frame_index = 0
            self._timer.resume()
        else:
            self._timer.pause()

        self._update_display()

    def watch__frame_index(self, index: int) -> None:  # noqa: ARG002
        """Update display when animation frame changes."""
        if self._is_animated():
            self._update_display()

    def _update_display(self) -> None:
        """Render the current status display."""
        label = self._label or self.status.upper()

        if self._is_animated():
            frames = self._get_frames()
            symbol = frames[self._frame_index] if frames else "?"
        else:
            symbol = self.STATIC_SYMBOLS.get(self.status, SemanticSymbols.INFO)

        self.update(f"{symbol} {label}")

    def set_status(self, status: str, label: str | None = None) -> None:
        """Update status and optionally the label.

        Args:
            status: New status state.
            label: Optional new label (keeps existing if None).
        """
        if label is not None:
            self._label = label
        self.status = status


class ScanningBar(Static):
    """A bouncing bar indicator for scanning operations.

    Displays a bar that bounces left-to-right while active.

    Example:
        bar = ScanningBar(width=20)
        bar.start()  # Begin animation
        bar.stop()   # Stop and hide
    """

    BAR_CHAR = "█"
    EMPTY_CHAR = "░"

    active: reactive[bool] = reactive(False)
    _position: reactive[int] = reactive(0)
    _direction: int = 1

    def __init__(
        self,
        width: int = 20,
        bar_width: int = 4,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the scanning bar.

        Args:
            width: Total width of the bar area.
            bar_width: Width of the moving bar segment.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._width = width
        self._bar_width = bar_width
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        """Start animation timer on mount."""
        self._timer = self.set_interval(0.05, self._advance, pause=True)
        self._update_display()

    def _advance(self) -> None:
        """Move the bar position."""
        max_pos = self._width - self._bar_width
        self._position += self._direction

        if self._position >= max_pos:
            self._position = max_pos
            self._direction = -1
        elif self._position <= 0:
            self._position = 0
            self._direction = 1

    def watch_active(self, active: bool) -> None:
        """Start/stop animation based on active state."""
        if self._timer is None:
            return

        if active:
            self._position = 0
            self._direction = 1
            self._timer.resume()
        else:
            self._timer.pause()

        self._update_display()

    def watch__position(self, position: int) -> None:  # noqa: ARG002
        """Update display when position changes."""
        if self.active:
            self._update_display()

    def _update_display(self) -> None:
        """Render the scanning bar."""
        if not self.active:
            self.update("")
            return

        before = self.EMPTY_CHAR * self._position
        bar = self.BAR_CHAR * self._bar_width
        after = self.EMPTY_CHAR * (self._width - self._position - self._bar_width)
        self.update(f"[{before}{bar}{after}]")

    def start(self) -> None:
        """Start the scanning animation."""
        self.active = True

    def stop(self) -> None:
        """Stop the scanning animation."""
        self.active = False


class PulsingIndicator(Static):
    """An indicator that pulses in brightness.

    Uses Textual's built-in style animation for smooth opacity transitions.

    Example:
        indicator = PulsingIndicator("⬤ Processing")
        indicator.start()  # Begin pulsing
        indicator.stop()   # Stop at full brightness
    """

    active: reactive[bool] = reactive(False)

    def __init__(
        self,
        content: str = "●",
        pulse_duration: float = 1.0,
        min_opacity: float = 0.3,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the pulsing indicator.

        Args:
            content: Text/symbol to display.
            pulse_duration: Time for one pulse cycle in seconds.
            min_opacity: Minimum opacity during pulse (0.0–1.0).
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(content, name=name, id=id, classes=classes)
        self._pulse_duration = pulse_duration
        self._min_opacity = min_opacity
        self._pulsing = False

    def watch_active(self, active: bool) -> None:
        """Start/stop pulsing based on active state."""
        if active and not self._pulsing:
            self._pulsing = True
            self._pulse_down()
        elif not active:
            self._pulsing = False
            self.styles.animate("opacity", value=1.0, duration=0.2, easing="linear")

    def _pulse_down(self) -> None:
        """Animate opacity down."""
        if not self._pulsing:
            return

        half_duration = self._pulse_duration / 2
        self.styles.animate(
            "opacity",
            value=self._min_opacity,
            duration=half_duration,
            easing="in_out_cubic",
            on_complete=self._pulse_up,
        )

    def _pulse_up(self) -> None:
        """Animate opacity back up."""
        if not self._pulsing:
            return

        half_duration = self._pulse_duration / 2
        self.styles.animate(
            "opacity",
            value=1.0,
            duration=half_duration,
            easing="in_out_cubic",
            on_complete=self._pulse_down,
        )

    def start(self) -> None:
        """Start pulsing."""
        self.active = True

    def stop(self) -> None:
        """Stop pulsing."""
        self.active = False
