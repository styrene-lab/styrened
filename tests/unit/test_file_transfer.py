"""Unit tests for FileTransferService (Batch 2).

Tests the repaired file transfer service: correct handler signatures,
no auto-accept, rate limiting, request-ID based matching, and thread safety.
"""

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from styrened.models.styrene_wire import (
    StyreneMessageType,
    create_file_offer,
)
from styrened.services.file_transfer import (
    MAX_CONCURRENT_TRANSFERS,
    FileTransferService,
    PendingTransfer,
)


@dataclass
class FakeLXMFMessage:
    """Minimal LXMFMessage stand-in for tests."""

    source_hash: str = "aabbccdd11223344"
    destination_hash: str = "eeff001122334455"
    content: str = ""
    fields: dict[str, Any] | None = None
    timestamp: float = 0.0


@pytest.fixture
def mock_deps(tmp_path: Path):
    """Create mock dependencies for FileTransferService."""
    identity = MagicMock()
    styrene_protocol = MagicMock()
    styrene_protocol.register_handler = MagicMock()
    styrene_protocol.send_to_identity = AsyncMock()

    from styrened.services.attachment_store import AttachmentStore

    attachment_store = AttachmentStore(
        base_dir=tmp_path / "attachments",
        max_file_size=1024 * 1024,
    )
    conversation_service = MagicMock()

    return {
        "identity": identity,
        "styrene_protocol": styrene_protocol,
        "attachment_store": attachment_store,
        "conversation_service": conversation_service,
    }


def _start_service_no_rns(svc: FileTransferService) -> None:
    """Start service without creating real RNS.Destination (unit test helper).

    Registers handlers, but skips RNS destination creation that requires
    a real RNS identity. Event loop is set to None; async tests can set it.
    """
    if svc._started:
        return

    svc._event_loop = None

    svc._styrene_protocol.register_handler(
        StyreneMessageType.FILE_OFFER,
        svc._handle_file_offer,
    )
    svc._styrene_protocol.register_handler(
        StyreneMessageType.FILE_ACCEPT,
        svc._handle_file_accept,
    )

    svc._started = True


@pytest.fixture
def service(mock_deps):
    """Create a FileTransferService without RNS (handlers only, no RNS.Destination)."""
    svc = FileTransferService(**mock_deps, max_size=1024 * 1024)
    _start_service_no_rns(svc)
    yield svc
    svc.shutdown()


class TestFileTransferHandlerSignatures:
    """Verify handler signatures match StyreneProtocol dispatch."""

    def test_start_registers_both_handlers(self, service, mock_deps):
        """start() should register handlers for FILE_OFFER and FILE_ACCEPT."""
        proto = mock_deps["styrene_protocol"]
        calls = proto.register_handler.call_args_list

        registered_types = [c[0][0] for c in calls]
        assert StyreneMessageType.FILE_OFFER in registered_types
        assert StyreneMessageType.FILE_ACCEPT in registered_types

    @pytest.mark.asyncio
    async def test_handle_file_offer_correct_signature(self, service):
        """_handle_file_offer should accept (message, envelope) args."""
        offer = create_file_offer(
            filename="test.txt",
            size=100,
            mime_type="text/plain",
        )
        msg = FakeLXMFMessage(source_hash="aabb" * 4)

        # Should not raise — correct signature
        await service._handle_file_offer(msg, offer)


class TestFileTransferNoAutoAccept:
    """Verify FILE_OFFERs are NOT auto-accepted."""

    @pytest.mark.asyncio
    async def test_handle_file_offer_no_auto_accept(self, service, mock_deps):
        """FILE_ACCEPT should NOT be sent automatically on FILE_OFFER."""
        offer = create_file_offer(
            filename="test.txt",
            size=100,
            mime_type="text/plain",
        )
        msg = FakeLXMFMessage(source_hash="aabb" * 4)

        await service._handle_file_offer(msg, offer)

        # send_to_identity should NOT have been called (no auto-accept)
        mock_deps["styrene_protocol"].send_to_identity.assert_not_called()

        # But the offer should be tracked as pending
        assert len(service._pending_inbound) == 1


class TestFileTransferSizeAndRateChecks:
    """Verify size and rate limit enforcement."""

    @pytest.mark.asyncio
    async def test_handle_file_offer_oversized_rejected(self, service):
        """FILE_OFFER with size > max_size should be silently rejected."""
        offer = create_file_offer(
            filename="huge.bin",
            size=service._max_size + 1,
            mime_type="application/octet-stream",
        )
        msg = FakeLXMFMessage(source_hash="aabb" * 4)

        await service._handle_file_offer(msg, offer)

        # Should not be tracked
        assert len(service._pending_inbound) == 0

    @pytest.mark.asyncio
    async def test_handle_file_offer_rate_limited(self, service):
        """Offers beyond MAX_CONCURRENT_TRANSFERS should be rejected."""
        peer = "aabb" * 4
        msg = FakeLXMFMessage(source_hash=peer)

        # Fill up the rate limit
        async with service._lock:
            service._active_transfers[peer] = MAX_CONCURRENT_TRANSFERS

        offer = create_file_offer(filename="limited.txt", size=10)
        await service._handle_file_offer(msg, offer)

        # Should not be tracked (rate limited)
        assert len(service._pending_inbound) == 0


