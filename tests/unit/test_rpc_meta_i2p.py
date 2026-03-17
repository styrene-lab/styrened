"""Unit tests for _gather_meta() I2P integration."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from styrened.rpc.server import RPCServer


@pytest.fixture
def mock_protocol() -> MagicMock:
    mock = MagicMock()
    mock.register_handler = MagicMock()
    return mock


@pytest.fixture
def server(mock_protocol: MagicMock) -> RPCServer:
    return RPCServer(styrene_protocol=mock_protocol)


def _make_i2p_adapter(b32_address: str | None, proxy_port: int = 4445) -> MagicMock:
    adapter = MagicMock()
    adapter.get_b32_address.return_value = b32_address
    adapter.status.return_value.details = {
        "b32_address": b32_address,
        "proxy_port": proxy_port,
    }
    return adapter


class TestGatherMetaI2P:
    def test_no_i2p_keys_when_adapter_absent(self, server: RPCServer) -> None:
        meta = server._gather_meta()
        assert "b32_address" not in meta
        assert "i2p" not in meta["capabilities"]

    def test_b32_address_present_when_known(self, server: RPCServer) -> None:
        server.set_i2p_adapter(_make_i2p_adapter("deadbeef.b32.i2p"))
        meta = server._gather_meta()
        assert meta["b32_address"] == "deadbeef.b32.i2p"

    def test_i2p_capability_present_when_b32_known(self, server: RPCServer) -> None:
        server.set_i2p_adapter(_make_i2p_adapter("deadbeef.b32.i2p"))
        meta = server._gather_meta()
        assert "i2p" in meta["capabilities"]

    def test_i2p_keys_omitted_when_address_unknown(self, server: RPCServer) -> None:
        server.set_i2p_adapter(_make_i2p_adapter(None))
        meta = server._gather_meta()
        assert "b32_address" not in meta
        assert "i2p" not in meta["capabilities"]

    def test_i2p_adapter_exception_is_ignored(self, server: RPCServer) -> None:
        adapter = MagicMock()
        adapter.get_b32_address.side_effect = RuntimeError("boom")
        adapter.status.side_effect = RuntimeError("boom")
        server.set_i2p_adapter(adapter)
        meta = server._gather_meta()
        assert "b32_address" not in meta
        assert "i2p" not in meta["capabilities"]
