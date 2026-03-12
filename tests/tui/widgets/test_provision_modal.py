"""Widget tests for ProvisionModal rendering states."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Label, ProgressBar, Static

from styrened.tui.screens.provision_modal import ProvisionModal


# ---------------------------------------------------------------------------
# Test harness app
# ---------------------------------------------------------------------------

class ProvisionTestApp(App):
    """Minimal app for mounting ProvisionModal."""

    def compose(self) -> ComposeResult:
        yield Static("base")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_modal(adapter: str = "yggdrasil") -> ProvisionModal:
    return ProvisionModal(
        adapter_name=adapter,
        platform_key="linux-amd64",
        version="0.5.13",
        install_dir=Path("/tmp/test-provision"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisionModalCompose:
    """Test that the modal composes with the expected widgets."""

    @pytest.mark.asyncio
    async def test_has_title(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            # Prevent auto-download by patching the worker
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            title = modal.query_one("#provision-title", Static)
            assert "Yggdrasil" in str(title.render())

    @pytest.mark.asyncio
    async def test_has_platform_info(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            info = modal.query_one("#provision-info", Static)
            text = str(info.render())
            assert "linux-amd64" in text
            assert "0.5.13" in text

    @pytest.mark.asyncio
    async def test_has_progress_bar(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            progress = modal.query_one("#provision-progress", ProgressBar)
            assert progress is not None

    @pytest.mark.asyncio
    async def test_status_shows_downloading(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            status = modal.query_one("#provision-status", Label)
            assert "Downloading" in str(status.render())

    @pytest.mark.asyncio
    async def test_close_button_hidden_initially(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            close_btn = modal.query_one("#provision-close", Button)
            assert close_btn.styles.display == "none"

    @pytest.mark.asyncio
    async def test_fallback_hidden_initially(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            fallback = modal.query_one("#provision-fallback", Static)
            assert fallback.styles.display == "none"


class TestProvisionModalFallbackContent:
    """Test fallback instructions per adapter."""

    @pytest.mark.asyncio
    async def test_yggdrasil_fallback(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal("yggdrasil")
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            fallback = modal.query_one("#provision-fallback", Static)
            text = str(fallback.render())
            assert "nixpkgs#yggdrasil" in text
            assert "brew install yggdrasil" in text

    @pytest.mark.asyncio
    async def test_i2pd_fallback(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal("i2pd")
            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal)
                await pilot.pause()

            fallback = modal.query_one("#provision-fallback", Static)
            text = str(fallback.render())
            assert "nixpkgs#i2pd" in text
            assert "brew install i2pd" in text


class TestProvisionModalDismiss:
    """Test dismiss behavior via close button."""

    @pytest.mark.asyncio
    async def test_close_button_dismisses_with_none(self):
        async with ProvisionTestApp().run_test() as pilot:
            modal = _make_modal()
            results = []

            with patch.object(modal, "run_worker"):
                pilot.app.push_screen(modal, callback=lambda r: results.append(r))
                await pilot.pause()

            # Simulate showing close button (as if error occurred)
            close_btn = modal.query_one("#provision-close", Button)
            close_btn.styles.display = "block"
            await pilot.pause()

            await pilot.click("#provision-close")
            await pilot.pause()

            assert results == [None]
