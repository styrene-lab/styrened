"""Configuration form widget for device provisioning."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.validation import ValidationResult, Validator
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from styrened.tui.forge.models import DeviceProfile, ForgeConfig


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

    Collects hostname, WiFi credentials, and SSH key path.
    Supports pre-population from ForgeConfig and DeviceProfile defaults.
    """

    DEFAULT_CSS = """
    ConfigForm {
        height: auto;
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
    """

    class Changed(Message):
        """Posted when any configuration value changes."""

        def __init__(self, config: dict[str, str]) -> None:
            super().__init__()
            self.config = config

    def __init__(
        self,
        *,
        forge_config: ForgeConfig | None = None,
        device: DeviceProfile | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize configuration form.

        Args:
            forge_config: Forge defaults for WiFi/SSH pre-population.
            device: Device profile for hostname pre-population.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._forge_config = forge_config
        self._device = device
        self._config: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        # Derive default values
        default_hostname = ""
        default_wifi_ssid = ""
        default_wifi_password = ""
        default_ssh_key = ""

        if self._device:
            default_hostname = self._device.default_hostname
            # Check forge_config for per-device hostname override
            if self._forge_config and self._device.id in self._forge_config.hostnames:
                default_hostname = self._forge_config.hostnames[self._device.id]

        if self._forge_config:
            default_wifi_ssid = self._forge_config.wifi_ssid
            default_wifi_password = self._forge_config.wifi_password
            default_ssh_key = self._forge_config.ssh_key

        yield Static("DEVICE CONFIGURATION", classes="title")

        with Vertical(classes="field"):
            yield Static("Hostname *", classes="field-label")
            yield Input(
                value=default_hostname,
                placeholder="styrene-node-01",
                id="input-hostname",
                validators=[HostnameValidator()],
            )

        with Vertical(classes="field"):
            yield Static("WiFi SSID (optional)", classes="field-label")
            yield Input(
                value=default_wifi_ssid,
                placeholder="MyNetwork",
                id="input-wifi-ssid",
            )

        with Vertical(classes="field"):
            yield Static("WiFi Password (optional)", classes="field-label")
            yield Input(
                value=default_wifi_password,
                placeholder="",
                id="input-wifi-password",
                password=True,
            )

        with Vertical(classes="field"):
            yield Static("SSH Public Key Path (optional)", classes="field-label")
            yield Input(
                value=default_ssh_key,
                placeholder="~/.ssh/id_ed25519.pub",
                id="input-ssh-key",
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input field changes."""
        self._update_config()

    def _update_config(self) -> None:
        """Update internal config and post message."""
        self._config = {
            "hostname": self.query_one("#input-hostname", Input).value,
            "wifi_ssid": self.query_one("#input-wifi-ssid", Input).value,
            "wifi_password": self.query_one("#input-wifi-password", Input).value,
            "ssh_key_path": self.query_one("#input-ssh-key", Input).value,
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
