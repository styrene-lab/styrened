"""Hardware picker widget."""

from collections import defaultdict

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import RadioButton, RadioSet, Static

from styrened.tui.models.device_hardware import Hardware


class HardwarePicker(Container):
    """Widget for selecting hardware specification.

    Groups hardware by activity level and displays as radio buttons.
    """

    DEFAULT_CSS = """
    HardwarePicker {
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    HardwarePicker .title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    HardwarePicker .activity-label {
        color: $warning;
        text-style: bold;
        margin-top: 1;
    }

    HardwarePicker RadioSet {
        height: auto;
        margin-left: 2;
    }

    HardwarePicker RadioButton {
        margin: 0 1;
    }

    HardwarePicker .specs {
        color: $text-muted;
        margin-left: 4;
    }
    """

    class Changed(Message):
        """Posted when hardware selection changes."""

        def __init__(self, hardware: "Hardware | None") -> None:
            super().__init__()
            self.hardware = hardware

    def __init__(
        self,
        hardware_list: list[Hardware],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize hardware picker.

        Args:
            hardware_list: List of available hardware.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.hardware_list = hardware_list
        self._selected_hardware: Hardware | None = None

    def compose(self) -> ComposeResult:
        """Compose the hardware picker UI."""
        yield Static("SELECT HARDWARE", classes="title")

        # Group hardware by activity level
        grouped: dict[str, list[Hardware]] = defaultdict(list)
        for hw in self.hardware_list:
            grouped[hw.activity].append(hw)

        # Display groups in order: low, medium, high; then any extras
        activity_order = ["low", "medium", "high"]
        extra_activities = [a for a in grouped if a not in activity_order]

        for activity in activity_order + extra_activities:
            if activity not in grouped:
                continue

            yield Static(f"Activity: {activity.upper()}", classes="activity-label")

            with RadioSet(id=f"hardware-radio-set-{activity}") as radio_set:
                radio_set.can_focus = True
                for hw in grouped[activity]:
                    yield RadioButton(
                        hw.label,
                        id=f"hardware-{hw.id}",
                    )
                    traits_str = ", ".join(hw.traits) if hw.traits else "none"
                    specs = f"Arch: {hw.arch} | Boot: {hw.boot} | Traits: {traits_str}"
                    yield Static(specs, classes="specs")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle radio button selection change."""
        if event.pressed and event.pressed.id:
            hardware_id = event.pressed.id.replace("hardware-", "")
            self._selected_hardware = next(
                (h for h in self.hardware_list if h.id == hardware_id), None
            )
        else:
            self._selected_hardware = None
        self.post_message(self.Changed(self._selected_hardware))

    @property
    def selected_hardware(self) -> "Hardware | None":
        """Get currently selected hardware."""
        return self._selected_hardware
