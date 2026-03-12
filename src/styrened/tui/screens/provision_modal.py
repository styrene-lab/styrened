"""Provisioning modal — shows download progress for adapter binary acquisition."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar, Static

log = logging.getLogger(__name__)


class ProvisionModal(ModalScreen[Path | None]):
    """Modal overlay for downloading and installing an adapter binary.

    On success, dismisses with the installed binary path.
    On failure, shows error details and fallback install instructions.
    """

    CSS = """
    ProvisionModal {
        align: center middle;
    }
    #provision-dialog {
        width: 60;
        max-height: 24;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #provision-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }
    #provision-info {
        margin-bottom: 1;
    }
    #provision-progress {
        margin: 1 0;
    }
    #provision-status {
        margin: 1 0;
    }
    #provision-fallback {
        display: none;
        margin: 1 0;
        color: $text-muted;
    }
    #provision-close {
        display: none;
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(
        self,
        adapter_name: str,
        platform_key: str,
        version: str,
        install_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.adapter_name = adapter_name
        self.platform_key = platform_key
        self.version = version
        self.install_dir = install_dir or Path.home() / ".styrene" / "bin"
        self._total_bytes = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="provision-dialog"):
            yield Static(
                f"Enable {self.adapter_name.title()}",
                id="provision-title",
            )
            yield Static(
                f"Platform: {self.platform_key}\n"
                f"Version:  {self.version}\n"
                f"Install:  {self.install_dir / self.adapter_name}",
                id="provision-info",
            )
            yield ProgressBar(total=100, id="provision-progress")
            yield Label("Downloading...", id="provision-status")
            yield Static(
                self._fallback_instructions(),
                id="provision-fallback",
            )
            yield Button("Close", id="provision-close", variant="default")

    def on_mount(self) -> None:
        """Start the download task."""
        self.run_worker(self._do_provision(), name="provision")

    async def _do_provision(self) -> None:
        """Run the provisioning pipeline."""
        from styrened.services.binary_provisioner import BinaryProvisioner

        provisioner = BinaryProvisioner(install_dir=self.install_dir)
        status = self.query_one("#provision-status", Label)
        progress = self.query_one("#provision-progress", ProgressBar)

        def on_progress(downloaded: int, total: int) -> None:
            self._total_bytes = total
            if total > 0:
                pct = min(100, int(downloaded * 100 / total))
                self.call_from_thread(progress.update, progress=pct)
                mb = downloaded / 1_048_576
                total_mb = total / 1_048_576
                self.call_from_thread(
                    status.update,
                    f"Downloading... {mb:.1f}/{total_mb:.1f} MB",
                )

        try:
            self.call_from_thread(status.update, "Downloading...")
            result = await provisioner.provision(
                self.adapter_name, on_progress=on_progress
            )

            # Success
            self.call_from_thread(progress.update, progress=100)
            self.call_from_thread(
                status.update,
                f"✓ {self.adapter_name} installed to {result}",
            )

            await asyncio.sleep(2.0)
            self.dismiss(result)

        except Exception as e:
            log.error("Provisioning failed for %s: %s", self.adapter_name, e)
            self.call_from_thread(
                status.update, f"✗ Error: {e}"
            )
            fallback = self.query_one("#provision-fallback")
            self.call_from_thread(fallback.styles.__setattr__, "display", "block")
            close_btn = self.query_one("#provision-close", Button)
            self.call_from_thread(close_btn.styles.__setattr__, "display", "block")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provision-close":
            self.dismiss(None)

    def _fallback_instructions(self) -> str:
        if self.adapter_name == "yggdrasil":
            return (
                "Manual install:\n"
                "  Nix:    nix profile install nixpkgs#yggdrasil\n"
                "  Debian: sudo apt install yggdrasil\n"
                "  macOS:  brew install yggdrasil"
            )
        elif self.adapter_name == "i2pd":
            return (
                "Manual install:\n"
                "  Nix:    nix profile install nixpkgs#i2pd\n"
                "  Debian: sudo apt install i2pd\n"
                "  macOS:  brew install i2pd"
            )
        return f"Install {self.adapter_name} manually via your package manager."
