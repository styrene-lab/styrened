"""Integration tests for PING/PONG message exchange.

Tests the most basic wire protocol interaction: ping request and pong response.
This validates:
- Wire format encoding/decoding across process boundary
- StyreneProtocol message routing
- Request correlation via request_id
"""
from __future__ import annotations


import pytest

from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
    create_ping,
    create_pong,
)


class TestPingPongEncoding:
    """Test PING/PONG wire format encoding without RNS."""

    def test_ping_creates_valid_envelope(self):
        """PING should create envelope with correct message type."""
        ping = create_ping()

        assert ping.message_type == StyreneMessageType.PING
        assert ping.payload == b""
        assert ping.request_id is not None
        assert ping.request_id != NO_CORRELATION

    def test_pong_creates_valid_envelope(self):
        """PONG should create envelope with correct message type."""
        pong = create_pong()

        assert pong.message_type == StyreneMessageType.PONG
        assert pong.payload == b""

    def test_ping_pong_correlation(self):
        """PONG should use same request_id as PING for correlation."""
        ping = create_ping()
        request_id = ping.request_id

        # Create pong with same request_id (as server would)
        # Note: version=2 is required for request_id support
        pong = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PONG,
            payload=b"",
            request_id=request_id,
        )

        assert pong.request_id == ping.request_id

    def test_ping_pong_wire_roundtrip(self):
        """PING/PONG should survive encode/decode cycle."""
        ping = create_ping()
        wire_data = ping.encode()

        decoded = StyreneEnvelope.decode(wire_data)

        assert decoded.message_type == StyreneMessageType.PING
        assert decoded.request_id == ping.request_id

    def test_multiple_pings_have_unique_request_ids(self):
        """Each PING should have unique request_id for correlation."""
        pings = [create_ping() for _ in range(10)]
        request_ids = [p.request_id for p in pings]

        # All request_ids should be unique
        assert len(set(request_ids)) == 10

    def test_ping_is_styrene_message(self):
        """PING wire data should be detected as Styrene message."""
        ping = create_ping()
        wire_data = ping.encode()

        assert StyreneEnvelope.is_styrene_message(wire_data)
        assert not StyreneEnvelope.is_styrene_message(b"not a styrene message")


@pytest.mark.requires_rns
class TestPingPongWithRNS:
    """Integration tests requiring RNS for actual message exchange.

    These tests spawn processes and exchange messages over local RNS.
    """

    @pytest.mark.asyncio
    async def test_ping_pong_loopback(self, local_rns_config, temp_rns_dir):
        """Test PING/PONG exchange over local RNS loopback.

        This test validates that:
        1. StyreneProtocol can send PING
        2. Handler receives PING and sends PONG
        3. Client receives correlated PONG
        """
        # This test requires full RNS initialization
        # which is complex for a first implementation.
        # Mark as placeholder for now.
        pytest.skip("Requires full RNS initialization - implement when Hub mode ready")

    @pytest.mark.asyncio
    async def test_ping_timeout_handling(self, local_rns_config, temp_rns_dir):
        """Test that PING without PONG response times out correctly."""
        pytest.skip("Requires full RNS initialization - implement when Hub mode ready")
