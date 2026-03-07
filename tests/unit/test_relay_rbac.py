"""Tests for relay RBAC capabilities.

TDD: written before implementation per project convention.
"""

import pytest

from styrened.models.rbac import Capability, Role, ROLE_CAPABILITIES, RBACPolicy, RosterEntry


# --- Capability constants exist ---

class TestRelayCapabilitiesExist:
    """All 10 relay.* capability constants are defined."""

    # PEER tier
    def test_relay_request_exists(self):
        assert Capability.RELAY_REQUEST == "relay.request"

    def test_relay_list_exists(self):
        assert Capability.RELAY_LIST == "relay.list"

    def test_relay_teardown_exists(self):
        assert Capability.RELAY_TEARDOWN == "relay.teardown"

    def test_relay_accept_exists(self):
        assert Capability.RELAY_ACCEPT == "relay.accept"

    def test_relay_reject_exists(self):
        assert Capability.RELAY_REJECT == "relay.reject"

    # OPERATOR tier
    def test_relay_request_permanent_exists(self):
        assert Capability.RELAY_REQUEST_PERMANENT == "relay.request_permanent"

    def test_relay_accept_permanent_exists(self):
        assert Capability.RELAY_ACCEPT_PERMANENT == "relay.accept_permanent"

    def test_relay_prioritize_exists(self):
        assert Capability.RELAY_PRIORITIZE == "relay.prioritize"

    def test_relay_bridge_exists(self):
        assert Capability.RELAY_BRIDGE == "relay.bridge"

    # ADMIN tier
    def test_relay_admin_exists(self):
        assert Capability.RELAY_ADMIN == "relay.admin"


class TestRelayCapabilitiesInALL:
    """All 10 relay.* strings are in Capability.ALL."""

    RELAY_CAPS = [
        "relay.request", "relay.list", "relay.teardown",
        "relay.accept", "relay.reject",
        "relay.request_permanent", "relay.accept_permanent",
        "relay.prioritize", "relay.bridge",
        "relay.admin",
    ]

    @pytest.mark.parametrize("cap", RELAY_CAPS)
    def test_in_all(self, cap):
        assert cap in Capability.ALL


class TestRelayCapabilityTiers:
    """Relay capabilities appear at the correct role tier."""

    # PEER tier includes relay.request, .list, .teardown, .accept, .reject
    @pytest.mark.parametrize("cap", [
        "relay.request", "relay.list", "relay.teardown",
        "relay.accept", "relay.reject",
    ])
    def test_peer_tier_has_relay_caps(self, cap):
        assert cap in ROLE_CAPABILITIES[Role.PEER]

    # OPERATOR tier includes relay.request_permanent, .accept_permanent, .prioritize, .bridge
    @pytest.mark.parametrize("cap", [
        "relay.request_permanent", "relay.accept_permanent",
        "relay.prioritize", "relay.bridge",
    ])
    def test_operator_tier_has_relay_caps(self, cap):
        assert cap in ROLE_CAPABILITIES[Role.OPERATOR]

    # ADMIN tier includes relay.admin
    def test_admin_tier_has_relay_admin(self):
        assert "relay.admin" in ROLE_CAPABILITIES[Role.ADMIN]

    # PEER tier does NOT have operator-level caps
    @pytest.mark.parametrize("cap", [
        "relay.request_permanent", "relay.accept_permanent",
        "relay.prioritize", "relay.bridge",
    ])
    def test_peer_tier_lacks_operator_relay_caps(self, cap):
        assert cap not in ROLE_CAPABILITIES[Role.PEER]

    # NONE/BLOCKED have no relay caps
    @pytest.mark.parametrize("cap", [
        "relay.request", "relay.list", "relay.teardown",
        "relay.accept", "relay.reject",
        "relay.request_permanent", "relay.accept_permanent",
        "relay.prioritize", "relay.bridge",
        "relay.admin",
    ])
    def test_none_tier_lacks_all_relay_caps(self, cap):
        assert cap not in ROLE_CAPABILITIES[Role.NONE]

    def test_blocked_tier_lacks_all_relay_caps(self):
        for cap in ["relay.request", "relay.admin"]:
            assert cap not in ROLE_CAPABILITIES[Role.BLOCKED]


class TestRelayHasCapability:
    """has_capability() correctly gates relay capabilities."""

    def _policy(self, default_role=Role.PEER, roster=None):
        return RBACPolicy(default_role=default_role, roster=roster or {})

    def test_peer_can_relay_request(self):
        policy = self._policy(default_role=Role.PEER)
        assert policy.has_capability("test_hash", Capability.RELAY_REQUEST)

    def test_none_cannot_relay_request(self):
        policy = self._policy(default_role=Role.NONE)
        assert not policy.has_capability("test_hash", Capability.RELAY_REQUEST)

    def test_operator_can_relay_request_permanent(self):
        policy = self._policy(default_role=Role.OPERATOR)
        assert policy.has_capability("test_hash", Capability.RELAY_REQUEST_PERMANENT)

    def test_peer_cannot_relay_request_permanent(self):
        policy = self._policy(default_role=Role.PEER)
        assert not policy.has_capability("test_hash", Capability.RELAY_REQUEST_PERMANENT)

    def test_admin_can_relay_admin(self):
        policy = self._policy(default_role=Role.ADMIN)
        assert policy.has_capability("test_hash", Capability.RELAY_ADMIN)

    def test_operator_cannot_relay_admin(self):
        policy = self._policy(default_role=Role.OPERATOR)
        assert not policy.has_capability("test_hash", Capability.RELAY_ADMIN)

    def test_roster_grant_overrides(self):
        """A PEER-role identity with explicit relay.request_permanent grant gets it."""
        policy = self._policy(
            default_role=Role.NONE,
            roster={
                "special": RosterEntry(
                    identity_hash="special",
                    role=Role.PEER,
                    grants=frozenset([Capability.RELAY_REQUEST_PERMANENT]),
                )
            },
        )
        assert policy.has_capability("special", Capability.RELAY_REQUEST_PERMANENT)
        assert policy.has_capability("special", Capability.RELAY_REQUEST)  # from PEER role


class TestCumulativeHierarchy:
    """Higher tiers include lower-tier relay capabilities."""

    PEER_RELAY = ["relay.request", "relay.list", "relay.teardown", "relay.accept", "relay.reject"]

    @pytest.mark.parametrize("cap", PEER_RELAY)
    def test_operator_inherits_peer_relay(self, cap):
        assert cap in ROLE_CAPABILITIES[Role.OPERATOR]

    @pytest.mark.parametrize("cap", PEER_RELAY)
    def test_admin_inherits_peer_relay(self, cap):
        assert cap in ROLE_CAPABILITIES[Role.ADMIN]

    @pytest.mark.parametrize("cap", [
        "relay.request_permanent", "relay.accept_permanent",
        "relay.prioritize", "relay.bridge",
    ])
    def test_admin_inherits_operator_relay(self, cap):
        assert cap in ROLE_CAPABILITIES[Role.ADMIN]
