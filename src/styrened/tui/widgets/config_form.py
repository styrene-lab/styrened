"""Configuration form widget."""

import re

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.validation import ValidationResult, Validator
from textual.widgets import Checkbox, Input, Static


class HostnameValidator(Validator):
    """Validator for hostname format."""

    def validate(self, value: str) -> ValidationResult:
        """Validate hostname against RFC 1123.

        Args:
            value: Hostname to validate.

        Returns:
            ValidationResult indicating validity.
        """
        if not value:
            return self.failure("Hostname is required")

        # RFC 1123 hostname pattern
        pattern = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
        if not re.match(pattern, value):
            return self.failure(
                "Hostname must contain only lowercase letters, numbers, and hyphens"
            )

        return self.success()


class ConfigForm(Container):
    """Widget for device configuration input.

    Collects hostname, WiFi credentials, SSH key, and mesh settings.
    """

    DEFAULT_CSS = """
    ConfigForm {
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    ConfigForm .title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    ConfigForm .field {
        height: auto;
        margin-bottom: 1;
    }

    ConfigForm .field-label {
        color: $text;
        margin-bottom: 0;
    }

    ConfigForm Input {
        width: 100%;
    }

    ConfigForm Checkbox {
        margin-top: 1;
    }
    """

    class Changed(Message):
        """Posted when any configuration value changes."""

        def __init__(self, config: dict[str, str]) -> None:
            super().__init__()
            self.config = config

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize configuration form.

        Args:
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._config: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        """Compose the configuration form UI."""
        yield Static("DEVICE CONFIGURATION", classes="title")

        with Vertical(classes="field"):
            yield Static("Hostname *", classes="field-label")
            yield Input(
                placeholder="styrene-node-01",
                id="input-hostname",
                validators=[HostnameValidator()],
            )

        with Vertical(classes="field"):
            yield Static("WiFi SSID (optional)", classes="field-label")
            yield Input(
                placeholder="MyNetwork",
                id="input-wifi-ssid",
            )

        with Vertical(classes="field"):
            yield Static("WiFi Password (optional)", classes="field-label")
            yield Input(
                placeholder="",
                id="input-wifi-password",
                password=True,
            )

        with Vertical(classes="field"):
            yield Static("SSH Public Key Path (optional)", classes="field-label")
            yield Input(
                placeholder="~/.ssh/id_ed25519.pub",
                id="input-ssh-key",
            )

        yield Checkbox("Enable mesh networking", id="checkbox-mesh", value=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input field changes."""
        self._update_config()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes."""
        self._update_config()

    def _update_config(self) -> None:
        """Update internal config and post message."""
        self._config = {
            "hostname": self.query_one("#input-hostname", Input).value,
            "wifi_ssid": self.query_one("#input-wifi-ssid", Input).value,
            "wifi_password": self.query_one("#input-wifi-password", Input).value,
            "ssh_key_path": self.query_one("#input-ssh-key", Input).value,
            "mesh_enabled": str(self.query_one("#checkbox-mesh", Checkbox).value).lower(),
        }
        self.post_message(self.Changed(self._config))

    def validate(self) -> tuple[bool, list[str]]:
        """Validate all form fields.

        Returns:
            Tuple of (is_valid, error_messages).
        """
        errors: list[str] = []

        # Validate hostname (required)
        hostname_input = self.query_one("#input-hostname", Input)
        if not hostname_input.value:
            errors.append("Hostname is required")
        elif not hostname_input.is_valid:
            errors.append("Hostname format is invalid")

        return (len(errors) == 0, errors)

    @property
    def config(self) -> dict[str, str]:
        """Get current configuration values."""
        return self._config
