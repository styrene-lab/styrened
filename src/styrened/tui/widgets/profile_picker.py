"""Profile picker widget."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import RadioButton, RadioSet, Static

from styrened.tui.models.profiles import Profile


class ProfilePicker(Container):
    """Widget for selecting a provisioning profile.

    Displays available profiles as radio buttons with descriptions.
    """

    DEFAULT_CSS = """
    ProfilePicker {
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    ProfilePicker .title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    ProfilePicker RadioSet {
        height: auto;
    }

    ProfilePicker RadioButton {
        margin: 0 1;
    }

    ProfilePicker .description {
        color: $text-muted;
        margin-left: 4;
        margin-bottom: 1;
    }
    """

    class Changed(Message):
        """Posted when profile selection changes."""

        def __init__(self, profile: "Profile | None") -> None:
            super().__init__()
            self.profile = profile

    def __init__(
        self,
        profiles: list[Profile],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize profile picker.

        Args:
            profiles: List of available profiles.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.profiles = profiles
        self._selected_profile: Profile | None = None

    def compose(self) -> ComposeResult:
        """Compose the profile picker UI."""
        yield Static("SELECT PROFILE", classes="title")

        with RadioSet(id="profile-radio-set") as radio_set:
            radio_set.can_focus = True
            for profile in self.profiles:
                yield RadioButton(
                    profile.label,
                    id=f"profile-{profile.id}",
                )
                yield Static(profile.description, classes="description")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle radio button selection change."""
        if event.pressed and event.pressed.id:
            profile_id = event.pressed.id.replace("profile-", "")
            self._selected_profile = next(
                (p for p in self.profiles if p.id == profile_id), None
            )
        else:
            self._selected_profile = None
        self.post_message(self.Changed(self._selected_profile))

    @property
    def selected_profile(self) -> "Profile | None":
        """Get currently selected profile."""
        return self._selected_profile
