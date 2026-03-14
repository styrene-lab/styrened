"""Tests for PageBrowserWidget transport selector and browser delegation.

Tests the T keybinding (transport cycling), O keybinding (browser delegation),
headless detection, content-type dispatch, and transport availability resolution.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from unittest import mock

import pytest

from styrened.tui.widgets.page_browser import (
    Transport,
    PageBrowserWidget,
    _is_headless,
    _TRANSPORT_LABELS,
    _CONTENT_INDICATORS,
)
from styrened.tui.widgets.html_renderer import ContentKind


# ---------------------------------------------------------------------------
# Minimal MeshDevice stub for transport selector tests
# ---------------------------------------------------------------------------

@dataclass
class _FakeDevice:
    """Minimal stub matching MeshDevice endpoint fields."""
    nomadnet_destination_hash: str = ""
    b32_address: str = ""
    web_url: str = ""
    identity_hash: str = "abc123"
    destination_hash: str = "def456"


# ---------------------------------------------------------------------------
# Transport availability
# ---------------------------------------------------------------------------

class TestGetAvailableTransports:
    """_get_available_transports returns transports from MeshDevice fields."""

    def test_no_device(self):
        w = PageBrowserWidget()
        assert w._get_available_transports() == []

    def test_nomadnet_only(self):
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(nomadnet_destination_hash="abc123")
        assert w._get_available_transports() == [Transport.NOMADNET]

    def test_i2p_only(self):
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(b32_address="something.b32.i2p")
        assert w._get_available_transports() == [Transport.I2P]

    def test_https_only(self):
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(web_url="https://node.example.com")
        assert w._get_available_transports() == [Transport.HTTPS]

    def test_all_three(self):
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(
            nomadnet_destination_hash="abc",
            b32_address="xyz.b32.i2p",
            web_url="https://example.com",
        )
        transports = w._get_available_transports()
        assert transports == [Transport.NOMADNET, Transport.I2P, Transport.HTTPS]

    def test_nomadnet_and_i2p(self):
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(
            nomadnet_destination_hash="abc",
            b32_address="xyz.b32.i2p",
        )
        transports = w._get_available_transports()
        assert transports == [Transport.NOMADNET, Transport.I2P]

    def test_empty_fields_not_counted(self):
        """Empty strings should not count as available transports."""
        w = PageBrowserWidget()
        w._mesh_device = _FakeDevice(
            nomadnet_destination_hash="",
            b32_address="",
            web_url="",
        )
        assert w._get_available_transports() == []


# ---------------------------------------------------------------------------
# set_mesh_device
# ---------------------------------------------------------------------------

class TestSetMeshDevice:
    """set_mesh_device sets device and initializes active transport."""

    def test_sets_device(self):
        w = PageBrowserWidget()
        dev = _FakeDevice(nomadnet_destination_hash="abc")
        w.set_mesh_device(dev)
        assert w._mesh_device is dev

    def test_sets_first_transport(self):
        w = PageBrowserWidget()
        dev = _FakeDevice(nomadnet_destination_hash="abc", b32_address="xyz.b32.i2p")
        w.set_mesh_device(dev)
        assert w._active_transport == Transport.NOMADNET

    def test_preserves_active_transport_if_valid(self):
        w = PageBrowserWidget()
        w._active_transport = Transport.I2P
        dev = _FakeDevice(nomadnet_destination_hash="abc", b32_address="xyz.b32.i2p")
        w.set_mesh_device(dev)
        # I2P is still available on this device, so it should stay
        assert w._active_transport == Transport.I2P

    def test_resets_transport_if_not_available(self):
        w = PageBrowserWidget()
        w._active_transport = Transport.HTTPS
        dev = _FakeDevice(nomadnet_destination_hash="abc")
        w.set_mesh_device(dev)
        # HTTPS not available on this device — should reset to first
        assert w._active_transport == Transport.NOMADNET


# ---------------------------------------------------------------------------
# Headless detection
# ---------------------------------------------------------------------------

class TestIsHeadless:
    """_is_headless detects environments without browser capability."""

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("os.uname")
    def test_no_env_no_ssh_not_headless(self, mock_uname):
        """No SSH, no display — not headless (local terminal)."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is False

    @mock.patch.dict(os.environ, {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, clear=True)
    @mock.patch("os.uname")
    def test_ssh_no_display_headless(self, mock_uname):
        """SSH without display — headless."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is True

    @mock.patch.dict(
        os.environ,
        {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22", "DISPLAY": ":0"},
        clear=True,
    )
    @mock.patch("os.uname")
    def test_ssh_with_display_not_headless(self, mock_uname):
        """SSH with X11 forwarding — not headless."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is False

    @mock.patch.dict(
        os.environ,
        {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22", "WAYLAND_DISPLAY": "wayland-0"},
        clear=True,
    )
    @mock.patch("os.uname")
    def test_ssh_with_wayland_not_headless(self, mock_uname):
        """SSH with Wayland forwarding — not headless."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is False

    @mock.patch.dict(
        os.environ,
        {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22", "BROWSER": "firefox"},
        clear=True,
    )
    @mock.patch("os.uname")
    def test_ssh_with_browser_env_not_headless(self, mock_uname):
        """SSH with BROWSER env set — not headless."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is False

    @mock.patch.dict(os.environ, {"SSH_CLIENT": "1.2.3.4 1234 22"}, clear=True)
    @mock.patch("os.uname")
    def test_ssh_client_also_detects_headless(self, mock_uname):
        """SSH_CLIENT (alternative to SSH_CONNECTION) also triggers headless."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        assert _is_headless() is True

    @mock.patch.dict(os.environ, {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, clear=True)
    @mock.patch("os.uname")
    def test_macos_never_headless(self, mock_uname):
        """macOS always has `open` available, even over SSH."""
        mock_uname.return_value = mock.Mock(sysname="Darwin")
        assert _is_headless() is False


# ---------------------------------------------------------------------------
# Display location with indicators
# ---------------------------------------------------------------------------

class TestDisplayLocation:
    """URL bar includes transport and content-type indicators."""

    def test_external_url_shows_indicator(self):
        w = PageBrowserWidget(external_url="http://test.b32.i2p/")
        w._last_content_kind = ContentKind.HTML
        loc = w._display_location()
        assert "🌐 HTML" in loc
        assert "http://test.b32.i2p/" in loc

    def test_nomadnet_path_shows_micron(self):
        w = PageBrowserWidget(destination_hash="a" * 32)
        w._last_content_kind = ContentKind.MICRON
        loc = w._display_location()
        assert "📄 micron" in loc

    def test_transport_label_shown_when_multiple(self):
        w = PageBrowserWidget(destination_hash="a" * 32)
        w._mesh_device = _FakeDevice(
            nomadnet_destination_hash="abc",
            b32_address="xyz.b32.i2p",
        )
        w._active_transport = Transport.NOMADNET
        w._last_content_kind = ContentKind.MICRON
        loc = w._display_location()
        assert "T: NomadNet" in loc

    def test_transport_label_hidden_when_single(self):
        w = PageBrowserWidget(destination_hash="a" * 32)
        w._mesh_device = _FakeDevice(nomadnet_destination_hash="abc")
        w._active_transport = Transport.NOMADNET
        w._last_content_kind = ContentKind.MICRON
        loc = w._display_location()
        # Single transport — no T: label
        assert "T:" not in loc


# ---------------------------------------------------------------------------
# Transport labels and content indicators
# ---------------------------------------------------------------------------

class TestLabelsAndIndicators:
    """Verify all enum values have corresponding labels."""

    def test_all_transports_have_labels(self):
        for t in Transport:
            assert t in _TRANSPORT_LABELS

    def test_all_content_kinds_have_indicators(self):
        for k in ContentKind:
            assert k in _CONTENT_INDICATORS

    def test_transport_label_values(self):
        assert _TRANSPORT_LABELS[Transport.NOMADNET] == "NomadNet"
        assert _TRANSPORT_LABELS[Transport.I2P] == "I2P"
        assert _TRANSPORT_LABELS[Transport.HTTPS] == "HTTPS"
