"""Integration tests for STATUS_REQUEST/STATUS_RESPONSE RPC flow.

Tests the status request RPC pattern:
- Client sends STATUS_REQUEST with request_id
- Server responds with STATUS_RESPONSE containing same request_id
- Client correlates response and returns StatusResponse object
"""

import pytest

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_status_request,
    decode_payload,
    encode_payload,
)
from styrened.rpc.messages import StatusResponse


class TestStatusRequestEncoding:
    """Test STATUS_REQUEST wire format encoding without RNS."""

    def test_status_request_creates_valid_envelope(self):
        """STATUS_REQUEST should create envelope with correct type."""
        request = create_status_request()

        assert request.message_type == StyreneMessageType.STATUS_REQUEST
        assert request.request_id is not None
        assert len(request.request_id) == 16

    def test_status_request_wire_roundtrip(self):
        """STATUS_REQUEST should survive encode/decode cycle."""
        request = create_status_request()
        wire_data = request.encode()

        decoded = StyreneEnvelope.decode(wire_data)

        assert decoded.message_type == StyreneMessageType.STATUS_REQUEST
        assert decoded.request_id == request.request_id

    def test_status_request_has_empty_payload(self):
        """STATUS_REQUEST should have empty or minimal payload."""
        request = create_status_request()

        # Status request doesn't need payload - it's a simple "give me status"
        assert request.payload == b"" or len(request.payload) < 10


class TestStatusResponseEncoding:
    """Test STATUS_RESPONSE wire format encoding."""

    def test_status_response_from_dict(self):
        """StatusResponse should deserialize from dict."""
        data = {
            "uptime": 3600,
            "ip": "192.168.1.100",
            "services": ["lxmf", "rns", "rpc"],
            "disk_used": 50000000,
            "disk_total": 100000000,
        }

        response = StatusResponse.from_dict(data)

        assert response.uptime == 3600
        assert response.ip == "192.168.1.100"
        assert response.services == ["lxmf", "rns", "rpc"]
        assert response.disk_used == 50000000
        assert response.disk_total == 100000000

    def test_status_response_to_dict(self):
        """StatusResponse should serialize to dict."""
        response = StatusResponse(
            uptime=7200,
            ip="10.0.0.1",
            services=["styrene"],
            disk_used=25000000,
            disk_total=50000000,
        )

        data = response.to_dict()

        assert data["uptime"] == 7200
        assert data["ip"] == "10.0.0.1"
        assert data["type"] == "status_response"

    def test_status_response_format_uptime(self):
        """StatusResponse should format uptime as human readable."""
        response = StatusResponse(
            uptime=90061,  # 1 day, 1 hour, 1 minute, 1 second
            ip="",
            services=[],
            disk_used=0,
            disk_total=0,
        )

        formatted = response.format_uptime()
        assert "1d" in formatted or "day" in formatted.lower()

    def test_status_response_format_disk_usage(self):
        """StatusResponse should format disk usage as percentage."""
        response = StatusResponse(
            uptime=0,
            ip="",
            services=[],
            disk_used=50000000,
            disk_total=100000000,
        )

        formatted = response.format_disk_usage()
        assert "50" in formatted  # 50% used

    def test_status_response_wire_format(self):
        """STATUS_RESPONSE should encode to valid wire format."""
        response = StatusResponse(
            uptime=3600,
            ip="192.168.1.1",
            services=["test"],
            disk_used=1000,
            disk_total=2000,
        )

        # Encode payload
        payload = encode_payload(response.to_dict())

        # Create envelope with version=2 (required for request_id)
        request_id = b"\x00" * 16  # Placeholder request_id
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=payload,
            request_id=request_id,
        )

        wire_data = envelope.encode()
        decoded = StyreneEnvelope.decode(wire_data)

        assert decoded.message_type == StyreneMessageType.STATUS_RESPONSE
        decoded_data = decode_payload(decoded.payload)
        assert decoded_data["uptime"] == 3600
        assert decoded_data["ip"] == "192.168.1.1"


class TestStatusCorrelation:
    """Test request/response correlation for STATUS RPC."""

    def test_response_correlates_with_request(self):
        """STATUS_RESPONSE should carry same request_id as STATUS_REQUEST."""
        request = create_status_request()
        request_id = request.request_id

        # Simulate server creating response with same request_id
        response_payload = encode_payload(
            {
                "uptime": 1000,
                "ip": "127.0.0.1",
                "services": [],
                "disk_used": 0,
                "disk_total": 0,
            }
        )

        # Note: version=2 is required for request_id support
        response_envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=response_payload,
            request_id=request_id,
        )

        # Verify correlation
        assert response_envelope.request_id == request.request_id

    def test_multiple_concurrent_requests(self):
        """Multiple STATUS_REQUEST should have unique request_ids."""
        requests = [create_status_request() for _ in range(5)]
        request_ids = [r.request_id for r in requests]

        # All should be unique for proper correlation
        assert len(set(request_ids)) == 5


@pytest.mark.requires_rns
class TestStatusRPCWithRNS:
    """Integration tests requiring RNS for actual RPC exchange."""

    @pytest.mark.asyncio
    async def test_status_rpc_full_flow(self, local_rns_config, temp_rns_dir):
        """Test complete STATUS RPC flow over local RNS.

        This test validates:
        1. RPCClient sends STATUS_REQUEST
        2. RPCServer receives and processes request
        3. RPCServer sends STATUS_RESPONSE
        4. RPCClient receives and correlates response
        """
        pytest.skip("Requires full RNS initialization - implement when Hub mode ready")

    @pytest.mark.asyncio
    async def test_status_rpc_timeout(self, local_rns_config, temp_rns_dir):
        """Test STATUS RPC timeout when server doesn't respond."""
        pytest.skip("Requires full RNS initialization - implement when Hub mode ready")