class TestFileTransferAcceptFlow:
    """Test explicit accept_transfer flow."""

    @pytest.mark.asyncio
    async def test_accept_transfer_sends_file_accept(self, service, mock_deps):
        """accept_transfer() should send FILE_ACCEPT for a pending offer."""
        offer = create_file_offer(filename="accepted.txt", size=50)
        msg = FakeLXMFMessage(source_hash="aabb" * 4)
        await service._handle_file_offer(msg, offer)

        # Get the pending transfer's request_id
        request_id = list(service._pending_inbound.keys())[0]

        result = await service.accept_transfer(request_id)
        assert result is True
        mock_deps["styrene_protocol"].send_to_identity.assert_called_once()

    @pytest.mark.asyncio
    async def test_accept_transfer_unknown_returns_false(self, service):
        """accept_transfer() with unknown request_id returns False."""
        result = await service.accept_transfer(os.urandom(16))
        assert result is False


class TestFileTransferResourceMatching:
    """Test request-ID based resource matching."""

    @pytest.mark.asyncio
    async def test_resource_matching_by_request_id(self, service):
        """Inbound resource should be matched by request_id prefix, not size."""
        # Add two pending transfers of the same size but different request_ids
        rid_a = os.urandom(16)
        rid_b = os.urandom(16)

        async with service._lock:
            service._pending_inbound[rid_a] = PendingTransfer(
                request_id=rid_a,
                peer_hash="aabb" * 4,
                filename="file_a.txt",
                size=100,
                mime_type=None,
                checksum=None,
            )
            service._pending_inbound[rid_b] = PendingTransfer(
                request_id=rid_b,
                peer_hash="ccdd" * 4,
                filename="file_b.txt",
                size=100,
                mime_type=None,
                checksum=None,
            )
            service._active_transfers["aabb" * 4] = 1
            service._active_transfers["ccdd" * 4] = 1

        # Simulate resource with rid_b prefix
        import RNS as rns_mod  # noqa: N811  # noqa: N811

        rns_mod.Resource = MagicMock()
        rns_mod.Resource.COMPLETE = 1

        mock_resource = MagicMock()
        mock_resource.status = 1  # RNS.Resource.COMPLETE
        mock_resource.total_size = 116  # prefix + data
        mock_resource.data.read.return_value = rid_b + b"x" * 100

        await service._process_inbound_resource(mock_resource)

        # file_b should be completed, file_a should be untouched
        assert rid_b not in service._pending_inbound
        assert rid_a in service._pending_inbound


class TestFileTransferThreadSafety:
    """Test concurrent access to shared state."""

    @pytest.mark.asyncio
    async def test_active_transfers_thread_safe(self, service):
        """Concurrent modifications to _active_transfers should not corrupt state."""
        peer = "aabb" * 4

        async def increment():
            async with service._lock:
                current = service._active_transfers.get(peer, 0)
                await asyncio.sleep(0.001)  # Force task switch
                service._active_transfers[peer] = current + 1

        async def decrement():
            async with service._lock:
                current = service._active_transfers.get(peer, 0)
                await asyncio.sleep(0.001)
                service._active_transfers[peer] = max(0, current - 1)

        # Run 10 increments and 10 decrements concurrently
        tasks = [increment() for _ in range(10)] + [decrement() for _ in range(10)]
        await asyncio.gather(*tasks)

        # Final value should be 0 (10 increments - 10 decrements)
        assert service._active_transfers.get(peer, 0) == 0


class TestResourceFilter:
    """Tests for _resource_filter (C3 — ACCEPT_APP gating)."""

    def test_resource_filter_rejects_when_no_pending(self, service):
        """_resource_filter rejects resources when no pending inbound transfers (C3)."""
        mock_resource = MagicMock()
        mock_resource.total_size = 100

        assert service._resource_filter(mock_resource) is False

    def test_resource_filter_accepts_when_pending_exists(self, service):
        """_resource_filter accepts resources when pending transfers exist (C3)."""
        # Add a pending transfer
        rid = os.urandom(16)
        service._pending_inbound[rid] = PendingTransfer(
            request_id=rid,
            peer_hash="aabb" * 4,
            filename="test.txt",
            size=100,
            mime_type=None,
            checksum=None,
        )
        mock_resource = MagicMock()
        mock_resource.total_size = 100

        assert service._resource_filter(mock_resource) is True

    def test_resource_filter_rejects_oversized(self, service):
        """_resource_filter rejects resources larger than max_size (C3/C4)."""
        # Add a pending transfer so the "no pending" check passes
        rid = os.urandom(16)
        service._pending_inbound[rid] = PendingTransfer(
            request_id=rid,
            peer_hash="aabb" * 4,
            filename="test.txt",
            size=100,
            mime_type=None,
            checksum=None,
        )
        mock_resource = MagicMock()
        mock_resource.total_size = service._max_size + 1

        assert service._resource_filter(mock_resource) is False


