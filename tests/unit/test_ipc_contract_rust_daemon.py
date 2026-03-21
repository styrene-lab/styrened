"""IPC contract tests — Python client against Rust daemon (styrened-rs).

These tests validate that the Python IPC bridge can communicate with the
Rust daemon over the Unix socket IPC protocol. They verify the end-to-end
contract: Python sends request → Rust dispatches → Rust responds → Python
decodes response.

IMPORTANT: These tests require a running styrened-rs IPC server.
Skip with: pytest -m "not rust_daemon"

In CI, the Rust daemon is started as a background process before these tests.
For local development, start it manually:
    cd ~/workspace/styrene-lab/styrene-rs
    cargo run -p styrened-rs --bin reticulumd -- --standalone
"""
import asyncio
import os
import struct
from pathlib import Path

import msgpack
import pytest

from styrened.ipc.protocol import (
    IPCMessageType,
    decode_frame,
    encode_frame,
    generate_request_id,
)

# Socket path — matches Rust default_socket_path()
SOCKET_PATH = Path(os.path.expanduser("~/.styrene/styrened.sock"))

# Skip all tests if socket doesn't exist (no running Rust daemon)
pytestmark = pytest.mark.skipif(
    not SOCKET_PATH.exists(),
    reason="Rust daemon not running (no socket at ~/.styrene/styrened.sock)",
)


async def ipc_roundtrip(
    msg_type: IPCMessageType, payload: dict, timeout: float = 5.0
) -> tuple[int, bytes, dict]:
    """Send a request and read the response over the Unix socket."""
    reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))

    try:
        # Send request
        request_id = generate_request_id()
        frame = encode_frame(msg_type, request_id, payload)
        writer.write(frame)
        await writer.drain()

        # Read response
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout)
        length = struct.unpack(">I", length_bytes)[0]
        body = await asyncio.wait_for(reader.readexactly(length), timeout)

        # Decode
        full_frame = length_bytes + body
        resp_type, resp_id, resp_payload = decode_frame(full_frame)

        return resp_type, resp_id, resp_payload
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.rust_daemon
class TestRustDaemonIPC:
    """Contract tests against a running Rust daemon."""

    @pytest.mark.asyncio
    async def test_ping_pong(self):
        """PING should get PONG response."""
        resp_type, resp_id, resp_payload = await ipc_roundtrip(
            IPCMessageType.PING, {}
        )
        assert resp_type == IPCMessageType.PONG

    @pytest.mark.asyncio
    async def test_query_status(self):
        """QUERY_STATUS should return a RESULT with status data."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_STATUS, {}
        )
        assert resp_type == IPCMessageType.RESULT
        assert "status" in payload or "data" in payload

    @pytest.mark.asyncio
    async def test_query_identity(self):
        """QUERY_IDENTITY should return identity info."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_IDENTITY, {}
        )
        assert resp_type == IPCMessageType.RESULT
        data = payload.get("data", payload)
        assert "identity_hash" in data or "destination_hash" in data

    @pytest.mark.asyncio
    async def test_query_devices(self):
        """QUERY_DEVICES should return a list."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_DEVICES, {"limit": 10}
        )
        assert resp_type == IPCMessageType.RESULT
        data = payload.get("data", payload)
        assert isinstance(data.get("devices", data), (list, dict))

    @pytest.mark.asyncio
    async def test_query_auto_reply(self):
        """QUERY_AUTO_REPLY should return auto-reply config."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_AUTO_REPLY, {}
        )
        assert resp_type == IPCMessageType.RESULT

    @pytest.mark.asyncio
    async def test_query_contacts(self):
        """QUERY_CONTACTS should return contacts list."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_CONTACTS, {}
        )
        assert resp_type == IPCMessageType.RESULT

    @pytest.mark.asyncio
    async def test_query_conversations(self):
        """QUERY_CONVERSATIONS should return conversations list."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_CONVERSATIONS, {"unread_only": False}
        )
        assert resp_type == IPCMessageType.RESULT

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self):
        """Sending an unimplemented type should get an ERROR response."""
        # Use a raw type byte that's valid but unimplemented
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.CMD_PQC_STATUS, {}
        )
        assert resp_type == IPCMessageType.ERROR

    @pytest.mark.asyncio
    async def test_resolve_name_not_found(self):
        """QUERY_RESOLVE_NAME for unknown name should return null peer_hash."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.QUERY_RESOLVE_NAME, {"name": "NonExistentNode12345"}
        )
        assert resp_type == IPCMessageType.RESULT
        data = payload.get("data", payload)
        peer = data.get("peer_hash")
        assert peer is None or peer == ""

    @pytest.mark.asyncio
    async def test_cmd_announce(self):
        """CMD_ANNOUNCE should succeed."""
        resp_type, _, payload = await ipc_roundtrip(
            IPCMessageType.CMD_ANNOUNCE, {}
        )
        assert resp_type == IPCMessageType.RESULT

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Multiple concurrent requests should all get responses."""
        async def ping():
            return await ipc_roundtrip(IPCMessageType.PING, {})

        results = await asyncio.gather(*[ping() for _ in range(5)])
        for resp_type, _, _ in results:
            assert resp_type == IPCMessageType.PONG
