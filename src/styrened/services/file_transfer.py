"""RNS.Resource-based file transfer for Styrene peers.

Provides full-quality file transfer between Styrene nodes using direct
RNS links, bypassing LXMF payload size constraints. Control plane uses
LXMF Styrene protocol (FILE_OFFER/FILE_ACCEPT), data plane uses
RNS.Resource over an RNS.Link.

Architecture:
    Send: FILE_OFFER via LXMF -> FILE_ACCEPT -> RNS.Link -> RNS.Resource
    Recv: FILE_OFFER handler -> (pending, no auto-accept) -> accept -> Resource -> store

This follows the terminal service pattern for link negotiation,
identity verification, and thread-safe asyncio interaction.
"""
from __future__ import annotations


import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_file_accept,
    create_file_offer,
    decode_payload,
)

if TYPE_CHECKING:
    import RNS

    from styrened.protocols.base import LXMFMessage
    from styrened.protocols.styrene import StyreneProtocol
    from styrened.services.attachment_store import AttachmentStore
    from styrened.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

# Transfer limits
DEFAULT_MAX_TRANSFER_SIZE = 64 * 1024 * 1024  # 64 MB (RNS.Resource limit)
DEFAULT_TRANSFER_TIMEOUT = 300.0  # 5 minutes
MAX_CONCURRENT_TRANSFERS = 4  # Per identity

# Request ID prefix length embedded in RNS.Resource data
_REQUEST_ID_PREFIX_LEN = 16


@dataclass
class PendingTransfer:
    """Tracks a pending file transfer negotiation."""

    request_id: bytes
    peer_hash: str
    filename: str
    size: int
    mime_type: str | None
    checksum: str | None
    created_at: float = field(default_factory=time.time)
    # Set when transfer completes
    completed: bool = False
    result_path: Path | None = None
    error: str | None = None


@dataclass
class OutboundTransfer:
    """Tracks an outbound file transfer in progress."""

    request_id: bytes
    peer_hash: str
    filename: str
    data: bytes
    mime_type: str | None
    on_progress: Callable[[float], None] | None
    created_at: float = field(default_factory=time.time)


