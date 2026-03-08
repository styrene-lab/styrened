"""Unit tests for _gather_meta() Yggdrasil integration.

Verifies that ygg_address and ygg_port are:
  - present in the response when YggdrasilAdapter is running
  - absent entirely (not None) when the adapter is absent or not running
  - that the 'yggdrasil' capability string is only present when running
"""

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


def _make_ygg_adapter(address: str | None, listen_port: int = 9002) -> MagicMock:
    adapter = MagicMock()
    adapter.get_local_address.return_value = address
    cfg = MagicMock()
    cfg.listen_port = listen_port
    adapter._config = cfg
    return adapter


class TestGatherMetaNoYgg:
    """_gather_meta without YggdrasilAdapter injected."""

    def test_no_ygg_keys_when_adapter_absent(self, server: RPCServer) -> None:
        meta = server._gather_meta()
        assert "ygg_address" not in meta
        assert "ygg_port" not in meta

    def test_yggdrasil_capability_absent(self, server: RPCServer) -> None:
        meta = server._gather_meta()
        assert "yggdrasil" not in meta["capabilities"]

    def test_base_keys_present(self, server: RPCServer) -> None:
        meta = server._gather_meta()
        for key in ("styrene_version", "profile", "capabilities", "arch", "os_id"):
            assert key in meta


class TestGatherMetaYggRunning:
    """_gather_meta with a running YggdrasilAdapter."""

    def test_ygg_address_present(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter("200:1234::1")
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert meta["ygg_address"] == "200:1234::1"

    def test_ygg_port_present(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter("200:1234::1", listen_port=9002)
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert meta["ygg_port"] == 9002

    def test_yggdrasil_capability_present(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter("200:1234::1")
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert "yggdrasil" in meta["capabilities"]


class TestGatherMetaYggNotRunning:
    """_gather_meta with an adapter injected but Yggdrasil not yet running."""

    def test_no_ygg_address_when_not_running(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter(None)  # address returns None
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert "ygg_address" not in meta

    def test_no_ygg_port_when_not_running(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter(None)
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert "ygg_port" not in meta

    def test_yggdrasil_capability_absent_when_not_running(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter(None)
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert "yggdrasil" not in meta["capabilities"]


class TestGatherMetaYggException:
    """_gather_meta gracefully handles adapter errors."""

    def test_exception_in_get_local_address_omits_keys(self, server: RPCServer) -> None:
        adapter = MagicMock()
        adapter.get_local_address.side_effect = RuntimeError("admin socket unavailable")
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        assert "ygg_address" not in meta
        assert "ygg_port" not in meta
        assert "yggdrasil" not in meta["capabilities"]

    def test_other_keys_still_present_after_exception(self, server: RPCServer) -> None:
        adapter = MagicMock()
        adapter.get_local_address.side_effect = RuntimeError("boom")
        server.set_ygg_adapter(adapter)
        meta = server._gather_meta()
        for key in ("styrene_version", "profile", "capabilities", "arch", "os_id"):
            assert key in meta


class TestSetYggAdapter:
    """set_ygg_adapter injection method."""

    def test_set_and_clear_adapter(self, server: RPCServer) -> None:
        adapter = _make_ygg_adapter("200:abcd::1")
        server.set_ygg_adapter(adapter)
        assert server._ygg_adapter is adapter

    def test_set_none_clears_adapter(self, server: RPCServer) -> None:
        server.set_ygg_adapter(_make_ygg_adapter("200:1::1"))
        server.set_ygg_adapter(None)
        meta = server._gather_meta()
        assert "ygg_address" not in meta