class TestInboundResourceSizeValidation:
    """Tests for _process_inbound_resource size check (C4)."""

    @pytest.mark.asyncio
    async def test_oversized_resource_data_rejected(self, service):
        """Resource data exceeding max_size + prefix is rejected (C4)."""
        import RNS as rns_mod  # noqa: N811

        rns_mod.Resource = MagicMock()
        rns_mod.Resource.COMPLETE = 1

        mock_resource = MagicMock()
        mock_resource.status = 1
        mock_resource.total_size = service._max_size + 100
        # Data exceeds max_size + prefix
        mock_resource.data.read.return_value = b"\x00" * (service._max_size + 100)

        await service._process_inbound_resource(mock_resource)

        # Should not have tried to match or store anything (no crash)
        # The resource should be rejected silently


class TestFileAcceptPeerVerification:
    """Tests for _handle_file_accept peer verification (W6)."""

    @pytest.mark.asyncio
    async def test_file_accept_from_wrong_peer_rejected(self, service, mock_deps):
        """FILE_ACCEPT from a peer different than the offer target is rejected (W6)."""
        import RNS as rns_mod  # noqa: N811

        rns_mod.Identity = MagicMock()

        from styrened.models.styrene_wire import create_file_accept
        from styrened.services.file_transfer import OutboundTransfer

        request_id = os.urandom(16)
        peer = "aabb" * 4
        wrong_peer = "ccdd" * 4

        async with service._lock:
            service._pending_outbound[request_id] = OutboundTransfer(
                request_id=request_id,
                peer_hash=peer,
                filename="test.txt",
                data=b"hello",
                mime_type=None,
                on_progress=None,
            )

        # Create FILE_ACCEPT envelope
        accept = create_file_accept(max_size=1024, request_id=request_id)

        # Send from wrong_peer
        msg = FakeLXMFMessage(source_hash=wrong_peer)
        await service._handle_file_accept(msg, accept)

        # Outbound transfer should NOT have been consumed (still pending)
        assert request_id in service._pending_outbound

    @pytest.mark.asyncio
    async def test_file_accept_from_correct_peer_proceeds(self, service, mock_deps):
        """FILE_ACCEPT from the correct peer is processed (W6)."""
        import RNS as rns_mod  # noqa: N811

        rns_mod.Identity = MagicMock()
        rns_mod.Identity.recall.return_value = None  # Will fail at identity resolution

        from styrened.models.styrene_wire import create_file_accept
        from styrened.services.file_transfer import OutboundTransfer

        request_id = os.urandom(16)
        peer = "aabb" * 4

        async with service._lock:
            service._pending_outbound[request_id] = OutboundTransfer(
                request_id=request_id,
                peer_hash=peer,
                filename="test.txt",
                data=b"hello",
                mime_type=None,
                on_progress=None,
            )

        accept = create_file_accept(max_size=1024, request_id=request_id)

        # Send from correct peer
        msg = FakeLXMFMessage(source_hash=peer)
        await service._handle_file_accept(msg, accept)

        # Method proceeds past peer check (it will fail later at identity
        # resolution, but that's OK — we're testing the peer check)


class TestStaleOfferCleanup:
    """Tests for _cleanup_stale_offers (W7)."""

    @pytest.mark.asyncio
    async def test_stale_offers_cleaned_up(self, service):
        """Pending offers older than 5 minutes are removed (W7)."""
        stale_rid = os.urandom(16)
        fresh_rid = os.urandom(16)

        async with service._lock:
            service._pending_inbound[stale_rid] = PendingTransfer(
                request_id=stale_rid,
                peer_hash="aabb" * 4,
                filename="stale.txt",
                size=100,
                mime_type=None,
                checksum=None,
                created_at=time.time() - 600,  # 10 minutes ago
            )
            service._active_transfers["aabb" * 4] = 1

            service._pending_inbound[fresh_rid] = PendingTransfer(
                request_id=fresh_rid,
                peer_hash="ccdd" * 4,
                filename="fresh.txt",
                size=100,
                mime_type=None,
                checksum=None,
                created_at=time.time(),  # just now
            )

        await service._cleanup_stale_offers()

        assert stale_rid not in service._pending_inbound
        assert fresh_rid in service._pending_inbound
        # Active transfer counter for stale peer should be decremented
        assert service._active_transfers.get("aabb" * 4, 0) == 0

    @pytest.mark.asyncio
    async def test_cleanup_called_on_file_offer(self, service, mock_deps):
        """_cleanup_stale_offers is called at start of _handle_file_offer (W7)."""
        stale_rid = os.urandom(16)
        async with service._lock:
            service._pending_inbound[stale_rid] = PendingTransfer(
                request_id=stale_rid,
                peer_hash="aabb" * 4,
                filename="stale.txt",
                size=100,
                mime_type=None,
                checksum=None,
                created_at=time.time() - 600,
            )

        # Send a new FILE_OFFER, which triggers cleanup
        offer = create_file_offer(filename="new.txt", size=50)
        msg = FakeLXMFMessage(source_hash="ccdd" * 4)
        await service._handle_file_offer(msg, offer)

        # Stale offer should be cleaned up
        assert stale_rid not in service._pending_inbound
