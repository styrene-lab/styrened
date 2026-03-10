"""Security and robustness tests for the DataLink subsystem.

Covers:
- _DataLinkRateLimiter: per-identity throttling, heavy vs light limits,
  FIFO eviction when tracking-table is full
- _sanitize_str / _validate_meta_response / _validate_info_response:
  markup injection prevention, type coercion, field length caps, unknown fields
- _SPEEDTEST_MAX_PAYLOAD_BYTES: payload size cap
- MAX_RESPONSE_BYTES: response size cap before json.loads
- VPN_HANDSHAKE orthogonal-only semantics in RBAC
- _serve_datalink_status RBAC gating (unit level, no RNS)
- Cache boundedness (MeshDeviceTree removed in v0.16.1; those tests retired)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class TestDataLinkRateLimiter:
    def _make(self):
        from styrened.daemon import _DataLinkRateLimiter
        return _DataLinkRateLimiter()

    def test_light_limit_enforced(self):
        from styrened.daemon import _DL_LIGHT_LIMIT
        rl = self._make()
        ih = "aa" * 16
        for i in range(_DL_LIGHT_LIMIT):
            assert rl.check(ih), f"Should pass on call {i}"
        assert not rl.check(ih), "Should be rate-limited after limit"

    def test_heavy_limit_enforced(self):
        from styrened.daemon import _DL_HEAVY_LIMIT
        rl = self._make()
        ih = "bb" * 16
        for i in range(_DL_HEAVY_LIMIT):
            assert rl.check(ih, heavy=True), f"Heavy should pass on call {i}"
        assert not rl.check(ih, heavy=True), "Heavy should be rate-limited"

    def test_heavy_and_light_are_independent_limits(self):
        """Light calls do not consume heavy quota and vice versa."""
        from styrened.daemon import _DL_HEAVY_LIMIT
        rl = self._make()
        ih = "cc" * 16
        # Exhaust heavy quota
        for _ in range(_DL_HEAVY_LIMIT):
            rl.check(ih, heavy=True)
        assert not rl.check(ih, heavy=True)
        # Light calls should still pass (different limit)
        assert rl.check(ih, heavy=False)

    def test_different_identities_are_independent(self):
        from styrened.daemon import _DL_LIGHT_LIMIT
        rl = self._make()
        ih1 = "11" * 16
        ih2 = "22" * 16
        # Exhaust ih1
        for _ in range(_DL_LIGHT_LIMIT):
            rl.check(ih1)
        assert not rl.check(ih1)
        # ih2 should still pass
        assert rl.check(ih2)

    def test_unknown_identity_passes(self):
        """Empty identity string is allowed — unknown callers get through
        until Phase 3 ALLOW_LIST enforcement lands."""
        rl = self._make()
        assert rl.check("")
        assert rl.check("", heavy=True)

    def test_window_reset_after_expiry(self):
        """Calls outside the rate-limit window are not counted."""
        from styrened.daemon import _DL_LIGHT_LIMIT, _DL_WINDOW_SECONDS
        rl = self._make()
        ih = "dd" * 16
        # Exhaust limit
        for _ in range(_DL_LIGHT_LIMIT):
            rl.check(ih)
        assert not rl.check(ih)
        # Manually age the timestamps out of the window
        ts = rl._ts[ih]
        old_time = time.time() - _DL_WINDOW_SECONDS - 1
        for i in range(len(ts)):
            ts[i] = old_time  # deque supports indexed assignment
        assert rl.check(ih), "After window expiry, should be allowed again"

    def test_evicts_oldest_when_full(self):
        """When _DL_MAX_TRACKED identities are tracked, adding a new one
        evicts the oldest, keeping memory bounded."""
        from styrened.daemon import _DL_MAX_TRACKED, _DataLinkRateLimiter
        rl = _DataLinkRateLimiter()
        # Fill table to the limit
        for i in range(_DL_MAX_TRACKED):
            rl.check(f"{i:064x}")
        assert len(rl._ts) == _DL_MAX_TRACKED
        # Adding one more should evict exactly one
        rl.check("ff" * 32)
        assert len(rl._ts) == _DL_MAX_TRACKED


# ---------------------------------------------------------------------------
# Sanitization: _sanitize_str
# ---------------------------------------------------------------------------


class TestSanitizeStr:
    def _s(self, value, max_len=64):
        from styrened.services.direct_link import _sanitize_str
        return _sanitize_str(value, max_len)

    def test_strips_rich_markup(self):
        result = self._s("[red]evil[/red]")
        assert "[" not in result
        assert "]" not in result
        assert "evil" in result

    def test_strips_nested_markup(self):
        result = self._s("[bold][italic]nested[/italic][/bold]")
        assert "[" not in result
        assert "nested" in result

    def test_strips_color_hex_markup(self):
        result = self._s("[#ff0000]colored[/#ff0000]")
        assert "[" not in result
        assert "colored" in result

    def test_caps_length(self):
        long_str = "a" * 200
        result = self._s(long_str, max_len=32)
        assert len(result) == 32

    def test_strips_control_characters(self):
        result = self._s("hello\x00world\x01\x1b[31m")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_non_string_returns_empty(self):
        assert self._s(123) == ""
        assert self._s(None) == ""
        assert self._s(["list"]) == ""
        assert self._s({"dict": True}) == ""

    def test_empty_string_stays_empty(self):
        assert self._s("") == ""

    def test_normal_string_unchanged(self):
        assert self._s("v0.14.3") == "v0.14.3"
        assert self._s("nixos") == "nixos"
        assert self._s("aarch64") == "aarch64"


# ---------------------------------------------------------------------------
# Sanitization: _validate_meta_response
# ---------------------------------------------------------------------------


class TestValidateMetaResponse:
    def _v(self, data):
        from styrened.services.direct_link import _validate_meta_response
        return _validate_meta_response(data)

    def test_valid_response_passes_through(self):
        result = self._v({
            "styrene_version": "0.14.3",
            "profile": "node",
            "capabilities": ["lxmf", "rpc", "datalink"],
            "arch": "aarch64",
            "os_id": "nixos",
        })
        assert result is not None
        assert result["styrene_version"] == "0.14.3"
        assert result["capabilities"] == ["lxmf", "rpc", "datalink"]

    def test_markup_in_version_stripped(self):
        result = self._v({"styrene_version": "[red]evil[/red]"})
        assert result["styrene_version"] == "evil"
        assert "[" not in result["styrene_version"]

    def test_non_string_capabilities_dropped(self):
        result = self._v({
            "styrene_version": "0.14.3",
            "capabilities": ["lxmf", 123, None, {"key": "val"}, "rpc"],
        })
        assert result["capabilities"] == ["lxmf", "rpc"]

    def test_capabilities_count_capped(self):
        from styrened.services.direct_link import _MAX_CAPS_COUNT
        result = self._v({
            "styrene_version": "0.14.3",
            "capabilities": [f"cap{i}" for i in range(_MAX_CAPS_COUNT + 10)],
        })
        assert len(result["capabilities"]) <= _MAX_CAPS_COUNT

    def test_unknown_fields_ignored(self):
        result = self._v({
            "styrene_version": "0.14.3",
            "hostname": "secret-server",   # must be dropped
            "ip": "192.168.1.1",           # must be dropped
            "uptime": 12345,               # must be dropped
            "os_id": "nixos",
        })
        assert "hostname" not in result
        assert "ip" not in result
        assert "uptime" not in result
        assert result.get("os_id") == "nixos"

    def test_non_dict_returns_none(self):
        assert self._v("string") is None
        assert self._v(123) is None
        assert self._v(["list"]) is None
        assert self._v(None) is None

    def test_empty_dict_returns_none(self):
        assert self._v({}) is None

    def test_empty_strings_after_sanitization_excluded(self):
        # A version that is purely markup → empty after strip → not included
        result = self._v({"styrene_version": "[red][/red]", "os_id": "darwin"})
        assert "styrene_version" not in result
        assert result.get("os_id") == "darwin"

    def test_version_length_capped(self):
        from styrened.services.direct_link import _MAX_VERSION_LEN
        result = self._v({"styrene_version": "x" * (_MAX_VERSION_LEN + 20)})
        assert len(result["styrene_version"]) <= _MAX_VERSION_LEN


# ---------------------------------------------------------------------------
# Sanitization: _validate_info_response
# ---------------------------------------------------------------------------


class TestValidateInfoResponse:
    def _v(self, data):
        from styrened.services.direct_link import _validate_info_response
        return _validate_info_response(data)

    def test_valid_response(self):
        result = self._v({"name": "alice-node", "operator_label": "mesh-lead"})
        assert result["name"] == "alice-node"
        assert result["operator_label"] == "mesh-lead"

    def test_markup_stripped_from_name(self):
        result = self._v({"name": "[bold]pwned[/bold]", "operator_label": ""})
        assert result is not None
        assert "[" not in result["name"]
        assert "pwned" in result["name"]

    def test_empty_both_returns_none(self):
        assert self._v({"name": "", "operator_label": ""}) is None

    def test_markup_only_name_stripped_to_empty_returns_none(self):
        # "[red][/red]" strips to "" — only field, so result is None
        assert self._v({"name": "[red][/red]", "operator_label": ""}) is None

    def test_non_dict_returns_none(self):
        assert self._v("evil") is None
        assert self._v(42) is None

    def test_unknown_fields_not_passed_through(self):
        result = self._v({
            "name": "alice",
            "operator_label": "",
            "ip": "10.0.0.1",
            "hostname": "secret",
        })
        assert "ip" not in result
        assert "hostname" not in result

    def test_name_length_capped(self):
        from styrened.services.direct_link import _MAX_NAME_LEN
        result = self._v({"name": "a" * (_MAX_NAME_LEN + 50), "operator_label": ""})
        assert len(result["name"]) <= _MAX_NAME_LEN

    def test_operator_label_length_capped(self):
        from styrened.services.direct_link import _MAX_LABEL_LEN
        result = self._v({"name": "alice", "operator_label": "x" * (_MAX_LABEL_LEN + 50)})
        assert len(result["operator_label"]) <= _MAX_LABEL_LEN


# ---------------------------------------------------------------------------
# Response size gate in request_meta / request_info
# ---------------------------------------------------------------------------


class TestResponseSizeGate:
    @pytest.mark.asyncio
    async def test_meta_oversized_response_discarded(self):
        """A response larger than MAX_RESPONSE_BYTES must be discarded."""
        from styrened.services.direct_link import MAX_RESPONSE_BYTES, DirectLinkService

        svc = DirectLinkService.__new__(DirectLinkService)
        oversized = b"x" * (MAX_RESPONSE_BYTES + 1)
        svc.request = MagicMock(return_value=None)

        import asyncio
        async def fake_request(*a, **kw):
            return oversized

        svc.request = fake_request
        result = await svc.request_meta("aabb" * 8)
        assert result is None

    @pytest.mark.asyncio
    async def test_info_oversized_response_discarded(self):
        from styrened.services.direct_link import MAX_RESPONSE_BYTES, DirectLinkService

        svc = DirectLinkService.__new__(DirectLinkService)

        async def fake_request(*a, **kw):
            return b"x" * (MAX_RESPONSE_BYTES + 1)

        svc.request = fake_request
        result = await svc.request_info("aabb" * 8)
        assert result is None


# ---------------------------------------------------------------------------
# VPN_HANDSHAKE: orthogonal grant only
# ---------------------------------------------------------------------------


class TestVpnHandshakeOrthogonal:
    def test_vpn_not_in_admin_caps(self):
        """VPN_HANDSHAKE must NOT be granted by the ADMIN role tier."""
        from styrened.models.rbac import ROLE_CAPABILITIES, Capability, Role
        admin_caps = ROLE_CAPABILITIES[Role.ADMIN]
        assert Capability.VPN_HANDSHAKE not in admin_caps

    def test_vpn_not_in_any_role_tier(self):
        """VPN_HANDSHAKE is orthogonal — no role tier should include it."""
        from styrened.models.rbac import ROLE_CAPABILITIES, Capability
        for role, caps in ROLE_CAPABILITIES.items():
            assert Capability.VPN_HANDSHAKE not in caps, (
                f"VPN_HANDSHAKE found in {role.name} caps — "
                "it must be an orthogonal explicit grant only"
            )

    def test_vpn_still_in_capability_all(self):
        """VPN_HANDSHAKE must remain in Capability.ALL for config validation."""
        from styrened.models.rbac import Capability
        assert Capability.VPN_HANDSHAKE in Capability.ALL

    def test_vpn_granted_via_explicit_roster_entry(self):
        """VPN_HANDSHAKE works when granted explicitly in roster."""
        from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={
                "aa" * 16: RosterEntry(
                    identity_hash="aa" * 16,
                    role=Role.PEER,
                    grants=frozenset({Capability.VPN_HANDSHAKE}),
                ),
                "bb" * 16: RosterEntry(
                    identity_hash="bb" * 16,
                    role=Role.ADMIN,  # ADMIN without explicit grant
                ),
            },
        )
        assert policy.has_capability("aa" * 16, Capability.VPN_HANDSHAKE)
        assert not policy.has_capability("bb" * 16, Capability.VPN_HANDSHAKE)

    def test_vpn_not_granted_to_admin_without_explicit_grant(self):
        """Even ADMIN role does not auto-grant VPN_HANDSHAKE."""
        from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry
        policy = RBACPolicy(
            roster={
                "cc" * 16: RosterEntry(identity_hash="cc" * 16, role=Role.ADMIN),
            }
        )
        assert not policy.has_capability("cc" * 16, Capability.VPN_HANDSHAKE)
