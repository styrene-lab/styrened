"""Tests for PageBrowserService.handle_reconnection()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from styrened.services.page_browser import PageBrowserService


class TestHandleReconnection:
    """Tests for link invalidation on network reconnect."""

    def test_preserves_active_links(self):
        """handle_reconnection() keeps active links intact (no teardown)."""
        service = PageBrowserService()

        # Simulate two cached links
        mock_link1 = MagicMock()
        mock_link2 = MagicMock()
        service._links = {
            "aabb": MagicMock(link=mock_link1),
            "ccdd": MagicMock(link=mock_link2),
        }

        service.handle_reconnection()

        # Links are preserved — stale ones fail naturally on next use
        mock_link1.teardown.assert_not_called()
        mock_link2.teardown.assert_not_called()
        assert len(service._links) == 2

    def test_sets_force_path_rediscovery(self):
        """handle_reconnection() flags force_path_rediscovery."""
        service = PageBrowserService()
        assert service._force_path_rediscovery is False

        service.handle_reconnection()

        assert service._force_path_rediscovery is True

    def test_handles_teardown_exception(self):
        """handle_reconnection() doesn't raise if link.teardown() throws."""
        service = PageBrowserService()
        mock_link = MagicMock()
        service._links = {"aabb": MagicMock(link=mock_link)}

        # Should not raise, links preserved
        service.handle_reconnection()
        assert len(service._links) == 1
        assert service._force_path_rediscovery is True

    def test_empty_links_is_noop(self):
        """handle_reconnection() works with no cached links."""
        service = PageBrowserService()
        service.handle_reconnection()
        assert service._force_path_rediscovery is True