class FileTransferService:
    """RNS.Resource-based file transfer for Styrene peers.

    Handles both sending and receiving files between Styrene nodes.
    Uses LXMF Styrene protocol for negotiation and RNS.Resource for
    the actual data transfer.

    FILE_OFFERs from peers are stored as pending — they are NOT
    auto-accepted. A future TUI/API surface can present accept/reject UI.
    """

    def __init__(
        self,
        identity: "RNS.Identity",
        styrene_protocol: "StyreneProtocol",
        attachment_store: "AttachmentStore",
        conversation_service: "ConversationService",
        max_size: int = DEFAULT_MAX_TRANSFER_SIZE,
    ) -> None:
        self._identity = identity
        self._styrene_protocol = styrene_protocol
        self._attachment_store = attachment_store
        self._conversation_service = conversation_service
        self._max_size = max_size

        # Inbound transfer state
        self._pending_inbound: dict[bytes, PendingTransfer] = {}
        self._inbound_destination: Any = None  # RNS.Destination

        # Outbound transfer state
        self._pending_outbound: dict[bytes, OutboundTransfer] = {}

        # Rate limiting per identity
        self._active_transfers: dict[str, int] = {}

        # asyncio.Lock protects mutable state from concurrent access
        self._lock = asyncio.Lock()

        # Captured event loop for thread-safe RNS callbacks
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # Optional callback for activity event emission (set by daemon)
        self._emit_event: Callable[..., None] | None = None

        self._started = False

    def start(self) -> None:
        """Register handlers and create inbound destination."""
        if self._started:
            return

        import RNS

        # Capture event loop for thread-safe RNS callbacks
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Register FILE_OFFER and FILE_ACCEPT handlers with Styrene protocol
        self._styrene_protocol.register_handler(
            StyreneMessageType.FILE_OFFER,
            self._handle_file_offer,
        )
        self._styrene_protocol.register_handler(
            StyreneMessageType.FILE_ACCEPT,
            self._handle_file_accept,
        )

        # Create inbound RNS destination for file transfers
        self._inbound_destination = RNS.Destination(
            self._identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "styrene",
            "filetx",
        )

        # Accept incoming links and resources
        self._inbound_destination.set_link_established_callback(
            self._on_link_established
        )

        self._started = True
        logger.info("FileTransferService started")

    def shutdown(self) -> None:
        """Clean up pending transfers and deregister handlers."""
        self._pending_inbound.clear()
        self._pending_outbound.clear()
        self._active_transfers.clear()

        if self._inbound_destination:
            try:
                self._inbound_destination.deregister()
            except Exception:
                pass
            self._inbound_destination = None

        self._started = False
        logger.info("FileTransferService shutdown")

    async def send_file(
        self,
        peer_hash: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        on_progress: Callable[[float], None] | None = None,
        timeout: float = DEFAULT_TRANSFER_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a file to a Styrene peer via RNS.Resource.

        Negotiates transfer via LXMF FILE_OFFER/ACCEPT, then transfers
        the file data via a direct RNS.Link + RNS.Resource.

        Args:
            peer_hash: LXMF destination hash of the peer.
            file_data: Raw file bytes.
            filename: Filename for the transfer.
            mime_type: Optional MIME type.
            on_progress: Optional callback(fraction_complete).
            timeout: Maximum time for the complete transfer.

        Returns:
            Dict with transfer result: {success, filename, size, checksum}.

        Raises:
            ValueError: If file exceeds max transfer size.
            TimeoutError: If transfer times out.
        """
        if len(file_data) > self._max_size:
            raise ValueError(
                f"File size {len(file_data)} exceeds maximum {self._max_size}"
            )

        async with self._lock:
            # Check rate limit
            active = self._active_transfers.get(peer_hash, 0)
            if active >= MAX_CONCURRENT_TRANSFERS:
                raise RuntimeError(
                    f"Too many concurrent transfers to {peer_hash[:8]} "
                    f"({active}/{MAX_CONCURRENT_TRANSFERS})"
                )
            self._active_transfers[peer_hash] = active + 1

        # Compute checksum
        checksum = hashlib.sha256(file_data).hexdigest()

        # Send FILE_OFFER via LXMF Styrene protocol
        offer = create_file_offer(
            filename=filename,
            size=len(file_data),
            mime_type=mime_type,
            checksum_sha256=checksum,
        )
        request_id = offer.request_id

        # Track outbound transfer
        async with self._lock:
            self._pending_outbound[request_id] = OutboundTransfer(
                request_id=request_id,
                peer_hash=peer_hash,
                filename=filename,
                data=file_data,
                mime_type=mime_type,
                on_progress=on_progress,
            )

        try:
            # Send the offer via async StyreneProtocol API
            await self._styrene_protocol.send_to_identity(peer_hash, offer)

            # Wait for FILE_ACCEPT (or timeout)
            # The actual RNS.Resource transfer is triggered in _handle_file_accept
            start_time = time.time()
            while time.time() - start_time < timeout:
                async with self._lock:
                    outbound = self._pending_outbound.get(request_id)
                if outbound is None:
                    # Transfer completed or was cleaned up
                    break
                await asyncio.sleep(0.5)
            else:
                raise TimeoutError(
                    f"File transfer to {peer_hash[:8]} timed out after {timeout}s"
                )

            return {
                "success": True,
                "filename": filename,
                "size": len(file_data),
                "checksum": checksum,
            }
        finally:
            # Clean up
            async with self._lock:
                self._pending_outbound.pop(request_id, None)
                self._active_transfers[peer_hash] = max(
                    0, self._active_transfers.get(peer_hash, 1) - 1
                )

    _STALE_OFFER_TTL: float = 300.0  # 5 minutes

    async def _cleanup_stale_offers(self) -> None:
        """Remove pending inbound offers older than _STALE_OFFER_TTL seconds."""
        now = time.time()
        async with self._lock:
            stale = [
                rid for rid, pt in self._pending_inbound.items()
                if (now - pt.created_at) > self._STALE_OFFER_TTL
            ]
            for rid in stale:
                pt = self._pending_inbound.pop(rid)
                # Also decrement active transfer count for stale offers
                peer = pt.peer_hash
                self._active_transfers[peer] = max(
                    0, self._active_transfers.get(peer, 1) - 1
                )
                logger.debug(
                    f"Cleaned up stale FILE_OFFER from {peer[:8]}: "
                    f"{pt.filename} (age {now - pt.created_at:.0f}s)"
                )

    async def _handle_file_offer(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle incoming FILE_OFFER from a peer.

        Stores the offer as pending. Does NOT auto-accept — a future
        TUI/API surface can present accept/reject UI.
        """
        await self._cleanup_stale_offers()
        source_hash = message.source_hash

        try:
            payload = decode_payload(envelope.payload)
        except Exception as e:
            logger.warning(f"Invalid FILE_OFFER payload: {e}")
            return

        filename = payload.get("filename", "")
        size = payload.get("size", 0)
        mime_type = payload.get("mime_type")
        checksum = payload.get("checksum")

        if size > self._max_size:
            logger.warning(
                f"FILE_OFFER from {source_hash[:8]} rejected: "
                f"size {size} > max {self._max_size}"
            )
            return

        async with self._lock:
            # Check rate limit
            active = self._active_transfers.get(source_hash, 0)
            if active >= MAX_CONCURRENT_TRANSFERS:
                logger.warning(
                    f"FILE_OFFER from {source_hash[:8]} rejected: rate limited"
                )
                return

            request_id = envelope.request_id or os.urandom(16)

            # Track pending inbound — do NOT auto-accept
            self._pending_inbound[request_id] = PendingTransfer(
                request_id=request_id,
                peer_hash=source_hash,
                filename=filename,
                size=size,
                mime_type=mime_type,
                checksum=checksum,
            )

        logger.info(
            f"FILE_OFFER from {source_hash[:8]} queued (pending acceptance): "
            f"{filename} ({size} bytes)"
        )

        if self._emit_event is not None:
            self._emit_event(
                "file_offer_received",
                peer_hash=source_hash,
                metadata={"filename": filename, "size": size},
            )

    async def accept_transfer(self, request_id: bytes) -> bool:
        """Accept a pending inbound transfer.

        Called by TUI/API when the user approves a file offer.

        Args:
            request_id: The request_id from the pending transfer.

        Returns:
            True if accept was sent, False if transfer not found.
        """
        async with self._lock:
            transfer = self._pending_inbound.get(request_id)
            if transfer is None:
                return False

            active = self._active_transfers.get(transfer.peer_hash, 0)
            self._active_transfers[transfer.peer_hash] = active + 1

        accept = create_file_accept(
            max_size=self._max_size,
            request_id=request_id,
        )
        await self._styrene_protocol.send_to_identity(transfer.peer_hash, accept)

        logger.info(
            f"Accepted FILE_OFFER from {transfer.peer_hash[:8]}: "
            f"{transfer.filename} ({transfer.size} bytes)"
        )
        return True

    async def _handle_file_accept(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle incoming FILE_ACCEPT — initiate outbound RNS.Resource transfer."""
        import RNS

        source_hash = message.source_hash

        try:
            decode_payload(envelope.payload)
        except Exception as e:
            logger.warning(f"Invalid FILE_ACCEPT payload: {e}")
            return

        accept_request_id = envelope.request_id
        if accept_request_id is None:
            logger.warning(f"FILE_ACCEPT from {source_hash[:8]} missing request_id")
            return

        async with self._lock:
            outbound = self._pending_outbound.get(accept_request_id)
            if outbound is None:
                logger.warning(
                    f"FILE_ACCEPT from {source_hash[:8]} for unknown request"
                )
                return

            # Verify the accepting peer is the one we sent the offer to
            if outbound.peer_hash != source_hash:
                logger.warning(
                    f"FILE_ACCEPT peer mismatch: expected {outbound.peer_hash[:8]}, "
                    f"got {source_hash[:8]}. Ignoring."
                )
                return

        logger.info(
            f"FILE_ACCEPT received from {source_hash[:8]}, "
            f"initiating RNS.Resource transfer for {outbound.filename}"
        )

        # Create RNS.Link to the peer's filetx destination and push data
        try:
            # Resolve peer identity
            peer_identity = RNS.Identity.recall(bytes.fromhex(source_hash))
            if peer_identity is None:
                logger.warning(f"Cannot resolve identity for {source_hash[:8]}")
                return

            filetx_dest = RNS.Destination(
                peer_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "styrene",
                "filetx",
            )

            link = RNS.Link(filetx_dest)

            # Embed request_id as prefix in data for receiver-side matching
            prefixed_data = accept_request_id[:_REQUEST_ID_PREFIX_LEN] + outbound.data

            # Wait for link to be established, then push resource
            def _on_link_ready(link: "RNS.Link") -> None:
                try:
                    RNS.Resource(
                        prefixed_data,
                        link,
                        callback=self._on_outbound_resource_concluded,
                    )
                    logger.debug(
                        f"RNS.Resource created for {outbound.filename} "
                        f"({len(outbound.data)} bytes)"
                    )
                except Exception as e:
                    logger.error(f"Failed to create outbound resource: {e}")

            link.set_link_established_callback(_on_link_ready)

        except Exception as e:
            logger.error(f"Failed to initiate outbound transfer: {e}")

    def _on_outbound_resource_concluded(self, resource: "RNS.Resource") -> None:
        """Handle completed outbound resource transfer."""
        import RNS

        if resource.status == RNS.Resource.COMPLETE:
            logger.info("Outbound file transfer resource completed")
        else:
            logger.warning(f"Outbound file transfer resource failed: {resource.status}")

    def _on_link_established(self, link: "RNS.Link") -> None:
        """Handle incoming RNS link for file transfer data plane."""
        import RNS

        link.set_resource_strategy(RNS.Link.ACCEPT_APP)
        link.set_resource_started_callback(self._on_resource_started)
        link.set_resource_concluded_callback(self._on_resource_concluded)
        link.set_resource_callback(self._resource_filter)

        logger.debug(f"File transfer link established from {link}")

    def _resource_filter(self, resource: "RNS.Resource") -> bool:
        """Filter incoming resources: only accept if a matching pending transfer exists.

        Called from RNS thread when ACCEPT_APP strategy is set.
        Returns True to accept, False to reject.
        """
        # Check advertised size against our max_size limit (C4 defense-in-depth)
        try:
            advertised_size = resource.total_size
            if advertised_size is not None and advertised_size > self._max_size:
                logger.warning(
                    f"Rejecting resource: advertised size {advertised_size} "
                    f"exceeds max {self._max_size}"
                )
                return False
        except AttributeError:
            pass  # total_size may not be available at filter time

        # Accept only if we have any pending inbound transfers
        if self._pending_inbound:
            return True

        logger.warning("Rejecting resource: no pending inbound transfers")
        return False

    def _on_resource_started(self, resource: "RNS.Resource") -> None:
        """Handle incoming resource transfer start."""
        logger.debug(f"File transfer resource started: {resource}")

    def _on_resource_concluded(self, resource: "RNS.Resource") -> None:
        """Handle completed inbound resource transfer.

        Called from RNS thread — schedules async work on the event loop.
        """
        if self._event_loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._process_inbound_resource(resource),
                self._event_loop,
            )
        else:
            logger.warning("No event loop for inbound resource processing")

    async def _process_inbound_resource(self, resource: "RNS.Resource") -> None:
        """Process a completed inbound resource transfer (async, thread-safe)."""
        import RNS

        if resource.status != RNS.Resource.COMPLETE:
            logger.warning(f"File transfer resource failed: {resource.status}")
            return

        # Validate resource size before reading data into memory
        try:
            resource_size = resource.total_size
            if resource_size is not None and resource_size > self._max_size:
                logger.warning(
                    f"Rejecting completed resource: size {resource_size} "
                    f"exceeds max {self._max_size}"
                )
                return
        except AttributeError:
            pass  # total_size may not be available

        data = resource.data.read()
        if data is None or len(data) < _REQUEST_ID_PREFIX_LEN:
            logger.warning("File transfer resource had no data or missing request_id prefix")
            return

        if len(data) > self._max_size + _REQUEST_ID_PREFIX_LEN:
            logger.warning(
                f"Rejecting resource data: {len(data)} bytes exceeds "
                f"max {self._max_size} + prefix"
            )
            return

        # Extract request_id prefix for matching
        resource_request_id = data[:_REQUEST_ID_PREFIX_LEN]
        file_data = data[_REQUEST_ID_PREFIX_LEN:]

        async with self._lock:
            matching = self._pending_inbound.get(resource_request_id)

        if matching is None:
            logger.warning(
                f"Received file data ({len(file_data)} bytes) with no matching transfer "
                f"(request_id={resource_request_id.hex()[:16]})"
            )
            return

        # Verify checksum if provided
        if matching.checksum:
            actual = hashlib.sha256(file_data).hexdigest()
            if actual != matching.checksum:
                logger.warning(
                    f"Checksum mismatch for {matching.filename}: "
                    f"expected {matching.checksum[:16]}..., got {actual[:16]}..."
                )
                matching.error = "checksum mismatch"
                return

        # Save to attachment store
        try:
            path = self._attachment_store.save(
                matching.peer_hash,
                0,
                matching.filename,
                file_data,
                mime=matching.mime_type,
            )
            matching.result_path = path
            matching.completed = True

            logger.info(
                f"File transfer complete: {matching.filename} "
                f"({len(file_data)} bytes) from {matching.peer_hash[:8]}"
            )

            if self._emit_event is not None:
                self._emit_event(
                    "file_transfer_complete",
                    peer_hash=matching.peer_hash,
                    metadata={"filename": matching.filename, "size": len(file_data)},
                )
        except Exception as e:
            logger.error(f"Failed to save transferred file: {e}")
            matching.error = str(e)
        finally:
            # Clean up active count
            async with self._lock:
                peer = matching.peer_hash
                self._active_transfers[peer] = max(
                    0, self._active_transfers.get(peer, 1) - 1
                )
                self._pending_inbound.pop(matching.request_id, None)
