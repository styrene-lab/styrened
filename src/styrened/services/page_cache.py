"""Page cache service for NomadNet page content.

Provides write-through caching of fetched NomadNet pages and
background site crawling for saved/bookmarked nodes.

Architecture:
    - Write-through: every successful fetch_page stores to SQLite
    - Read fallback: on fetch failure, return cached content with timestamp
    - Saved sites: user can "save" a node for periodic background crawling
    - Crawler: BFS from index.mu, follows same-node links up to depth limit
"""

import asyncio
import logging
import re
import time
import urllib.parse
from collections import deque
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from styrened.models.messages import PageCache, SavedSite

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from styrened.services.page_browser import PageBrowserService

logger = logging.getLogger(__name__)

# Link pattern in micron: `[label`url`fields] or `[url]
_MICRON_LINK_RE = re.compile(r"`\[([^]]*)]")


def extract_page_links(content: str) -> list[str]:
    """Extract same-node page links from micron content.

    Parses `[label`url`fields] patterns and returns paths that
    are same-node references (start with / or are relative .mu paths).

    Args:
        content: Raw micron markup content.

    Returns:
        List of page paths found in the content.
    """
    links: list[str] = []
    for match in _MICRON_LINK_RE.finditer(content):
        inner = match.group(1)
        # Split on backtick — parts are [label, url, fields] or [url]
        parts = inner.split("`")
        if len(parts) >= 2:
            url = parts[1].strip()
        else:
            url = parts[0].strip()

        if not url:
            continue

        # Same-node links only
        if url.startswith(":"):
            url = url[1:]  # Strip colon prefix (self-reference)
        if ":" in url and not url.startswith("/"):
            continue  # Cross-node link, skip

        # Normalize
        if not url.startswith("/"):
            url = f"/page/{url}"
        if not url.endswith(".mu"):
            url = f"{url}.mu" if "." not in url.split("/")[-1] else url

        if url not in links:
            links.append(url)
    return links


