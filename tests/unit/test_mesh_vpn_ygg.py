"""Tests for Yggdrasil-aware handshake extensions in MeshVPNService.

Covers:
- PeerInfo.ygg_endpoint and capabilities fields
- build_handshake_request/response with ygg_endpoint
- parse_handshake_request/response backward-compat + ygg_endpoint
- CAPABILITY_YGGDRASIL constant and PeerDiscovery enum
- _detect_yggdrasil_endpoint — adapter fast path and fallback
- _select_peer_endpoint — prefer ygg_endpoint when adapter running
- MeshVPNConfig.peer_discovery field
- Lazy /meta fetch in initiate_handshake when CAPABILITY_YGGDRASIL present
- add_peer() called in handle_handshake_request/response when ygg_endpoint set
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.config import MeshVPNConfig
from styrened.services.mesh_vpn import (
    CAPABILITY_YGGDRASIL,
    PeerDiscovery,
    PeerInfo,
    build_handshake_request,
    build_handshake_response,
    parse_handshake_request,
    parse_handshake_response,
)

# ---------------------------------------------------------------------------
# Constants and enums
# ---------------------------------------------------------------------------


def test_capability_yggdrasil_string():
    assert CAPABILITY_YGGDRASIL == "yggdrasil"


def test_peer_discovery_values():
    assert PeerDiscovery.EAGER.value == "eager"
    assert PeerDiscovery.LAZY.value == "lazy"


# ---------------------------------------------------------------------------
# PeerInfo new fields
# ---------------------------------------------------------------------------


def test_peerinfo_defaults_ygg_fields():
    p = PeerInfo(public_key="pk", mesh_ip="fd73::1")
    assert p.ygg_endpoint is None
    assert p.capabilities == []


def test_peerinfo_with_ygg_endpoint():
    p = PeerInfo(
        public_key="pk",
        mesh_ip="fd73::1",
        ygg_endpoint="[200:abcd::1]:51820",
        capabilities=[CAPABILITY_YGGDRASIL],
    )
    assert p.ygg_endpoint == "[200:abcd::1]:51820"
    assert CAPABILITY_YGGDRASIL in p.capabilities


# ---------------------------------------------------------------------------
# build / parse — backward-compat (no ygg_endpoint)
# ---------------------------------------------------------------------------


def test_build_handshake_request_no_ygg():
    data = build_handshake_request("pubkey123", "fd73::2")
    payload = json.loads(data)
    assert "ygg_endpoint" not in payload
    assert payload["wg_pubkey"] == "pubkey123"


def test_build_handshake_response_no_ygg():
    data = build_handshake_response("pubkey", "fd73::2", gateway=True)
    payload = json.loads(data)
    assert "ygg_endpoint" not in payload
    assert payload["gateway"] is True


def test_parse_handshake_request_no_ygg_backward_compat():
    """Old peers sending no ygg_endpoint must parse fine."""
    raw = json.dumps({
        "version": 1,
        "wg_pubkey": "pk",
        "mesh_ip": "fd73::3",
        "endpoint": "1.2.3.4:51820",
    }).encode()
    peer = parse_handshake_request(raw)
    assert peer.ygg_endpoint is None


def test_parse_handshake_response_no_ygg_backward_compat():
    raw = json.dumps({
        "version": 1,
        "wg_pubkey": "pk",
        "mesh_ip": "fd73::3",
        "gateway": False,
    }).encode()
    peer = parse_handshake_response(raw)
    assert peer.ygg_endpoint is None


# ---------------------------------------------------------------------------
# build / parse — with ygg_endpoint
# ---------------------------------------------------------------------------


def test_build_handshake_request_with_ygg():
    data = build_handshake_request(
        "pubkey", "fd73::2", ygg_endpoint="[200::1]:51820"
    )
    payload = json.loads(data)
    assert payload["ygg_endpoint"] == "[200::1]:51820"


def test_build_handshake_response_with_ygg():
    data = build_handshake_response(
        "pubkey", "fd73::2", ygg_endpoint="[200::1]:51820"
    )
    payload = json.loads(data)
    assert payload["ygg_endpoint"] == "[200::1]:51820"


def test_parse_handshake_request_with_ygg():
    raw = json.dumps({
        "version": 1,
        "wg_pubkey": "pk",
        "mesh_ip": "fd73::3",
        "ygg_endpoint": "[200::1]:51820",
    }).encode()
    peer = parse_handshake_request(raw)
    assert peer.ygg_endpoint == "[200::1]:51820"


def test_parse_handshake_response_with_ygg():
    raw = json.dumps({
        "version": 1,
        "wg_pubkey": "pk",
        "mesh_ip": "fd73::3",
        "gateway": True,
        "ygg_endpoint": "[200::1]:51820",
    }).encode()
    peer = parse_handshake_response(raw)
    assert peer.ygg_endpoint == "[200::1]:51820"


def test_parse_handshake_request_ygg_endpoint_empty_string_becomes_none():
    """Empty string ygg_endpoint → None (canonical no-value)."""
    raw = json.dumps({
        "version": 1,
        "wg_pubkey": "pk",
        "mesh_ip": "fd73::3",
        "ygg_endpoint": "",
    }).encode()
    peer = parse_handshake_request(raw)
    assert peer.ygg_endpoint is None


# ---------------------------------------------------------------------------
# MeshVPNConfig.peer_discovery
# ---------------------------------------------------------------------------


def test_meshvpnconfig_peer_discovery_default():
    cfg = MeshVPNConfig()
    assert cfg.peer_discovery == "lazy"


def test_meshvpnconfig_peer_discovery_eager():
    cfg = MeshVPNConfig(peer_discovery="eager")
    assert cfg.peer_discovery == "eager"


# ---------------------------------------------------------------------------
# Helpers: _detect_yggdrasil_endpoint and _select_peer_endpoint
# ---------------------------------------------------------------------------


def _make_service(**kwargs: Any):
    """Build a MeshVPNService with minimal real state."""
    from styrened.services.mesh_vpn import MeshVPNService

    svc = MeshVPNService.__new__(MeshVPNService)
    svc.config = MeshVPNConfig(**kwargs)
    svc._peers = {}
    svc._styrene_protocol = None
    svc._pending_handshakes = {}
    svc._ygg_adapter = None
    svc._direct_link_service = None
    svc._started = False
    svc.private_key = ""
    svc.public_key = ""
    svc.mesh_ip = ""
    return svc


@pytest.mark.asyncio
async def test_detect_yggdrasil_endpoint_adapter_fast_path():
    """When adapter is present and has cached address, use it immediately."""
    svc = _make_service()
    mock_adapter = MagicMock()
    mock_adapter.get_local_address.return_value = "200:abcd::1"
    svc._ygg_adapter = mock_adapter

    result = await svc._detect_yggdrasil_endpoint(51820)
    assert result == "[200:abcd::1]:51820"


@pytest.mark.asyncio
async def test_detect_yggdrasil_endpoint_adapter_no_address():
    """Adapter present but no cached address → fall through to socket probe."""
    svc = _make_service()
    mock_adapter = MagicMock()
    mock_adapter.get_local_address.return_value = None
    svc._ygg_adapter = mock_adapter

    # No sockets exist in test environment → returns None
    result = await svc._detect_yggdrasil_endpoint(51820)
    assert result is None


@pytest.mark.asyncio
async def test_detect_yggdrasil_endpoint_no_adapter_no_sockets():
    """No adapter, no admin sockets → None."""
    svc = _make_service()
    result = await svc._detect_yggdrasil_endpoint(51820)
    assert result is None


def test_select_peer_endpoint_prefers_ygg_when_local_ygg_running():
    svc = _make_service()
    mock_adapter = MagicMock()
    mock_adapter.get_local_address.return_value = "200::1"
    svc._ygg_adapter = mock_adapter

    peer = PeerInfo(
        public_key="pk",
        mesh_ip="fd73::2",
        endpoint="1.2.3.4:51820",
        ygg_endpoint="[200::2]:51820",
    )
    assert svc._select_peer_endpoint(peer) == "[200::2]:51820"


def test_select_peer_endpoint_falls_back_when_no_local_ygg():
    svc = _make_service()  # _ygg_adapter is None

    peer = PeerInfo(
        public_key="pk",
        mesh_ip="fd73::2",
        endpoint="1.2.3.4:51820",
        ygg_endpoint="[200::2]:51820",
    )
    assert svc._select_peer_endpoint(peer) == "1.2.3.4:51820"


def test_select_peer_endpoint_no_ygg_endpoint():
    svc = _make_service()
    mock_adapter = MagicMock()
    mock_adapter.get_local_address.return_value = "200::1"
    svc._ygg_adapter = mock_adapter

    peer = PeerInfo(public_key="pk", mesh_ip="fd73::2", endpoint="1.2.3.4:51820")
    assert svc._select_peer_endpoint(peer) == "1.2.3.4:51820"


def test_select_peer_endpoint_no_endpoint_at_all():
    svc = _make_service()
    peer = PeerInfo(public_key="pk", mesh_ip="fd73::2")
    assert svc._select_peer_endpoint(peer) is None


# ---------------------------------------------------------------------------
# _fetch_meta_ygg_address
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_meta_ygg_address_no_dl_service():
    """Without DirectLinkService injected, returns None gracefully."""
    svc = _make_service()
    result = await svc._fetch_meta_ygg_address("aabbccddeeff")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_meta_ygg_address_returns_ygg_address():
    svc = _make_service()
    mock_dl = AsyncMock()
    mock_dl.request_meta.return_value = {"ygg_address": "200:beef::1", "capabilities": ["yggdrasil"]}
    svc._direct_link_service = mock_dl

    result = await svc._fetch_meta_ygg_address("aabbccdd")
    assert result == "200:beef::1"
    mock_dl.request_meta.assert_called_once_with("aabbccdd")


@pytest.mark.asyncio
async def test_fetch_meta_ygg_address_no_ygg_address_in_meta():
    svc = _make_service()
    mock_dl = AsyncMock()
    mock_dl.request_meta.return_value = {"capabilities": [], "styrene_version": "0.15.3"}
    svc._direct_link_service = mock_dl

    result = await svc._fetch_meta_ygg_address("aabbccdd")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_meta_ygg_address_dl_returns_none():
    svc = _make_service()
    mock_dl = AsyncMock()
    mock_dl.request_meta.return_value = None
    svc._direct_link_service = mock_dl

    result = await svc._fetch_meta_ygg_address("aabbccdd")
    assert result is None


# ---------------------------------------------------------------------------
# Lazy peer_discovery in initiate_handshake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_handshake_lazy_fetches_meta_for_ygg_peer():
    """LAZY mode fetches /meta when target has CAPABILITY_YGGDRASIL."""
    svc = _make_service(peer_discovery="lazy")
    svc._started = True
    svc.public_key = "pubkey"
    svc.mesh_ip = "fd73::1"

    # Pre-populate peer with capability flag
    svc._peers["target"] = PeerInfo(
        public_key="", mesh_ip="", capabilities=[CAPABILITY_YGGDRASIL]
    )

    mock_dl = AsyncMock()
    mock_dl.request_meta.return_value = {"ygg_address": "200:cafe::1"}
    svc._direct_link_service = mock_dl

    mock_adapter = MagicMock()
    mock_adapter.get_local_address.return_value = "200:feed::1"
    mock_adapter.add_peer = AsyncMock(return_value=True)
    svc._ygg_adapter = mock_adapter

    mock_proto = AsyncMock()
    svc._styrene_protocol = mock_proto

    # Patch _send_vpn_message so handshake doesn't hang waiting for response
    with patch.object(svc, "_send_vpn_message", new_callable=AsyncMock):
        # Give the future a result so wait_for doesn't time out in test
        async def _fake_send(*args, **kwargs):
            future = svc._pending_handshakes.get("target")
            if future and not future.done():
                future.set_result(svc._peers["target"])

        svc._send_vpn_message = _fake_send  # type: ignore[method-assign]
        await svc.initiate_handshake("target", timeout=2.0)

    # add_peer should have been called with the Ygg address from /meta
    mock_adapter.add_peer.assert_called_once_with("200:cafe::1")


@pytest.mark.asyncio
async def test_initiate_handshake_eager_skips_meta_fetch():
    """EAGER mode does NOT call _fetch_meta_ygg_address."""
    svc = _make_service(peer_discovery="eager")
    svc._started = True
    svc.public_key = "pubkey"
    svc.mesh_ip = "fd73::1"

    # Pre-populate peer with ygg_endpoint already set (eager path)
    svc._peers["target"] = PeerInfo(
        public_key="",
        mesh_ip="",
        capabilities=[CAPABILITY_YGGDRASIL],
        ygg_endpoint="[200::1]:51820",
    )

    mock_dl = AsyncMock()
    svc._direct_link_service = mock_dl

    svc._styrene_protocol = MagicMock()

    with patch.object(svc, "_send_vpn_message", new_callable=AsyncMock):
        async def _fake_send(*args, **kwargs):
            future = svc._pending_handshakes.get("target")
            if future and not future.done():
                future.set_result(svc._peers["target"])

        svc._send_vpn_message = _fake_send  # type: ignore[method-assign]
        await svc.initiate_handshake("target", timeout=2.0)

    # Should NOT have called request_meta
    mock_dl.request_meta.assert_not_called()
