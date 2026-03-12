"""Tests for DirectLinkService — payload selection, cache, and status helpers."""
from __future__ import annotations


import time
from unittest.mock import MagicMock

import pytest

from styrened.services.direct_link import (
    PAYLOAD_SET_FAST,
    PAYLOAD_SET_MEDIUM,
    PAYLOAD_SET_MINIMAL,
    PAYLOAD_SET_SLOW,
    DirectLinkService,
)


class TestSelectPayloads:
    """RTT-adaptive payload selection must pick safe sizes for LoRa."""

    def test_none_rtt_uses_medium(self):
        result = DirectLinkService._select_payloads(None)
        assert result == PAYLOAD_SET_MEDIUM

    def test_tcp_rtt_uses_fast(self):
        result = DirectLinkService._select_payloads(0.05)
        assert result == PAYLOAD_SET_FAST
        assert 262144 in result  # 256KB included

    def test_boundary_200ms_uses_medium(self):
        result = DirectLinkService._select_payloads(0.2)
        assert result == PAYLOAD_SET_MEDIUM
        assert 262144 not in result  # No 256KB

    def test_wifi_mesh_uses_medium(self):
        result = DirectLinkService._select_payloads(0.8)
        assert result == PAYLOAD_SET_MEDIUM
        assert max(result) == 16384  # 16KB max

    def test_fast_lora_uses_slow(self):
        result = DirectLinkService._select_payloads(3.0)
        assert result == PAYLOAD_SET_SLOW
        assert max(result) == 4096  # 4KB max

    def test_slow_lora_uses_minimal(self):
        result = DirectLinkService._select_payloads(8.0)
        assert result == PAYLOAD_SET_MINIMAL
        assert max(result) == 1024  # 1KB max

    def test_boundary_2s_uses_slow(self):
        result = DirectLinkService._select_payloads(2.0)
        assert result == PAYLOAD_SET_SLOW

    def test_boundary_5s_uses_minimal(self):
        result = DirectLinkService._select_payloads(5.0)
        assert result == PAYLOAD_SET_MINIMAL

    def test_returns_copies(self):
        """Must return copies, not references to module-level lists."""
        a = DirectLinkService._select_payloads(0.05)
        b = DirectLinkService._select_payloads(0.05)
        assert a is not b
        a.append(999)
        assert 999 not in DirectLinkService._select_payloads(0.05)

    def test_all_sets_are_sorted_ascending(self):
        for rtt in [None, 0.01, 0.5, 3.0, 10.0]:
            payloads = DirectLinkService._select_payloads(rtt)
            assert payloads == sorted(payloads), f"Not sorted for RTT={rtt}"


class TestStatusCache:
    """Module-level status cache in mesh_device_detail."""

    def test_cache_hit_within_ttl(self):
        from styrened.tui.screens.mesh_device_detail import (
            _STATUS_CACHE,
            _cache_status,
            _get_cached_status,
        )

        _STATUS_CACHE.clear()
        mock_status = MagicMock()
        _cache_status("abc123", mock_status)
        assert _get_cached_status("abc123") is mock_status

    def test_cache_miss_after_ttl(self):
        from styrened.tui.screens.mesh_device_detail import (
            _STATUS_CACHE,
            _STATUS_CACHE_TTL,
            _get_cached_status,
        )

        _STATUS_CACHE.clear()
        mock_status = MagicMock()
        # Manually insert with old timestamp
        _STATUS_CACHE["old123"] = (mock_status, time.time() - _STATUS_CACHE_TTL - 1)
        assert _get_cached_status("old123") is None
        # Verify it was evicted
        assert "old123" not in _STATUS_CACHE

    def test_cache_miss_unknown_key(self):
        from styrened.tui.screens.mesh_device_detail import (
            _STATUS_CACHE,
            _get_cached_status,
        )

        _STATUS_CACHE.clear()
        assert _get_cached_status("nonexistent") is None

    def test_cache_eviction_at_max(self):
        from styrened.tui.screens.mesh_device_detail import (
            _STATUS_CACHE,
            _STATUS_CACHE_MAX,
            _cache_status,
        )

        _STATUS_CACHE.clear()
        # Fill to max + 1
        for i in range(_STATUS_CACHE_MAX + 5):
            _cache_status(f"device_{i}", MagicMock())
        assert len(_STATUS_CACHE) <= _STATUS_CACHE_MAX
        _STATUS_CACHE.clear()