class PageCacheService:
    """Manages page caching and background site crawling.

    Works alongside PageBrowserService — receives fetch results for
    write-through caching and provides cached fallbacks on failure.
    NomadNet crawling remains destination-based; explicit HTTP(S)/I2P
    URLs use direct cache entries keyed by URL.
    """

    def __init__(self, engine: "Engine", i2p_cache_ttl: int = 3600) -> None:
        self._engine = engine
        self._i2p_cache_ttl = i2p_cache_ttl
        self._crawl_task: asyncio.Task | None = None
        self._started = False
        self._page_browser: PageBrowserService | None = None

    def set_page_browser(self, browser: "PageBrowserService") -> None:
        """Set reference to PageBrowserService for crawling."""
        self._page_browser = browser

    async def start(self) -> None:
        """Start the cache service and background crawl timer."""
        if self._started:
            return
        self._started = True
        self._crawl_task = asyncio.create_task(self._crawl_loop())
        logger.info("PageCacheService started")

    async def stop(self) -> None:
        """Stop the cache service."""
        self._started = False
        if self._crawl_task:
            self._crawl_task.cancel()
            try:
                await self._crawl_task
            except asyncio.CancelledError:
                pass
            self._crawl_task = None
        logger.info("PageCacheService stopped")

    def _cache_key_for_url(self, url: str) -> tuple[str, str]:
        parsed = urllib.parse.urlparse(url)
        transport = "i2p" if (parsed.hostname or "").lower().endswith(".i2p") else (parsed.scheme or "http")
        return (f"url:{transport}", url)

    def get_cache_ttl_for_url(self, url: str) -> int | None:
        parsed = urllib.parse.urlparse(url)
        if (parsed.hostname or "").lower().endswith(".i2p"):
            return self._i2p_cache_ttl
        return None

    def cache_page(self, destination_hash: str, path: str, content: str) -> None:
        """Write-through cache a page after successful fetch.

        Args:
            destination_hash: Hex destination hash.
            path: Page path.
            content: Raw micron content.
        """
        try:
            with Session(self._engine) as session:
                existing = session.execute(
                    select(PageCache).where(
                        PageCache.destination_hash == destination_hash,
                        PageCache.path == path,
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.content = content
                    existing.content_length = len(content.encode("utf-8"))
                    existing.fetched_at = time.time()
                else:
                    session.add(
                        PageCache(
                            destination_hash=destination_hash,
                            path=path,
                            content=content,
                            content_length=len(content.encode("utf-8")),
                            fetched_at=time.time(),
                        )
                    )
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to cache page {path}: {e}")

    def cache_url(self, url: str, content: str) -> None:
        """Write-through cache an explicit HTTP(S)/I2P URL fetch."""
        destination_hash, path = self._cache_key_for_url(url)
        self.cache_page(destination_hash, path, content)

    def get_cached_page(
        self, destination_hash: str, path: str
    ) -> dict[str, Any] | None:
        """Retrieve a cached page.

        Args:
            destination_hash: Hex destination hash.
            path: Page path.

        Returns:
            Dict with content, content_length, fetched_at or None.
        """
        try:
            with Session(self._engine) as session:
                row = session.execute(
                    select(PageCache).where(
                        PageCache.destination_hash == destination_hash,
                        PageCache.path == path,
                    )
                ).scalar_one_or_none()

                if row:
                    return {
                        "content": row.content,
                        "content_length": row.content_length,
                        "fetched_at": row.fetched_at,
                    }
        except Exception as e:
            logger.warning(f"Failed to read cached page {path}: {e}")
        return None

    def get_cached_url(self, url: str, max_age: int | None = None) -> dict[str, Any] | None:
        """Retrieve a cached HTTP(S)/I2P URL entry.

        Args:
            url: Explicit URL key.
            max_age: Optional freshness limit in seconds.
        """
        destination_hash, path = self._cache_key_for_url(url)
        cached = self.get_cached_page(destination_hash, path)
        if not cached:
            return None
        if max_age is not None and (time.time() - cached["fetched_at"]) > max_age:
            return None
        return cached

    def get_cached_pages_for_site(
        self, destination_hash: str
    ) -> list[dict[str, Any]]:
        """Get all cached pages for a destination.

        Returns:
            List of dicts with path, content_length, fetched_at.
        """
        try:
            with Session(self._engine) as session:
                rows = session.execute(
                    select(PageCache).where(
                        PageCache.destination_hash == destination_hash,
                    )
                ).scalars().all()
                return [
                    {
                        "path": r.path,
                        "content_length": r.content_length,
                        "fetched_at": r.fetched_at,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to list cached pages: {e}")
            return []

    # --- Saved Sites ---

    def save_site(
        self,
        destination_hash: str,
        display_name: str = "",
        refresh_interval: int = 3600,
        max_depth: int = 3,
    ) -> None:
        """Register a node for periodic background crawling.

        Args:
            destination_hash: Hex destination hash.
            display_name: Human-readable name for the site.
            refresh_interval: Seconds between crawls.
            max_depth: Maximum link-following depth from index.mu.
        """
        try:
            with Session(self._engine) as session:
                existing = session.execute(
                    select(SavedSite).where(
                        SavedSite.destination_hash == destination_hash,
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.display_name = display_name or existing.display_name
                    existing.refresh_interval = refresh_interval
                    existing.max_depth = max_depth
                else:
                    session.add(
                        SavedSite(
                            destination_hash=destination_hash,
                            display_name=display_name,
                            refresh_interval=refresh_interval,
                            max_depth=max_depth,
                        )
                    )
                session.commit()
                logger.info(
                    f"Saved site {destination_hash[:16]}... "
                    f"(name={display_name!r}, interval={refresh_interval}s, depth={max_depth})"
                )
        except Exception as e:
            logger.warning(f"Failed to save site: {e}")

    def remove_site(self, destination_hash: str) -> bool:
        """Remove a saved site (stops background crawling).

        Returns:
            True if site was found and removed.
        """
        try:
            with Session(self._engine) as session:
                site = session.execute(
                    select(SavedSite).where(
                        SavedSite.destination_hash == destination_hash,
                    )
                ).scalar_one_or_none()
                if site:
                    session.delete(site)
                    session.commit()
                    logger.info(f"Removed saved site {destination_hash[:16]}...")
                    return True
        except Exception as e:
            logger.warning(f"Failed to remove saved site: {e}")
        return False

    def list_saved_sites(self) -> list[dict[str, Any]]:
        """List all saved sites.

        Returns:
            List of site dicts with destination_hash, display_name, etc.
        """
        try:
            with Session(self._engine) as session:
                rows = session.execute(select(SavedSite)).scalars().all()
                return [
                    {
                        "destination_hash": r.destination_hash,
                        "display_name": r.display_name,
                        "refresh_interval": r.refresh_interval,
                        "last_crawl_at": r.last_crawl_at,
                        "pages_cached": r.pages_cached,
                        "max_depth": r.max_depth,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Failed to list saved sites: {e}")
            return []

    def is_site_saved(self, destination_hash: str) -> bool:
        """Check if a destination is a saved site."""
        try:
            with Session(self._engine) as session:
                return (
                    session.execute(
                        select(SavedSite).where(
                            SavedSite.destination_hash == destination_hash,
                        )
                    ).scalar_one_or_none()
                    is not None
                )
        except Exception:
            return False

    # --- Crawling ---

    async def crawl_site(
        self,
        destination_hash: str,
        max_depth: int = 3,
        progress_callback: Any = None,
    ) -> int:
        """Crawl a NomadNet node, caching all reachable pages.

        BFS from /page/index.mu, following same-node links up to max_depth.

        Args:
            destination_hash: Hex destination hash.
            max_depth: Maximum depth from index page.
            progress_callback: Optional async callable(pages_done, pages_total, current_path).

        Returns:
            Number of pages cached.
        """
        if self._page_browser is None:
            logger.warning("Cannot crawl — no page browser service")
            return 0

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([("/page/index.mu", 0)])
        pages_cached = 0

        while queue:
            path, depth = queue.popleft()
            if path in visited:
                continue
            visited.add(path)

            if progress_callback:
                try:
                    await progress_callback(pages_cached, len(visited) + len(queue), path)
                except Exception:
                    pass

            logger.debug(f"Crawling {destination_hash[:16]}...:{path} (depth={depth})")

            try:
                response = await self._page_browser.fetch_page(
                    destination_hash=destination_hash,
                    path=path,
                    timeout=30.0,
                )
            except Exception as e:
                logger.warning(f"Crawl fetch failed for {path}: {e}")
                continue

            if response.status.value != "ok":
                logger.debug(f"Crawl: {path} returned {response.status.value}")
                continue

            # Cache the page
            self.cache_page(destination_hash, path, response.content)
            pages_cached += 1

            # Follow links if within depth limit
            if depth < max_depth:
                links = extract_page_links(response.content)
                for link in links:
                    if link not in visited:
                        queue.append((link, depth + 1))

        # Update saved site stats
        try:
            with Session(self._engine) as session:
                site = session.execute(
                    select(SavedSite).where(
                        SavedSite.destination_hash == destination_hash,
                    )
                ).scalar_one_or_none()
                if site:
                    site.last_crawl_at = time.time()
                    site.pages_cached = pages_cached
                    session.commit()
        except Exception:
            pass

        logger.info(
            f"Crawl complete for {destination_hash[:16]}...: "
            f"{pages_cached} pages cached from {len(visited)} visited"
        )
        return pages_cached

    async def _crawl_loop(self) -> None:
        """Background task that periodically refreshes saved sites."""
        try:
            # Wait a bit before first crawl to let daemon stabilize
            await asyncio.sleep(60)

            while self._started:
                await self._refresh_stale_sites()
                await asyncio.sleep(300)  # Check every 5 minutes
        except asyncio.CancelledError:
            pass

    async def _refresh_stale_sites(self) -> None:
        """Crawl any saved sites that are past their refresh interval."""
        sites = self.list_saved_sites()
        now = time.time()

        for site in sites:
            if not self._started:
                break

            elapsed = now - site["last_crawl_at"]
            if elapsed < site["refresh_interval"]:
                continue

            dest = site["destination_hash"]
            logger.info(
                f"Background refresh for saved site {dest[:16]}... "
                f"(stale by {elapsed - site['refresh_interval']:.0f}s)"
            )
            try:
                await self.crawl_site(
                    dest,
                    max_depth=site["max_depth"],
                )
            except Exception as e:
                logger.warning(f"Background crawl failed for {dest[:16]}...: {e}")

            # Small delay between sites to avoid flooding
            await asyncio.sleep(5)
