"""Tests for PageBrowserWidget transport selector and browser delegation.

Tests the T keybinding (transport cycling), O keybinding (browser delegation),
headless detection, content-type dispatch, and transport availability resolution.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from unittest import mock

from styrened.tui.widgets.html_renderer import ContentKind
from styrened.tui.widgets.page_browser import (
    _CONTENT_INDICATORS,
    _TRANSPORT_LABELS,
    PageBrowserWidget,
    Transport,
    _is_headless,
)

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


# ---------------------------------------------------------------------------
# check_action — headless gating
# ---------------------------------------------------------------------------

class TestCheckAction:
    """check_action returns False for open_in_browser when headless."""

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=True)
    def test_headless_hides_open_in_browser(self, _mock):
        w = PageBrowserWidget()
        result = w.check_action("open_in_browser", ())
        assert result is False

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=False)
    def test_non_headless_shows_open_in_browser(self, _mock):
        w = PageBrowserWidget()
        result = w.check_action("open_in_browser", ())
        assert result is True

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=True)
    def test_headless_allows_other_actions(self, _mock):
        # check_action returns None for unknown actions (delegate to base class)
        w = PageBrowserWidget()
        assert w.check_action("reload", ()) is None
        assert w.check_action("go_back", ()) is None
        assert w.check_action("cycle_transport", ()) is None

    @mock.patch.dict(os.environ, {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, clear=True)
    @mock.patch("os.uname")
    def test_macos_ssh_check_action_returns_true(self, mock_uname):
        """macOS is never headless, so check_action returns True."""
        mock_uname.return_value = mock.Mock(sysname="Darwin")
        w = PageBrowserWidget()
        assert w.check_action("open_in_browser", ()) is True

    @mock.patch.dict(os.environ, {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, clear=True)
    @mock.patch("os.uname")
    def test_linux_ssh_no_display_check_action_returns_false(self, mock_uname):
        """Linux over SSH without display returns False."""
        mock_uname.return_value = mock.Mock(sysname="Linux")
        w = PageBrowserWidget()
        assert w.check_action("open_in_browser", ()) is False


# ---------------------------------------------------------------------------
# action_open_in_browser URL rewriting
# ---------------------------------------------------------------------------

class TestOpenInBrowserUrlRewriting:
    """action_open_in_browser rewrites .i2p URLs to localhost proxy."""

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=False)
    def test_i2p_url_rewritten_to_proxy(self, _mock):
        w = PageBrowserWidget(external_url="http://something.b32.i2p/page")
        w._external_url = "http://something.b32.i2p/page"
        opened_urls = []
        fake_app = mock.Mock()
        fake_app.open_url = lambda u: opened_urls.append(u)
        with mock.patch.object(type(w), "app", new_callable=lambda: property(lambda self: fake_app)):
            w.action_open_in_browser()
        assert len(opened_urls) == 1
        assert opened_urls[0] == "http://localhost:4444/http://something.b32.i2p/page"

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=False)
    def test_https_url_passed_through_unchanged(self, _mock):
        w = PageBrowserWidget(external_url="https://styrene.dev/docs")
        w._external_url = "https://styrene.dev/docs"
        opened_urls = []
        fake_app = mock.Mock()
        fake_app.open_url = lambda u: opened_urls.append(u)
        with mock.patch.object(type(w), "app", new_callable=lambda: property(lambda self: fake_app)):
            w.action_open_in_browser()
        assert opened_urls == ["https://styrene.dev/docs"]

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=False)
    def test_nomadnet_path_shows_notification_no_url_opened(self, _mock):
        w = PageBrowserWidget(destination_hash="a" * 32, initial_path="/page/index.mu")
        w._external_url = ""
        w.current_path = "/page/index.mu"
        notifications = []
        fake_app = mock.Mock()
        w.notify = lambda msg, **kw: notifications.append(msg)
        with mock.patch.object(type(w), "app", new_callable=lambda: property(lambda self: fake_app)):
            w.action_open_in_browser()
        assert any("NomadNet" in n for n in notifications)
        fake_app.open_url.assert_not_called()

    @mock.patch("styrened.tui.widgets.page_browser._is_headless", return_value=True)
    def test_headless_shows_warning_no_url_opened(self, _mock):
        w = PageBrowserWidget(external_url="https://example.com")
        w._external_url = "https://example.com"
        notifications = []
        w.notify = lambda msg, **kw: notifications.append(msg)
        fake_app = mock.Mock()
        with mock.patch.object(type(w), "app", new_callable=lambda: property(lambda self: fake_app)):
            w.action_open_in_browser()
        assert any("headless" in n.lower() or "browser" in n.lower() for n in notifications)
        assert fake_app.open_url.call_count == 0


# ---------------------------------------------------------------------------
# action_cycle_transport — single worker, direct field assignment
# ---------------------------------------------------------------------------

class TestCycleTransportFields:
    """action_cycle_transport sets fields directly without calling set_external_url."""

    def _make_widget_with_nomadnet_and_i2p(self):
        w = PageBrowserWidget(destination_hash="nomadnet_dest_hash")
        w._external_url = ""
        w._active_transport = Transport.NOMADNET
        dev = _FakeDevice(
            nomadnet_destination_hash="nomadnet_dest_hash",
            b32_address="something.b32.i2p",
        )
        w._mesh_device = dev
        return w

    def test_cycle_to_i2p_sets_external_url_directly(self):
        w = self._make_widget_with_nomadnet_and_i2p()
        workers_started = []
        w.run_worker = lambda coro, **kw: workers_started.append(coro)
        # set_external_url would also call run_worker — track that it's NOT called
        set_external_url_calls = []
        w.set_external_url = lambda u: set_external_url_calls.append(u)

        w.notify = mock.Mock()
        w.action_cycle_transport()

        assert w._active_transport == Transport.I2P
        assert w._external_url == "http://something.b32.i2p/"
        assert w.destination_hash == ""
        assert w._history == []
        # Exactly one worker started (no double dispatch from set_external_url)
        assert len(workers_started) == 1
        assert len(set_external_url_calls) == 0

    def test_cycle_to_nomadnet_sets_destination_directly(self):
        w = PageBrowserWidget(external_url="http://something.b32.i2p/")
        w._external_url = "http://something.b32.i2p/"
        w._active_transport = Transport.I2P
        dev = _FakeDevice(
            nomadnet_destination_hash="nomadnet_dest_hash",
            b32_address="something.b32.i2p",
        )
        w._mesh_device = dev
        workers_started = []
        w.run_worker = lambda coro, **kw: workers_started.append(coro)
        set_external_url_calls = []
        w.set_external_url = lambda u: set_external_url_calls.append(u)
        w.notify = mock.Mock()

        w.action_cycle_transport()

        assert w._active_transport == Transport.NOMADNET
        assert w._external_url == ""
        assert w.destination_hash == "nomadnet_dest_hash"
        assert w._history == []
        assert len(workers_started) == 1
        assert len(set_external_url_calls) == 0

    def test_cycle_clears_history(self):
        w = self._make_widget_with_nomadnet_and_i2p()
        w._history = ["/page/a.mu", "/page/b.mu"]
        w.run_worker = lambda coro, **kw: None
        w.notify = mock.Mock()
        w.action_cycle_transport()
        assert w._history == []


# ---------------------------------------------------------------------------
# _last_content_kind set on all render paths
# ---------------------------------------------------------------------------

class TestContentKindUnconditional:
    """_last_content_kind is set even when structured renderer is used."""

    def test_detect_content_type_called_before_structured_render(self):
        """The content-type detection runs unconditionally, not only on fallback path."""
        import asyncio

        from styrened.tui.widgets.page_browser import detect_content_type

        w = PageBrowserWidget(destination_hash="a" * 32)
        # Simulate a result with both structured_data AND content_type
        fake_result = {
            "status": "ok",
            "content": "<html><body>hi</body></html>",
            "content_type": "text/html",
            "transfer_time": 0.1,
            "content_length": 26,
            "structured_data": {"title": "Test"},
            "page_metadata": {"page_type": "node_info"},
        }
        detected_kinds = []

        original_detect = detect_content_type

        def _tracking_detect(content, ct):
            kind = original_detect(content, ct)
            detected_kinds.append(kind)
            return kind

        bridge = mock.AsyncMock()
        bridge.fetch_page = mock.AsyncMock(return_value=fake_result)
        # spawn_lane is called synchronously — must return a bridge, not a coroutine
        bridge.spawn_lane = mock.MagicMock(return_value=bridge)
        bridge.connected = True

        with mock.patch("styrened.tui.widgets.page_browser.detect_content_type", _tracking_detect):
            with mock.patch("styrened.tui.widgets.page_browser.render_structured_page", return_value="rendered"):
                with mock.patch.object(type(w), "_ipc_bridge", new_callable=lambda: property(lambda self: bridge)):
                    with mock.patch.object(w, "query_one", side_effect=Exception("no DOM")):
                        asyncio.run(w._load_page("/page/index.mu"))

        # detect_content_type was called exactly once
        assert len(detected_kinds) == 1
        assert detected_kinds[0] == ContentKind.HTML
        assert w._last_content_kind == ContentKind.HTML
