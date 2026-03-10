"""Unit tests for PageBrowserService.

Tests service lifecycle, page fetching with mocked RNS,
link caching, idle cleanup, and disconnect.
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from styrened.services.page_browser import (
    LINK_IDLE_TIMEOUT,
    PageBrowserService,
    PageStatus,
    _LinkEntry,
)


@pytest.fixture
def service():
    """Create a fresh PageBrowserService."""
    return PageBrowserService()


class TestServiceLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_captures_event_loop(self, service):
        """Start should capture the event loop and start cleanup task."""
        await service.start()
        try:
            assert service._started is True
            assert service._event_loop is not None
            assert service._cleanup_task is not None
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, service):
        """Calling start twice should not create duplicate cleanup tasks."""
        await service.start()
        try:
            task = service._cleanup_task
            await service.start()
            assert service._cleanup_task is task
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_state(self, service):
        """Stop should clear links and cancel cleanup task."""
        await service.start()
        await service.stop()

        assert service._started is False
        assert service._cleanup_task is None
        assert len(service._links) == 0

    @pytest.mark.asyncio
    async def test_stop_tears_down_cached_links(self, service):
        """Stop should teardown all cached links."""
        await service.start()

        mock_link = MagicMock()
        service._links["abc"] = _LinkEntry(
            link=mock_link, destination_hash="abc", established=True,
        )

        await service.stop()

        mock_link.teardown.assert_called_once()
        assert len(service._links) == 0


class TestFetchPage:
    """Tests for fetch_page() with mocked RNS."""

    @pytest.mark.asyncio
    async def test_invalid_hex_hash_returns_error(self, service):
        """Invalid hex destination hash should return ERROR status."""
        await service.start()
        try:
            response = await service.fetch_page("not-valid-hex")
            assert response.status == PageStatus.ERROR
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_no_path_returns_path_not_found(self, service):
        """When RNS has no path, should return PATH_NOT_FOUND after timeout."""
        await service.start()
        try:
            mock_transport = MagicMock()
            mock_transport.has_path.return_value = False
            mock_transport.request_path.return_value = None

            with patch.dict("sys.modules", {"RNS": MagicMock()}):
                import sys
                rns_mock = sys.modules["RNS"]
                rns_mock.Transport = mock_transport

                # Use very short timeout to avoid slow test
                with patch("styrened.services.page_browser.PATH_DISCOVERY_TIMEOUT", 0.1):
                    response = await service.fetch_page("a" * 32)

            assert response.status == PageStatus.PATH_NOT_FOUND
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_no_identity_returns_link_failed(self, service):
        """When identity cannot be recalled, should return LINK_FAILED."""
        await service.start()
        try:
            with patch.dict("sys.modules", {"RNS": MagicMock()}):
                import sys
                rns_mock = sys.modules["RNS"]
                rns_mock.Transport.has_path.return_value = True
                rns_mock.Identity.recall.return_value = None

                response = await service.fetch_page("a" * 32)

            assert response.status == PageStatus.LINK_FAILED
            assert response.error_message is not None
        finally:
            await service.stop()


class TestFetchUrl:
    """Tests for explicit HTTP(S)/I2P URL fetching."""

    @pytest.mark.asyncio
    async def test_fetch_url_rejects_unsupported_scheme(self, service):
        await service.start()
        try:
            response = await service.fetch_url("nomadnet://example/index.mu")
            assert response.status == PageStatus.ERROR
            assert "Unsupported URL scheme" in (response.error_message or "")
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_fetch_i2p_requires_explicit_enablement(self, service):
        await service.start()
        try:
            response = await service.fetch_url("http://docs.example.i2p/")
            assert response.status == PageStatus.ERROR
            assert response.error_message == "I2P not enabled — set i2p.mode: adopt or managed in config."
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_fetch_i2p_requires_ready_proxy(self):
        service = PageBrowserService(i2p_adapter=MagicMock())
        service._i2p_adapter.get_http_proxy_url.return_value = None
        await service.start()
        try:
            response = await service.fetch_url("http://docs.example.i2p/")
            assert response.status == PageStatus.ERROR
            assert "proxy is not ready" in (response.error_message or "")
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_fetch_url_uses_proxy_for_i2p(self):
        adapter = MagicMock()
        adapter.get_http_proxy_url.return_value = "http://127.0.0.1:4445"
        service = PageBrowserService(i2p_adapter=adapter)
        await service.start()
        try:
            mock_response = MagicMock()
            mock_response.read.return_value = b"hello over i2p"
            mock_response.headers.get_content_charset.return_value = "utf-8"
            mock_response.__enter__.return_value = mock_response
            mock_response.__exit__.return_value = None

            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_response

            with patch("urllib.request.build_opener", return_value=mock_opener) as mock_build:
                response = await service.fetch_url("http://docs.example.i2p/")

            assert response.status == PageStatus.OK
            assert response.content == "hello over i2p"
            assert mock_build.call_args is not None
            proxy_handler = mock_build.call_args.args[0]
            assert proxy_handler.proxies["http"] == "http://127.0.0.1:4445"
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_fetch_https_does_not_require_i2p(self, service):
        await service.start()
        try:
            mock_response = MagicMock()
            mock_response.read.return_value = b"hello over https"
            mock_response.headers.get_content_charset.return_value = "utf-8"
            mock_response.__enter__.return_value = mock_response
            mock_response.__exit__.return_value = None

            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_response

            with patch("urllib.request.build_opener", return_value=mock_opener):
                response = await service.fetch_url("https://docs.styrene.io/")

            assert response.status == PageStatus.OK
            assert response.content == "hello over https"
        finally:
            await service.stop()


class TestDisconnect:
    """Tests for disconnect() method."""

    @pytest.mark.asyncio
    async def test_disconnect_existing_link(self, service):
        """Disconnect should teardown and remove cached link."""
        mock_link = MagicMock()
        service._links["abc123"] = _LinkEntry(
            link=mock_link, destination_hash="abc123", established=True,
        )

        result = await service.disconnect("abc123")

        assert result is True
        mock_link.teardown.assert_called_once()
        assert "abc123" not in service._links

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_link(self, service):
        """Disconnect should return False when no link exists."""
        result = await service.disconnect("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_handles_teardown_error(self, service):
        """Disconnect should handle teardown exceptions gracefully."""
        mock_link = MagicMock()
        mock_link.teardown.side_effect = Exception("teardown error")
        service._links["abc123"] = _LinkEntry(
            link=mock_link, destination_hash="abc123", established=True,
        )

        result = await service.disconnect("abc123")

        assert result is True
        assert "abc123" not in service._links


class TestCleanupIdleLinks:
    """Tests for idle link cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_idle_links(self, service):
        """Links idle beyond threshold should be cleaned up."""
        mock_link = MagicMock()
        service._links["old"] = _LinkEntry(
            link=mock_link,
            destination_hash="old",
            last_used=time.time() - LINK_IDLE_TIMEOUT - 10,
            established=True,
        )

        await service._cleanup_idle_links()

        assert "old" not in service._links
        mock_link.teardown.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_keeps_active_links(self, service):
        """Recently used links should not be cleaned up."""
        mock_link = MagicMock()
        service._links["active"] = _LinkEntry(
            link=mock_link,
            destination_hash="active",
            last_used=time.time(),
            established=True,
        )

        await service._cleanup_idle_links()

        assert "active" in service._links
        mock_link.teardown.assert_not_called()


