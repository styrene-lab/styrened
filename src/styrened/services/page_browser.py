"""Page browser service for NomadNet node page fetching.

Manages outgoing RNS.Links to NomadNet nodes for browsing their served pages.
This is the first client-side RNS.Link usage in styrened — the existing
TerminalService handles server-side (incoming) Links.

Architecture:
    1. Check path to destination, request if missing
    2. Recall identity from destination hash
    3. Get or create RNS.Link to ("nomadnetwork", "node") destination
    4. Send page request via link.request()
    5. Await response via asyncio.Future bridged from RNS callbacks
    6. Decode UTF-8 micron markup, return PageResponse

Usage:
    service = PageBrowserService()
    await service.start()
    response = await service.fetch_page("abcdef1234567890", "/page/index.mu")
    await service.stop()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import RNS

    from styrened.pages.directives import PageMetadata

logger = logging.getLogger(__name__)

# Timeouts
PATH_DISCOVERY_TIMEOUT = 10.0  # Seconds to wait for path discovery
LINK_ESTABLISHMENT_TIMEOUT = 15.0  # Seconds to wait for link establishment
REQUEST_TIMEOUT = 30.0  # Default page request timeout
LINK_IDLE_TIMEOUT = 120.0  # Seconds before idle link teardown
CLEANUP_INTERVAL = 30.0  # Seconds between cleanup checks


class PageStatus(Enum):
    """Status of a page fetch operation."""

    OK = "ok"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    LINK_FAILED = "link_failed"
    PATH_NOT_FOUND = "path_not_found"
    ERROR = "error"


@dataclass
class PageResponse:
    """Response from a NomadNet page fetch."""

    content: str
    status: PageStatus
    destination_hash: str
    path: str
    transfer_time: float
    content_length: int
    cache_ttl: int | None = None
    error_message: str | None = None
    structured_data: dict[str, Any] | None = None
    page_metadata: "PageMetadata | None" = None


@dataclass
class _LinkEntry:
    """Internal tracking for a cached RNS.Link."""

    link: "RNS.Link"
    destination_hash: str
    last_used: float = field(default_factory=time.time)
    established: bool = False


class PageBrowserService:
    """Manages RNS.Link lifecycle for NomadNet page browsing.

    Maintains a pool of cached links (one per destination) and handles
    path discovery, link establishment, and page request/response flow.
    Thread safety is handled by bridging RNS callbacks to the asyncio
    event loop via run_coroutine_threadsafe().
    """

    def __init__(self) -> None:
        self._links: dict[str, _LinkEntry] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._started = False
        self._force_path_rediscovery = False

    async def start(self) -> None:
        """Start the page browser service.

        Captures the event loop and starts the idle link cleanup task.
        """
        if self._started:
            return

        self._event_loop = asyncio.get_running_loop()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._started = True
        logger.info("PageBrowserService started")

    def handle_reconnection(self) -> None:
        """Handle network reconnection by flagging path re-discovery.

        Called by the daemon's reconnection callback chain.  Does NOT
        tear down active links (they may still be healthy).  Stale links
        fail naturally on next use and get cleaned up then.
        """
        logger.info("[RECONNECT] PageBrowserService forcing path re-discovery (keeping active links)")
        # Don't tear down active links — they may still be healthy.
        # Only flag path re-discovery for the next fetch.
        # Stale links will fail naturally and get cleaned up on next use.
        self._force_path_rediscovery = True

    async def stop(self) -> None:
        """Stop the service and tear down all links."""
        self._started = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Tear down all cached links
        for _dest_hash, entry in list(self._links.items()):
            try:
                entry.link.teardown()
            except Exception:
                pass
        self._links.clear()

        logger.info("PageBrowserService stopped")

    async def fetch_page(
        self,
        destination_hash: str,
        path: str = "/page/index.mu",
        form_data: dict | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> PageResponse:
        """Fetch a page from a NomadNet node.

        Args:
            destination_hash: Hex-encoded destination hash of the NomadNet node.
            path: Page path to request (default: /page/index.mu).
            form_data: Optional form data to submit with the request.
            timeout: Request timeout in seconds.

        Returns:
            PageResponse with content and metadata.
        """
        import RNS

        start_time = time.time()

        # Convert hex hash to bytes
        try:
            dest_hash_bytes = bytes.fromhex(destination_hash)
        except ValueError:
            return PageResponse(
                content="",
                status=PageStatus.ERROR,
                destination_hash=destination_hash,
                path=path,
                transfer_time=0.0,
                content_length=0,
                error_message="Invalid destination hash format",
            )

        # Step 1: Ensure path exists (force re-request if flagged)
        force_path = self._force_path_rediscovery
        if force_path or not RNS.Transport.has_path(dest_hash_bytes):
            if force_path:
                logger.info(f"Forcing path re-discovery for {destination_hash[:16]}... (post-reconnect)")
                self._force_path_rediscovery = False
            else:
                logger.debug(f"Requesting path to {destination_hash[:16]}...")
            RNS.Transport.request_path(dest_hash_bytes)

            # Wait for path
            path_wait_start = time.time()
            while not RNS.Transport.has_path(dest_hash_bytes):
                if time.time() - path_wait_start > PATH_DISCOVERY_TIMEOUT:
                    return PageResponse(
                        content="",
                        status=PageStatus.PATH_NOT_FOUND,
                        destination_hash=destination_hash,
                        path=path,
                        transfer_time=time.time() - start_time,
                        content_length=0,
                        error_message="Path discovery timed out — node may be offline",
                    )
                await asyncio.sleep(0.2)

        logger.info(f"Path found for {destination_hash[:16]}..., recalling identity")

        # Step 2: Recall identity
        identity = RNS.Identity.recall(dest_hash_bytes)
        logger.info(f"Identity recall for {destination_hash[:16]}...: {'OK' if identity else 'FAILED'}")
        if identity is None:
            return PageResponse(
                content="",
                status=PageStatus.LINK_FAILED,
                destination_hash=destination_hash,
                path=path,
                transfer_time=time.time() - start_time,
                content_length=0,
                error_message="Cannot recall node identity — try refreshing",
            )

        # Step 3: Get or create link (retry once with forced path re-discovery)
        link = await self._get_or_create_link(destination_hash, identity)
        if link is None:
            # First attempt failed — force path re-discovery and retry.
            # This handles post-network-switch scenarios where the cached
            # RNS path points through a now-dead interface.
            logger.info(f"Link failed for {destination_hash[:16]}..., retrying with fresh path")
            RNS.Transport.request_path(dest_hash_bytes)
            path_wait_start = time.time()
            while not RNS.Transport.has_path(dest_hash_bytes):
                if time.time() - path_wait_start > PATH_DISCOVERY_TIMEOUT:
                    break
                await asyncio.sleep(0.2)
            link = await self._get_or_create_link(destination_hash, identity)

        if link is None:
            return PageResponse(
                content="",
                status=PageStatus.LINK_FAILED,
                destination_hash=destination_hash,
                path=path,
                transfer_time=time.time() - start_time,
                content_length=0,
                error_message="Link establishment failed — node may be offline or unreachable",
            )

        # Step 4: Send page request
        response_future: asyncio.Future[tuple[bytes | None, bool]] = asyncio.Future()

        def response_callback(request_receipt: "RNS.RequestReceipt") -> None:
            """RNS callback when response is received."""
            if self._event_loop is None:
                return
            try:
                response_data = request_receipt.response
                asyncio.run_coroutine_threadsafe(
                    self._resolve_future(response_future, (response_data, True)),
                    self._event_loop,
                )
            except Exception as e:
                logger.warning(f"Error in response callback: {e}")

        def failed_callback(request_receipt: "RNS.RequestReceipt") -> None:
            """RNS callback when request fails."""
            if self._event_loop is None:
                return
            try:
                asyncio.run_coroutine_threadsafe(
                    self._resolve_future(response_future, (None, False)),
                    self._event_loop,
                )
            except Exception as e:
                logger.warning(f"Error in failed callback: {e}")

        try:
            link.request(
                path,
                data=form_data,
                response_callback=response_callback,
                failed_callback=failed_callback,
            )
        except Exception as e:
            logger.error(f"Failed to send page request: {e}")
            return PageResponse(
                content="",
                status=PageStatus.ERROR,
                destination_hash=destination_hash,
                path=path,
                transfer_time=time.time() - start_time,
                content_length=0,
                error_message=str(e),
            )

        # Step 5: Await response
        try:
            response_data, success = await asyncio.wait_for(
                response_future, timeout=timeout
            )
        except TimeoutError:
            return PageResponse(
                content="",
                status=PageStatus.TIMEOUT,
                destination_hash=destination_hash,
                path=path,
                transfer_time=time.time() - start_time,
                content_length=0,
                error_message="Page request timed out",
            )

        transfer_time = time.time() - start_time

        if not success or response_data is None:
            return PageResponse(
                content="",
                status=PageStatus.NOT_FOUND,
                destination_hash=destination_hash,
                path=path,
                transfer_time=transfer_time,
                content_length=0,
                error_message="Node returned no data for this page",
            )

        # Step 6: Decode response
        try:
            if isinstance(response_data, bytes):
                content = response_data.decode("utf-8")
            else:
                content = str(response_data)
        except UnicodeDecodeError:
            content = str(response_data)

        # Parse cache TTL from #!c=N directive
        cache_ttl = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#!c="):
                try:
                    cache_ttl = int(stripped[4:])
                except ValueError:
                    pass

        # Extract Styrene structured data if present
        structured_data: dict[str, Any] | None = None
        page_metadata: PageMetadata | None = None
        try:
            from styrened.pages.parser import parse_page_directives

            parsed = parse_page_directives(content)
            if parsed:
                structured_data = parsed.data
                page_metadata = parsed.metadata
        except Exception as e:
            logger.debug(f"Failed to parse page directives: {e}")

        # Update link usage
        if destination_hash in self._links:
            self._links[destination_hash].last_used = time.time()

        return PageResponse(
            content=content,
            status=PageStatus.OK,
            destination_hash=destination_hash,
            path=path,
            transfer_time=transfer_time,
            content_length=len(response_data) if isinstance(response_data, bytes) else len(content),
            cache_ttl=cache_ttl,
            structured_data=structured_data,
            page_metadata=page_metadata,
        )

    async def disconnect(self, destination_hash: str) -> bool:
        """Disconnect and remove a cached link.

        Args:
            destination_hash: Hex destination hash to disconnect.

        Returns:
            True if a link was found and torn down.
        """
        entry = self._links.pop(destination_hash, None)
        if entry is None:
            return False

        try:
            entry.link.teardown()
        except Exception as e:
            logger.warning(f"Error tearing down link to {destination_hash[:16]}...: {e}")

        logger.debug(f"Disconnected link to {destination_hash[:16]}...")
        return True

    async def _get_or_create_link(
        self,
        destination_hash: str,
        identity: "RNS.Identity",
    ) -> "RNS.Link | None":
        """Get a cached link or create a new one.

        Args:
            destination_hash: Hex destination hash.
            identity: Recalled RNS.Identity for the destination.

        Returns:
            Active RNS.Link or None if establishment failed.
        """
        import RNS

        # Check for existing active link
        entry = self._links.get(destination_hash)
        if entry is not None and entry.link.status == RNS.Link.ACTIVE:
            entry.last_used = time.time()
            return entry.link

        # Remove stale entry if exists
        if entry is not None:
            try:
                entry.link.teardown()
            except Exception:
                pass
            del self._links[destination_hash]

        # Create new link
        destination = RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            "nomadnetwork",
            "node",
        )

        established_future: asyncio.Future[bool] = asyncio.Future()

        logger.info(f"Creating link to {destination_hash[:16]}... (dest_hash={destination.hash.hex()[:16]})")
        link = RNS.Link(destination)
        logger.info(f"RNS.Link created, status={link.status}, waiting for establishment...")

        def link_established(lnk: "RNS.Link") -> None:
            logger.info(f"Link ESTABLISHED callback fired for {destination_hash[:16]}...")
            if self._event_loop is None:
                logger.warning("No event loop in link_established callback!")
                return
            asyncio.run_coroutine_threadsafe(
                self._resolve_future(established_future, True),
                self._event_loop,
            )

        def link_closed(lnk: "RNS.Link") -> None:
            dest_hash = destination_hash
            logger.info(f"Link CLOSED callback fired for {dest_hash[:16]}... (teardown_reason={getattr(lnk, 'teardown_reason', 'unknown')})")
            self._links.pop(dest_hash, None)
            if self._event_loop is not None and not established_future.done():
                asyncio.run_coroutine_threadsafe(
                    self._resolve_future(established_future, False),
                    self._event_loop,
                )

        link.set_link_established_callback(link_established)
        link.set_link_closed_callback(link_closed)

        # Wait for establishment
        try:
            success = await asyncio.wait_for(
                established_future, timeout=LINK_ESTABLISHMENT_TIMEOUT
            )
        except TimeoutError:
            logger.warning(f"Link establishment timed out for {destination_hash[:16]}...")
            try:
                link.teardown()
            except Exception:
                pass
            return None

        if not success:
            return None

        # Cache the link
        self._links[destination_hash] = _LinkEntry(
            link=link,
            destination_hash=destination_hash,
            established=True,
        )

        logger.debug(f"Link established to {destination_hash[:16]}...")
        return link

    @staticmethod
    async def _resolve_future(future: asyncio.Future, value: object) -> None:
        """Safely resolve a future if not already done."""
        if not future.done():
            future.set_result(value)

    async def _cleanup_loop(self) -> None:
        """Background task to tear down idle links."""
        try:
            while self._started:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._cleanup_idle_links()
        except asyncio.CancelledError:
            pass

    async def _cleanup_idle_links(self) -> None:
        """Tear down links that have been idle beyond the threshold."""
        now = time.time()
        to_remove: list[str] = []

        for dest_hash, entry in self._links.items():
            idle_time = now - entry.last_used
            if idle_time > LINK_IDLE_TIMEOUT:
                to_remove.append(dest_hash)

        for dest_hash in to_remove:
            entry = self._links.pop(dest_hash)
            if entry:
                try:
                    entry.link.teardown()
                    logger.debug(
                        f"Cleaned up idle link to {dest_hash[:16]}... "
                        f"(idle {now - entry.last_used:.0f}s)"
                    )
                except Exception as e:
                    logger.warning(f"Error cleaning up link: {e}")

    @property
    def active_link_count(self) -> int:
        """Number of active cached links."""
        return len(self._links)
