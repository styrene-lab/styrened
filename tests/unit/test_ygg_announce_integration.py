"""Tests for Yggdrasil announce integration in StyreneAnnounceHandler.

Covers:
- CAPABILITY_YGGDRASIL detection in received announces → ygg_address=None
- _bootstrap_ygg_peer: extracts ygg_address+ygg_port from /meta, calls add_peer()
- EAGER mode fires bootstrap task when all conditions met
- LAZY mode suppresses bootstrap task
- bootstrap_from_rns=False suppresses bootstrap task
- Absent local Yggdrasil suppresses bootstrap task
- Silent failure on /meta errors
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.capabilities import CAPABILITY_YGGDRASIL
from styrened.models.config import PeerDiscovery, YggdrasilConfig
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.reticulum import StyreneAnnounceHandler, _bootstrap_ygg_peer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(
    ygg_adapter: Any = None,
    ygg_config: YggdrasilConfig | None = None,
) -> StyreneAnnounceHandler:
    return StyreneAnnounceHandler(
        callback=None,
        node_store=None,
        ygg_adapter=ygg_adapter,
        ygg_config=ygg_config,
    )


def _fake_identity(hex_hash: str = "a" * 32) -> MagicMock:
    identity = MagicMock()
    identity.hash = bytes.fromhex(hex_hash)
    identity.get_public_key.return_value = None
    return identity


def _styrene_app_data(capabilities: list[str]) -> bytes:
    caps_str = ",".join(capabilities) if capabilities else "node"
    lxmf_dest = "b" * 64
    return f"styrene:TestNode:0.15.3:{caps_str}:{lxmf_dest}:tn:fp:".encode()


def _call_received_announce(
    handler: StyreneAnnounceHandler,
    dest_hex: str = "c" * 64,
    identity_hex: str = "a" * 32,
    capabilities: list[str] | None = None,
) -> None:
    """Invoke received_announce with a synthetic Styrene app_data."""
    dest_hash = bytes.fromhex(dest_hex)
    identity = _fake_identity(identity_hex)
    app_data = _styrene_app_data(capabilities or [])

    with (
        patch("styrened.services.reticulum.RNS") as mock_rns,
        patch("styrened.services.reticulum.create_mesh_device") as mock_create,
        patch("styrened.services.reticulum.logger"),
    ):
        # RNS access mode check (OPEN by default, no allowed_peers)
        mock_rns.Transport.path_table = {}

        # Return a real MeshDevice from create_mesh_device
        import time
        caps = capabilities or []
        device = MeshDevice(
            destination_hash=dest_hex,
            identity_hash=identity_hex,
            device_type=DeviceType.STYRENE_NODE,
            name="TestNode",
            capabilities=caps,
            lxmf_destination_hash="b" * 64,
            last_announce=int(time.time()),
        )
        mock_create.return_value = device

        handler.received_announce(
            destination_hash=dest_hash,
            announced_identity=identity,
            app_data=app_data,
        )


# ---------------------------------------------------------------------------
# PeerDiscovery enum
# ---------------------------------------------------------------------------


class TestPeerDiscoveryEnum:
    def test_eager_value(self) -> None:
        assert PeerDiscovery.EAGER.value == "eager"

    def test_lazy_value(self) -> None:
        assert PeerDiscovery.LAZY.value == "lazy"

    def test_default_in_ygg_config(self) -> None:
        cfg = YggdrasilConfig()
        assert cfg.peer_discovery == PeerDiscovery.EAGER


# ---------------------------------------------------------------------------
# ygg_address set to None on capability detection
# ---------------------------------------------------------------------------


class TestCapabilityDetection:
    def test_ygg_capability_sets_ygg_address_none(self) -> None:
        handler = _make_handler()
        _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])
        device = list(handler.discovered_devices.values())[0]
        assert device.ygg_address is None

    def test_no_ygg_capability_leaves_ygg_address_unchanged(self) -> None:
        handler = _make_handler()
        _call_received_announce(handler, capabilities=["hub"])
        device = list(handler.discovered_devices.values())[0]
        # ygg_address stays at whatever default create_mesh_device provides
        assert device.ygg_address is None  # default field value

    def test_multiple_capabilities_including_ygg(self) -> None:
        handler = _make_handler()
        _call_received_announce(handler, capabilities=["hub", CAPABILITY_YGGDRASIL, "api"])
        device = list(handler.discovered_devices.values())[0]
        assert CAPABILITY_YGGDRASIL in (device.capabilities or [])
        assert device.ygg_address is None


# ---------------------------------------------------------------------------
# EAGER bootstrap task dispatch
# ---------------------------------------------------------------------------


class TestEagerBootstrap:
    def test_eager_fires_task_when_all_conditions_met(self) -> None:
        adapter = MagicMock()
        adapter.get_local_address.return_value = "200::1"

        cfg = YggdrasilConfig(
            bootstrap_from_rns=True,
            peer_discovery=PeerDiscovery.EAGER,
        )
        handler = _make_handler(ygg_adapter=adapter, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])

        assert len(tasks_created) == 1

    def test_lazy_suppresses_task(self) -> None:
        adapter = MagicMock()
        adapter.get_local_address.return_value = "200::1"

        cfg = YggdrasilConfig(
            bootstrap_from_rns=True,
            peer_discovery=PeerDiscovery.LAZY,
        )
        handler = _make_handler(ygg_adapter=adapter, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])

        assert len(tasks_created) == 0

    def test_bootstrap_from_rns_false_suppresses_task(self) -> None:
        adapter = MagicMock()
        adapter.get_local_address.return_value = "200::1"

        cfg = YggdrasilConfig(
            bootstrap_from_rns=False,
            peer_discovery=PeerDiscovery.EAGER,
        )
        handler = _make_handler(ygg_adapter=adapter, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])

        assert len(tasks_created) == 0

    def test_no_local_ygg_suppresses_task(self) -> None:
        adapter = MagicMock()
        adapter.get_local_address.return_value = None  # not running

        cfg = YggdrasilConfig(
            bootstrap_from_rns=True,
            peer_discovery=PeerDiscovery.EAGER,
        )
        handler = _make_handler(ygg_adapter=adapter, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])

        assert len(tasks_created) == 0

    def test_no_ygg_adapter_suppresses_task(self) -> None:
        cfg = YggdrasilConfig(
            bootstrap_from_rns=True,
            peer_discovery=PeerDiscovery.EAGER,
        )
        handler = _make_handler(ygg_adapter=None, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=[CAPABILITY_YGGDRASIL])

        assert len(tasks_created) == 0

    def test_no_ygg_capability_never_fires_task(self) -> None:
        adapter = MagicMock()
        adapter.get_local_address.return_value = "200::1"

        cfg = YggdrasilConfig(
            bootstrap_from_rns=True,
            peer_discovery=PeerDiscovery.EAGER,
        )
        handler = _make_handler(ygg_adapter=adapter, ygg_config=cfg)

        tasks_created: list[Any] = []

        with patch("asyncio.create_task", side_effect=lambda coro: tasks_created.append(coro) or MagicMock()):
            _call_received_announce(handler, capabilities=["hub"])  # no yggdrasil

        assert len(tasks_created) == 0


# ---------------------------------------------------------------------------
# _bootstrap_ygg_peer — async unit tests
# ---------------------------------------------------------------------------


class TestBootstrapYggPeer:
    @pytest.mark.asyncio
    async def test_successful_bootstrap(self) -> None:
        adapter = AsyncMock()
        adapter.add_peer.return_value = True

        meta = {"ygg_address": "200::abcd", "ygg_port": 9001}
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.return_value = meta

        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

        adapter.add_peer.assert_awaited_once_with("200::abcd", 9001)

    @pytest.mark.asyncio
    async def test_no_direct_link_service_silent(self) -> None:
        adapter = AsyncMock()
        # Pass direct_link=None and stub out the fallback import so it also returns None
        with patch("styrened.services.reticulum.DirectLinkService" if False else "builtins.__import__", side_effect=ImportError):
            # Simplest: patch nothing, pass None directly but patch get_instance
            pass

        # Direct injection of None propagates silently — no get_instance needed
        with patch("styrened.services.direct_link.DirectLinkService") as mock_cls:
            mock_cls.get_instance.return_value = None
            # Pass no direct_link, force import path to return None
            import styrened.services.direct_link as dl_mod

            original = getattr(dl_mod.DirectLinkService, "get_instance", None)
            try:
                dl_mod.DirectLinkService.get_instance = staticmethod(lambda: None)  # type: ignore[attr-defined]
                await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter)
            finally:
                if original is not None:
                    dl_mod.DirectLinkService.get_instance = original  # type: ignore[attr-defined]

        adapter.add_peer.assert_not_called()

    @pytest.mark.asyncio
    async def test_meta_returns_none_silent(self) -> None:
        adapter = AsyncMock()
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.return_value = None

        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

        adapter.add_peer.assert_not_called()

    @pytest.mark.asyncio
    async def test_meta_missing_ygg_address_silent(self) -> None:
        adapter = AsyncMock()
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.return_value = {"version": "0.15.3"}

        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

        adapter.add_peer.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_peer_failure_silent(self) -> None:
        adapter = AsyncMock()
        adapter.add_peer.return_value = False

        meta = {"ygg_address": "200::1", "ygg_port": 9001}
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.return_value = meta

        # Should not raise even though add_peer returns False
        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

    @pytest.mark.asyncio
    async def test_fetch_meta_exception_silent(self) -> None:
        adapter = AsyncMock()
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.side_effect = RuntimeError("connection refused")

        # Should not raise
        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

        adapter.add_peer.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_port_9001_when_missing(self) -> None:
        adapter = AsyncMock()
        adapter.add_peer.return_value = True

        # ygg_port absent → default 9001
        meta = {"ygg_address": "200::cafe"}
        mock_dl = AsyncMock()
        mock_dl.fetch_meta.return_value = meta

        await _bootstrap_ygg_peer("aa" * 16, "bb" * 32, adapter, direct_link=mock_dl)

        adapter.add_peer.assert_awaited_once_with("200::cafe", 9001)