class TestDirectLinkServiceLifecycle:
    """Basic lifecycle tests."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        svc = DirectLinkService()
        await svc.start()
        assert svc._started
        assert svc._speedtest_lock is not None
        await svc.stop()
        assert not svc._started
        assert len(svc._links) == 0

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        svc = DirectLinkService()
        await svc.start()
        await svc.start()  # Should not raise
        assert svc._started
        await svc.stop()

    @pytest.mark.asyncio
    async def test_speedtest_no_link_returns_no_link(self):
        svc = DirectLinkService()
        await svc.start()
        result = await svc.run_speedtest("deadbeef" * 4)
        assert len(result) == 1
        assert result[0]["status"] == "no_link"
        await svc.stop()

    @pytest.mark.asyncio
    async def test_teardown_nonexistent_returns_false(self):
        svc = DirectLinkService()
        await svc.start()
        assert not await svc.teardown("nonexistent")
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_link_info_nonexistent(self):
        svc = DirectLinkService()
        assert svc.get_link_info("nonexistent") is None

    @pytest.mark.asyncio
    async def test_request_status_no_link(self):
        svc = DirectLinkService()
        await svc.start()
        result = await svc.request_status("deadbeef" * 4)
        assert result is None
        await svc.stop()


class TestEstablishIdentityRecall:
    """Tests for establish() identity resolution logic.

    The establish() method must handle both destination hashes and identity
    hashes, because the NodeStore sometimes stores identity hashes in the
    destination_hash field.
    """

    @pytest.mark.asyncio
    async def test_recall_by_dest_hash_succeeds(self):
        """When RNS.Identity.recall(dest_hash) succeeds, skip path discovery."""
        import sys
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_identity = MagicMock()
        mock_identity.hash = bytes.fromhex("aa" * 16)

        mock_datalink_dest = MagicMock()
        mock_datalink_dest.hash = bytes.fromhex("bb" * 16)

        svc = DirectLinkService()
        await svc.start()

        with patch.dict(sys.modules, {"RNS": MagicMock()}):
            import RNS
            # First recall (by dest hash) succeeds
            RNS.Identity.recall = MagicMock(return_value=mock_identity)
            RNS.Transport.has_path = MagicMock(return_value=True)
            RNS.Destination = MagicMock(return_value=mock_datalink_dest)
            RNS.Destination.OUT = 1
            RNS.Destination.SINGLE = 2
            RNS.Link = MagicMock()
            RNS.Link.ACTIVE = 1

            with patch.object(svc, "_create_link", new_callable=AsyncMock, return_value=None):
                await svc.establish("aa" * 16)
                # Should have called recall with dest_hash
                assert RNS.Identity.recall.call_count >= 1
                first_call = RNS.Identity.recall.call_args_list[0]
                assert first_call[0][0] == bytes.fromhex("aa" * 16)

        await svc.stop()

    @pytest.mark.asyncio
    async def test_recall_falls_back_to_identity_hash(self):
        """When dest hash recall fails, try from_identity_hash=True."""
        import sys
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_identity = MagicMock()
        mock_identity.hash = bytes.fromhex("aa" * 16)

        mock_datalink_dest = MagicMock()
        mock_datalink_dest.hash = bytes.fromhex("bb" * 16)

        svc = DirectLinkService()
        await svc.start()

        call_count = 0

        def mock_recall(hash_bytes, from_identity_hash=False):
            nonlocal call_count
            call_count += 1
            if from_identity_hash:
                return mock_identity  # Second attempt succeeds
            return None  # First attempt fails

        with patch.dict(sys.modules, {"RNS": MagicMock()}):
            import RNS
            RNS.Identity.recall = mock_recall
            RNS.Transport.has_path = MagicMock(return_value=True)
            RNS.Destination = MagicMock(return_value=mock_datalink_dest)
            RNS.Destination.OUT = 1
            RNS.Destination.SINGLE = 2
            RNS.Link = MagicMock()
            RNS.Link.ACTIVE = 1

            with patch.object(svc, "_create_link", new_callable=AsyncMock, return_value=None):
                await svc.establish("aa" * 16)
                # Should have tried both recall methods
                assert call_count == 2

        await svc.stop()

    @pytest.mark.asyncio
    async def test_identity_unknown_when_both_recalls_fail(self):
        """Returns identity_unknown when neither recall method works and no path."""
        import sys
        from unittest.mock import MagicMock, patch

        svc = DirectLinkService()
        await svc.start()

        mock_rns = MagicMock()
        mock_rns.Identity.recall = MagicMock(return_value=None)
        mock_rns.Transport.has_path = MagicMock(return_value=True)

        with patch.dict(sys.modules, {"RNS": mock_rns}):
            result = await svc.establish("cc" * 16)
            assert result.status == "identity_unknown"

        await svc.stop()

    @pytest.mark.asyncio
    async def test_path_not_found_timeout(self):
        """Returns path_not_found when path discovery times out."""
        import sys
        from unittest.mock import MagicMock, patch

        import styrened.services.direct_link as dl_mod

        svc = DirectLinkService()
        await svc.start()

        original_timeout = dl_mod.PATH_DISCOVERY_TIMEOUT
        dl_mod.PATH_DISCOVERY_TIMEOUT = 0.1

        try:
            mock_rns = MagicMock()
            mock_rns.Identity.recall = MagicMock(return_value=None)
            mock_rns.Transport.has_path = MagicMock(return_value=False)
            mock_rns.Transport.request_path = MagicMock()

            with patch.dict(sys.modules, {"RNS": mock_rns}):
                result = await svc.establish("dd" * 16)
                assert result.status == "path_not_found"
        finally:
            dl_mod.PATH_DISCOVERY_TIMEOUT = original_timeout

        await svc.stop()


class TestDestHashProperty:
    """Test _dest_hash property on MeshDeviceDetailScreen."""

    def test_dest_hash_prefers_device_destination_hash(self):
        """_dest_hash should return device.destination_hash when available."""
        from styrened.models.mesh_device import DeviceType, MeshDevice

        device = MeshDevice(
            destination_hash="fe75a225eeff636a" + "0" * 16,
            name="test",
            device_type=DeviceType.STYRENE_NODE, last_announce=0,
            identity_hash="e012da2530c3eb27" + "0" * 16,
        )

        # Can't instantiate the full screen easily, so test the logic directly
        dest_hash = device.destination_hash
        identity = device.identity_hash
        # Simulate _dest_hash logic
        result = dest_hash if dest_hash else identity
        assert result == "fe75a225eeff636a" + "0" * 16
        assert result != identity

    def test_dest_hash_falls_back_to_identity(self):
        """When device has no destination_hash, fall back to identity."""
        from styrened.models.mesh_device import DeviceType, MeshDevice

        device = MeshDevice(
            destination_hash="",
            name="test",
            device_type=DeviceType.STYRENE_NODE, last_announce=0,
            identity_hash="e012da2530c3eb27" + "0" * 16,
        )

        result = device.destination_hash if device.destination_hash else device.identity_hash
        assert result == "e012da2530c3eb27" + "0" * 16

    def test_dest_hash_same_as_identity_is_common_bug(self):
        """Document: NodeStore often stores identity_hash as destination_hash."""
        from styrened.models.mesh_device import DeviceType, MeshDevice

        # This is the broken state we see in practice
        identity = "e012da2530c3eb27" + "0" * 16
        device = MeshDevice(
            destination_hash=identity,  # Bug: same as identity
            name="test",
            device_type=DeviceType.STYRENE_NODE, last_announce=0,
            identity_hash=identity,
        )
        # _dest_hash would return the identity hash thinking it's a dest hash
        # establish() must handle this via from_identity_hash=True fallback
        assert device.destination_hash == device.identity_hash


class TestExplorationFiltering:
    """Status filtering on exploration tables."""

    def test_status_counts_empty(self):
        from styrened.tui.screens.exploration import ReticumAnnounceTable

        table = ReticumAnnounceTable()
        counts = table.status_counts
        assert counts == {"active": 0, "stale": 0, "lost": 0}

    def test_hide_lost_default_true(self):
        from styrened.tui.screens.exploration import ReticumAnnounceTable

        table = ReticumAnnounceTable()
        assert table.hiding_lost is True

    def test_hide_stale_default_false(self):
        from styrened.tui.screens.exploration import ReticumAnnounceTable

        table = ReticumAnnounceTable()
        assert table.hiding_stale is False

    def test_toggle_hide_lost_state(self):
        from styrened.tui.screens.exploration import ReticumAnnounceTable

        table = ReticumAnnounceTable()
        # Directly mutate state without triggering _rebuild_table (no mount)
        assert table._hide_lost is True
        table._hide_lost = False
        assert table.hiding_lost is False
        table._hide_lost = True
        assert table.hiding_lost is True

    def test_toggle_hide_stale_state(self):
        from styrened.tui.screens.exploration import ReticumAnnounceTable

        table = ReticumAnnounceTable()
        assert table._hide_stale is False
        table._hide_stale = True
        assert table.hiding_stale is True
        table._hide_stale = False
        assert table.hiding_stale is False


class TestIPCProtocolNoCollisions:
    """Verify IPC command values are unique."""

    def test_no_enum_value_collisions(self):
        from styrened.ipc.protocol import IPCMessageType

        seen: dict[int, str] = {}
        for member in IPCMessageType:
            assert member.value not in seen, (
                f"COLLISION: {member.name} ({hex(member.value)}) "
                f"== {seen[member.value]} ({hex(member.value)})"
            )
            seen[member.value] = member.name

    def test_datalink_commands_in_0x60_range(self):
        from styrened.ipc.protocol import IPCMessageType

        assert IPCMessageType.CMD_DATALINK_ESTABLISH == 0x60
        assert IPCMessageType.CMD_DATALINK_TEARDOWN == 0x61
        assert IPCMessageType.CMD_DATALINK_STATUS == 0x62
        assert IPCMessageType.CMD_DATALINK_QUERY == 0x63
        assert IPCMessageType.CMD_DATALINK_SPEEDTEST == 0x64

    def test_terminal_commands_in_0x50_range(self):
        from styrened.ipc.protocol import IPCMessageType

        assert IPCMessageType.CMD_TERMINAL_OPEN == 0x50
        assert IPCMessageType.CMD_TERMINAL_INPUT == 0x51
        assert IPCMessageType.CMD_TERMINAL_RESIZE == 0x52
        assert IPCMessageType.CMD_TERMINAL_CLOSE == 0x53
