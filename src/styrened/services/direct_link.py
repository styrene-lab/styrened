"""Direct data link service for persistent RNS.Link connections.

Manages outgoing RNS.Links to Styrene peers via the ("styrene", "datalink")
destination aspect.  Links are persistent, cached, and automatically
renegotiated on path changes.

This is the initialization point for the direct-highest-bandwidth-datalink
mesh system — providing low-latency request/response that bypasses LXMF
store-and-forward overhead.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import RNS

logger = logging.getLogger(__name__)

# Timeouts
PATH_DISCOVERY_TIMEOUT = 15.0
LINK_ESTABLISHMENT_TIMEOUT = 15.0
REQUEST_TIMEOUT = 10.0
CLEANUP_INTERVAL = 60.0
IDLE_LINK_TIMEOUT = 300.0  # 5 min idle before teardown

# Destination aspect for Styrene direct data links
DATALINK_APP = "styrene"
DATALINK_ASPECT = "datalink"


@dataclass
class LinkInfo:
    """Public link status information."""

    destination_hash: str
    status: str  # "active", "establishing", "closed", "failed", "path_not_found", "identity_unknown"
    rtt: float | None = None  # seconds (from RNS)
    established_at: float | None = None
    last_activity: float | None = None


@dataclass
class _LinkEntry:
    """Internal link tracking."""

    link: "RNS.Link"
    destination_hash: str  # keyed by LXMF dest hash (user-facing ID)
    datalink_hash: str  # the ("styrene","datalink") destination hash
    established: bool = False
    established_at: float | None = None
    last_used: float = field(default_factory=time.time)


class DirectLinkService:
    """Manages persistent outgoing RNS.Links to Styrene peers.

    Links target the ("styrene", "datalink") destination aspect
    registered on remote daemons.  Peers are identified by their
    LXMF destination hash (the user-visible identity).
    """

    def __init__(self) -> None:
        self._links: dict[str, _LinkEntry] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._started = False
        self._force_path_rediscovery = False

    async def start(self) -> None:
        """Start the service and background cleanup task."""
        if self._started:
            return
        self._event_loop = asyncio.get_running_loop()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._started = True
        logger.info("DirectLinkService started")

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
        for entry in list(self._links.values()):
            try:
                entry.link.teardown()
            except Exception:
                pass
        self._links.clear()
        logger.info("DirectLinkService stopped")

    def handle_reconnection(self) -> None:
        """Flag path re-discovery on network reconnection."""
        self._force_path_rediscovery = True
        logger.info("[RECONNECT] DirectLinkService flagged for path re-discovery")

    async def establish(self, lxmf_destination_hash: str) -> LinkInfo:
        """Establish or retrieve a direct link to a Styrene peer.

        Args:
            lxmf_destination_hash: Peer's LXMF destination hash (hex).

        Returns:
            LinkInfo with current status.
        """
        import RNS

        # Check existing active link
        entry = self._links.get(lxmf_destination_hash)
        if entry is not None and entry.link.status == RNS.Link.ACTIVE:
            entry.last_used = time.time()
            return self._entry_to_info(entry)

        # Remove stale entry
        if entry is not None:
            try:
                entry.link.teardown()
            except Exception:
                pass
            self._links.pop(lxmf_destination_hash, None)

        # Recall identity from the LXMF destination hash
        dest_hash_bytes = bytes.fromhex(lxmf_destination_hash)

        # Ensure path exists for identity recall
        if self._force_path_rediscovery or not RNS.Transport.has_path(dest_hash_bytes):
            self._force_path_rediscovery = False
            RNS.Transport.request_path(dest_hash_bytes)
            start = time.time()
            while not RNS.Transport.has_path(dest_hash_bytes):
                if time.time() - start > PATH_DISCOVERY_TIMEOUT:
                    return LinkInfo(
                        destination_hash=lxmf_destination_hash,
                        status="path_not_found",
                    )
                await asyncio.sleep(0.2)

        identity = RNS.Identity.recall(dest_hash_bytes)
        if identity is None:
            return LinkInfo(
                destination_hash=lxmf_destination_hash,
                status="identity_unknown",
            )

        # Compute the datalink destination (different hash from LXMF dest)
        datalink_dest = RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            DATALINK_APP,
            DATALINK_ASPECT,
        )
        datalink_hash = datalink_dest.hash.hex()

        # Request path to datalink destination (may differ from LXMF path)
        if not RNS.Transport.has_path(datalink_dest.hash):
            RNS.Transport.request_path(datalink_dest.hash)
            start = time.time()
            while not RNS.Transport.has_path(datalink_dest.hash):
                if time.time() - start > PATH_DISCOVERY_TIMEOUT:
                    return LinkInfo(
                        destination_hash=lxmf_destination_hash,
                        status="path_not_found",
                    )
                await asyncio.sleep(0.2)

        # Create link
        link = await self._create_link(lxmf_destination_hash, datalink_dest, datalink_hash)
        if link is None:
            return LinkInfo(
                destination_hash=lxmf_destination_hash,
                status="failed",
            )

        entry = self._links.get(lxmf_destination_hash)
        if entry:
            return self._entry_to_info(entry)
        return LinkInfo(destination_hash=lxmf_destination_hash, status="failed")

    async def teardown(self, lxmf_destination_hash: str) -> bool:
        """Tear down a link to a peer."""
        entry = self._links.pop(lxmf_destination_hash, None)
        if entry is None:
            return False
        try:
            entry.link.teardown()
        except Exception:
            pass
        logger.info(f"Datalink torn down to {lxmf_destination_hash[:16]}...")
        return True

    async def request_status(
        self,
        lxmf_destination_hash: str,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Request status from peer over direct link.

        Returns:
            Status dict or None if link not active / request failed.
        """
        import RNS

        entry = self._links.get(lxmf_destination_hash)
        if not entry or entry.link.status != RNS.Link.ACTIVE:
            return None

        entry.last_used = time.time()
        response_future: asyncio.Future[bytes | None] = asyncio.Future()

        def on_response(receipt: Any) -> None:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, receipt.response),
                    self._event_loop,
                )

        def on_failed(receipt: Any) -> None:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, None),
                    self._event_loop,
                )

        try:
            entry.link.request(
                "/status",
                data=None,
                response_callback=on_response,
                failed_callback=on_failed,
            )
        except Exception as e:
            logger.error(f"Failed to send /status over datalink: {e}")
            return None

        try:
            data = await asyncio.wait_for(response_future, timeout=timeout)
            if data:
                return json.loads(data)
        except TimeoutError:
            logger.warning(f"Datalink /status timed out for {lxmf_destination_hash[:16]}...")
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Datalink /status decode error: {e}")
        return None

    def get_link_info(self, lxmf_destination_hash: str) -> LinkInfo | None:
        """Get link info for a peer, or None if no link."""
        entry = self._links.get(lxmf_destination_hash)
        if entry is None:
            return None
        return self._entry_to_info(entry)

    def get_all_links(self) -> list[LinkInfo]:
        """Get info for all managed links."""
        return [self._entry_to_info(e) for e in self._links.values()]

    def _entry_to_info(self, entry: _LinkEntry) -> LinkInfo:
        """Convert internal entry to public LinkInfo."""
        import RNS

        status_map = {
            RNS.Link.ACTIVE: "active",
            RNS.Link.PENDING: "establishing",
            RNS.Link.CLOSED: "closed",
        }
        status = status_map.get(entry.link.status, "unknown")
        rtt = None
        try:
            rtt = entry.link.rtt
        except Exception:
            pass
        return LinkInfo(
            destination_hash=entry.destination_hash,
            status=status,
            rtt=rtt,
            established_at=entry.established_at,
            last_activity=entry.last_used,
        )

    async def _create_link(
        self,
        lxmf_destination_hash: str,
        datalink_dest: "RNS.Destination",
        datalink_hash: str,
    ) -> "RNS.Link | None":
        """Create and cache a new RNS.Link."""
        import RNS

        established_future: asyncio.Future[bool] = asyncio.Future()

        logger.info(
            f"Creating datalink to {lxmf_destination_hash[:16]}... "
            f"(datalink_hash={datalink_hash[:16]}...)"
        )
        link = RNS.Link(datalink_dest)

        def on_established(lnk: "RNS.Link") -> None:
            logger.info(f"Datalink ESTABLISHED to {lxmf_destination_hash[:16]}...")
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(established_future, True),
                    self._event_loop,
                )

        def on_closed(lnk: "RNS.Link") -> None:
            logger.info(f"Datalink CLOSED to {lxmf_destination_hash[:16]}...")
            self._links.pop(lxmf_destination_hash, None)
            if self._event_loop and not established_future.done():
                asyncio.run_coroutine_threadsafe(
                    _resolve(established_future, False),
                    self._event_loop,
                )

        link.set_link_established_callback(on_established)
        link.set_link_closed_callback(on_closed)

        try:
            success = await asyncio.wait_for(
                established_future, timeout=LINK_ESTABLISHMENT_TIMEOUT
            )
        except TimeoutError:
            logger.warning(f"Datalink establishment timed out for {lxmf_destination_hash[:16]}...")
            try:
                link.teardown()
            except Exception:
                pass
            return None

        if not success:
            return None

        now = time.time()
        self._links[lxmf_destination_hash] = _LinkEntry(
            link=link,
            destination_hash=lxmf_destination_hash,
            datalink_hash=datalink_hash,
            established=True,
            established_at=now,
            last_used=now,
        )
        return link

    async def _cleanup_loop(self) -> None:
        """Background task to tear down idle links."""
        try:
            while self._started:
                await asyncio.sleep(CLEANUP_INTERVAL)
                now = time.time()
                stale = [
                    dh
                    for dh, entry in self._links.items()
                    if now - entry.last_used > IDLE_LINK_TIMEOUT
                ]
                for dh in stale:
                    entry = self._links.pop(dh, None)
                    if entry:
                        try:
                            entry.link.teardown()
                        except Exception:
                            pass
                        logger.debug(f"Cleaned up idle datalink to {dh[:16]}...")
        except asyncio.CancelledError:
            pass


async def _resolve(future: asyncio.Future, value: object) -> None:
    """Safely resolve a future if not already done."""
    if not future.done():
        future.set_result(value)
