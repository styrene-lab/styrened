"""Tests for PageCacheService."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine

from styrened.models.messages import Base, PageCache, SavedSite
from styrened.services.page_cache import PageCacheService, extract_page_links


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with cache tables."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def cache_service(engine):
    """Create a PageCacheService with in-memory DB."""
    return PageCacheService(engine)


class TestExtractPageLinks:
    """Test micron link extraction."""

    def test_simple_link(self):
        content = "`[Documentation`/page/docs/index.mu]"
        links = extract_page_links(content)
        assert "/page/docs/index.mu" in links

    def test_relative_link(self):
        content = "`[About`about.mu]"
        links = extract_page_links(content)
        assert "/page/about.mu" in links

    def test_self_reference_link(self):
        content = "`[Home`:/page/index.mu]"
        links = extract_page_links(content)
        assert "/page/index.mu" in links

    def test_cross_node_link_ignored(self):
        content = "`[Remote`abcdef12:/page/index.mu]"
        links = extract_page_links(content)
        assert len(links) == 0

    def test_multiple_links(self):
        content = (
            "`[Docs`/page/docs.mu]\n"
            "`[About`/page/about.mu]\n"
            "`[Home`/page/index.mu]"
        )
        links = extract_page_links(content)
        assert len(links) == 3

    def test_deduplication(self):
        content = "`[Home`/page/index.mu]\n`[Home Again`/page/index.mu]"
        links = extract_page_links(content)
        assert len(links) == 1

    def test_empty_content(self):
        assert extract_page_links("") == []


class TestPageCacheService:
    """Test page caching operations."""

    def test_cache_and_retrieve(self, cache_service):
        cache_service.cache_page("aabb", "/page/index.mu", "Hello World")
        result = cache_service.get_cached_page("aabb", "/page/index.mu")
        assert result is not None
        assert result["content"] == "Hello World"
        assert result["content_length"] == 11
        assert result["fetched_at"] > 0

    def test_cache_update(self, cache_service):
        cache_service.cache_page("aabb", "/page/index.mu", "Version 1")
        cache_service.cache_page("aabb", "/page/index.mu", "Version 2")
        result = cache_service.get_cached_page("aabb", "/page/index.mu")
        assert result["content"] == "Version 2"

    def test_cache_miss(self, cache_service):
        result = cache_service.get_cached_page("nonexistent", "/page/index.mu")
        assert result is None

    def test_get_cached_pages_for_site(self, cache_service):
        cache_service.cache_page("aabb", "/page/index.mu", "Index")
        cache_service.cache_page("aabb", "/page/about.mu", "About")
        cache_service.cache_page("ccdd", "/page/index.mu", "Other")

        pages = cache_service.get_cached_pages_for_site("aabb")
        assert len(pages) == 2
        paths = [p["path"] for p in pages]
        assert "/page/index.mu" in paths
        assert "/page/about.mu" in paths


class TestSavedSites:
    """Test saved site operations."""

    def test_save_and_list(self, cache_service):
        cache_service.save_site("aabb", "Test Hub", 3600, 3)
        sites = cache_service.list_saved_sites()
        assert len(sites) == 1
        assert sites[0]["destination_hash"] == "aabb"
        assert sites[0]["display_name"] == "Test Hub"
        assert sites[0]["refresh_interval"] == 3600

    def test_is_site_saved(self, cache_service):
        assert not cache_service.is_site_saved("aabb")
        cache_service.save_site("aabb", "Test")
        assert cache_service.is_site_saved("aabb")

    def test_remove_site(self, cache_service):
        cache_service.save_site("aabb", "Test")
        assert cache_service.remove_site("aabb")
        assert not cache_service.is_site_saved("aabb")

    def test_remove_nonexistent(self, cache_service):
        assert not cache_service.remove_site("nonexistent")

    def test_update_existing_site(self, cache_service):
        cache_service.save_site("aabb", "Old Name", 3600)
        cache_service.save_site("aabb", "New Name", 7200)
        sites = cache_service.list_saved_sites()
        assert len(sites) == 1
        assert sites[0]["display_name"] == "New Name"
        assert sites[0]["refresh_interval"] == 7200


class TestCrawlSite:
    """Test site crawling."""

    @pytest.mark.asyncio
    async def test_crawl_no_browser(self, cache_service):
        """Crawl without page browser returns 0."""
        count = await cache_service.crawl_site("aabb")
        assert count == 0

    @pytest.mark.asyncio
    async def test_crawl_single_page(self, cache_service):
        """Crawl with a page that has no links."""
        mock_browser = AsyncMock()
        mock_response = MagicMock()
        mock_response.status.value = "ok"
        mock_response.content = "`!Simple Page`!\nNo links here."
        mock_browser.fetch_page = AsyncMock(return_value=mock_response)

        cache_service.set_page_browser(mock_browser)
        count = await cache_service.crawl_site("aabb", max_depth=2)
        assert count == 1

        # Verify cached
        cached = cache_service.get_cached_page("aabb", "/page/index.mu")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_crawl_follows_links(self, cache_service):
        """Crawl follows same-node links."""
        mock_browser = AsyncMock()

        index_response = MagicMock()
        index_response.status.value = "ok"
        index_response.content = "`!Index`!\n`[About`/page/about.mu]"

        about_response = MagicMock()
        about_response.status.value = "ok"
        about_response.content = "`!About`!\nJust text."

        async def fake_fetch(destination_hash, path="/page/index.mu", **kwargs):
            if path == "/page/index.mu":
                return index_response
            elif path == "/page/about.mu":
                return about_response
            fail = MagicMock()
            fail.status.value = "not_found"
            return fail

        mock_browser.fetch_page = AsyncMock(side_effect=fake_fetch)
        cache_service.set_page_browser(mock_browser)

        count = await cache_service.crawl_site("aabb", max_depth=2)
        assert count == 2

    @pytest.mark.asyncio
    async def test_crawl_respects_depth_limit(self, cache_service):
        """Crawl stops at max_depth."""
        mock_browser = AsyncMock()

        async def fake_fetch(destination_hash, path="/page/index.mu", **kwargs):
            resp = MagicMock()
            resp.status.value = "ok"
            # Each page links to a deeper one
            depth = path.count("/") - 1
            resp.content = f"`!Page {depth}`!\n`[Deeper`/page/level{depth + 1}/index.mu]"
            return resp

        mock_browser.fetch_page = AsyncMock(side_effect=fake_fetch)
        cache_service.set_page_browser(mock_browser)

        count = await cache_service.crawl_site("aabb", max_depth=1)
        # index.mu (depth 0) + one level of links (depth 1)
        assert count <= 3  # Bounded by depth