class TestActiveLinkCount:
    """Tests for active_link_count property."""

    def test_empty(self, service):
        assert service.active_link_count == 0

    def test_with_links(self, service):
        service._links["a"] = _LinkEntry(
            link=MagicMock(), destination_hash="a",
        )
        service._links["b"] = _LinkEntry(
            link=MagicMock(), destination_hash="b",
        )
        assert service.active_link_count == 2


class TestResolveFuture:
    """Tests for _resolve_future() static helper."""

    @pytest.mark.asyncio
    async def test_resolve_sets_result(self):
        """Should set result on an unresolved future."""
        future: asyncio.Future = asyncio.Future()
        await PageBrowserService._resolve_future(future, "value")
        assert future.result() == "value"

    @pytest.mark.asyncio
    async def test_resolve_ignores_already_done(self):
        """Should not raise if future is already resolved."""
        future: asyncio.Future = asyncio.Future()
        future.set_result("first")
        # Should not raise
        await PageBrowserService._resolve_future(future, "second")
        assert future.result() == "first"


class TestErrorMessages:
    """All error returns include a descriptive error_message."""

    @pytest.mark.asyncio
    async def test_invalid_hex_has_error_message(self, service):
        """Invalid hex hash should include error_message."""
        await service.start()
        try:
            response = await service.fetch_page("not-valid-hex")
            assert response.status == PageStatus.ERROR
            assert response.error_message is not None
            assert "Invalid" in response.error_message
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_path_timeout_has_error_message(self, service):
        """Path discovery timeout should include error_message."""
        await service.start()
        try:
            mock_transport = MagicMock()
            mock_transport.has_path.return_value = False
            mock_transport.request_path.return_value = None

            with patch.dict("sys.modules", {"RNS": MagicMock()}):
                import sys
                rns_mock = sys.modules["RNS"]
                rns_mock.Transport = mock_transport

                with patch("styrened.services.page_browser.PATH_DISCOVERY_TIMEOUT", 0.1):
                    response = await service.fetch_page("a" * 32)

            assert response.status == PageStatus.PATH_NOT_FOUND
            assert response.error_message is not None
            assert "timed out" in response.error_message.lower()
        finally:
            await service.stop()

    @pytest.mark.asyncio
    async def test_identity_recall_failure_has_error_message(self, service):
        """Identity recall failure should include error_message."""
        await service.start()
        try:
            with patch.dict("sys.modules", {"RNS": MagicMock()}):
                import sys
                rns_mock = sys.modules["RNS"]
                rns_mock.Transport.has_path.return_value = True
                rns_mock.Identity.recall.return_value = None

                response = await service.fetch_page("a" * 32)

            assert response.status == PageStatus.LINK_FAILED
            assert response.error_message is not None
            assert "identity" in response.error_message.lower()
        finally:
            await service.stop()
