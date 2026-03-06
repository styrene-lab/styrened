"""Unit tests for RBAC model and policy resolution."""

import pytest

from styrened.models.rbac import (
    ROLE_CAPABILITIES,
    Capability,
    RBACPolicy,
    Role,
    RosterEntry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HASH_ADMIN = "a" * 32
HASH_OPERATOR = "b" * 32
HASH_MONITOR = "c" * 32
HASH_PEER = "d" * 32
HASH_VPN_PEER = "e" * 32
HASH_UNKNOWN = "f" * 32
HASH_BLOCKED = "ca3e9813" + "0" * 24


@pytest.fixture
def policy() -> RBACPolicy:
    """A fully-populated RBAC policy for testing."""
    return RBACPolicy(
        default_role=Role.PEER,
        roster={
            HASH_ADMIN: RosterEntry(
                identity_hash=HASH_ADMIN, role=Role.ADMIN, label="admin node"
            ),
            HASH_OPERATOR: RosterEntry(
                identity_hash=HASH_OPERATOR, role=Role.OPERATOR, label="operator"
            ),
            HASH_MONITOR: RosterEntry(
                identity_hash=HASH_MONITOR, role=Role.MONITOR, label="monitor"
            ),
            HASH_PEER: RosterEntry(
                identity_hash=HASH_PEER, role=Role.PEER, label="peer"
            ),
            HASH_VPN_PEER: RosterEntry(
                identity_hash=HASH_VPN_PEER,
                role=Role.PEER,
                label="vpn peer",
                grants=frozenset({Capability.VPN_HANDSHAKE}),
            ),
        },
        blocked=["ca3e9813"],
    )


@pytest.fixture
def empty_policy() -> RBACPolicy:
    """A minimal policy with defaults."""
    return RBACPolicy()


# ---------------------------------------------------------------------------
# Role Resolution
# ---------------------------------------------------------------------------


class TestResolveRole:
    def test_explicit_admin(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role(HASH_ADMIN) == Role.ADMIN

    def test_explicit_operator(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role(HASH_OPERATOR) == Role.OPERATOR

    def test_explicit_monitor(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role(HASH_MONITOR) == Role.MONITOR

    def test_explicit_peer(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role(HASH_PEER) == Role.PEER

    def test_unknown_gets_default(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role(HASH_UNKNOWN) == Role.PEER

    def test_unknown_gets_none_when_default_none(self) -> None:
        p = RBACPolicy(default_role=Role.NONE)
        assert p.resolve_role(HASH_UNKNOWN) == Role.NONE

    def test_blocked_overrides_roster(self, policy: RBACPolicy) -> None:
        """A blocked identity is BLOCKED even if in the roster."""
        # Add blocked hash to roster as admin
        policy.roster[HASH_BLOCKED] = RosterEntry(
            identity_hash=HASH_BLOCKED, role=Role.ADMIN
        )
        assert policy.resolve_role(HASH_BLOCKED) == Role.BLOCKED

    def test_blocked_prefix_matching(self, policy: RBACPolicy) -> None:
        full_hash = "ca3e9813" + "ab" * 12
        assert policy.resolve_role(full_hash) == Role.BLOCKED

    def test_blocked_reverse_prefix(self, policy: RBACPolicy) -> None:
        """Short source_hash matches long blocked prefix."""
        policy.blocked.append("deadbeef12345678" + "0" * 16)
        assert policy.resolve_role("deadbeef12345678" + "0" * 16) == Role.BLOCKED

    def test_not_blocked_different_prefix(self, policy: RBACPolicy) -> None:
        assert policy.resolve_role("cb3e9813" + "0" * 24) != Role.BLOCKED


# ---------------------------------------------------------------------------
# Capability Checks
# ---------------------------------------------------------------------------


class TestHasCapability:
    def test_admin_has_exec(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_ADMIN, Capability.EXEC)

    def test_admin_has_all_role_capabilities(self, policy: RBACPolicy) -> None:
        """ADMIN role grants all role-derived capabilities.

        VPN_HANDSHAKE is an orthogonal grant (not role-derived) — it must be
        explicitly granted per-identity regardless of role.  See rbac.py.
        """
        from styrened.models.rbac import ROLE_CAPABILITIES, Role
        admin_role_caps = ROLE_CAPABILITIES[Role.ADMIN]
        for cap in admin_role_caps:
            assert policy.has_capability(HASH_ADMIN, cap), f"ADMIN missing role cap {cap}"
        # VPN_HANDSHAKE must NOT be auto-granted to ADMIN without explicit grant
        assert not policy.has_capability(HASH_ADMIN, Capability.VPN_HANDSHAKE), (
            "VPN_HANDSHAKE should not be auto-granted by ADMIN role — "
            "it is an orthogonal capability requiring explicit roster grant"
        )

    def test_operator_has_config_update(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_OPERATOR, Capability.CONFIG_UPDATE)

    def test_operator_lacks_exec(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_OPERATOR, Capability.EXEC)

    def test_operator_lacks_reboot(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_OPERATOR, Capability.REBOOT)

    def test_operator_has_terminal_restricted(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_OPERATOR, Capability.TERMINAL_RESTRICTED)

    def test_operator_lacks_terminal_full(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_OPERATOR, Capability.TERMINAL_FULL)

    def test_monitor_has_web_read(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_MONITOR, Capability.WEB_READ)

    def test_monitor_lacks_web_write(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_MONITOR, Capability.WEB_WRITE)

    def test_monitor_has_datalink(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_MONITOR, Capability.DATALINK_ESTABLISH)

    def test_peer_has_chat(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_PEER, Capability.CHAT_SEND)
        assert policy.has_capability(HASH_PEER, Capability.CHAT_RECEIVE)

    def test_peer_has_status(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_PEER, Capability.STATUS_QUERY)

    def test_peer_lacks_datalink(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_PEER, Capability.DATALINK_ESTABLISH)

    def test_peer_lacks_vpn_by_default(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_PEER, Capability.VPN_HANDSHAKE)

    def test_blocked_has_nothing(self, policy: RBACPolicy) -> None:
        for cap in Capability.ALL:
            assert not policy.has_capability(HASH_BLOCKED, cap), f"BLOCKED has {cap}"

    def test_none_has_nothing(self) -> None:
        p = RBACPolicy(default_role=Role.NONE)
        for cap in Capability.ALL:
            assert not p.has_capability(HASH_UNKNOWN, cap), f"NONE has {cap}"

    def test_unknown_gets_default_role_caps(self, policy: RBACPolicy) -> None:
        """Unrostered identity gets default_role capabilities."""
        assert policy.has_capability(HASH_UNKNOWN, Capability.CHAT_SEND)
        assert not policy.has_capability(HASH_UNKNOWN, Capability.EXEC)


# ---------------------------------------------------------------------------
# Explicit Grants (Orthogonal Capabilities)
# ---------------------------------------------------------------------------


class TestGrants:
    def test_vpn_grant_on_peer(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_VPN_PEER, Capability.VPN_HANDSHAKE)

    def test_vpn_peer_still_lacks_exec(self, policy: RBACPolicy) -> None:
        assert not policy.has_capability(HASH_VPN_PEER, Capability.EXEC)

    def test_vpn_peer_still_has_peer_caps(self, policy: RBACPolicy) -> None:
        assert policy.has_capability(HASH_VPN_PEER, Capability.CHAT_SEND)

    def test_effective_capabilities_includes_grants(self) -> None:
        entry = RosterEntry(
            identity_hash=HASH_VPN_PEER,
            role=Role.PEER,
            grants=frozenset({Capability.VPN_HANDSHAKE, Capability.DATALINK_ESTABLISH}),
        )
        eff = entry.effective_capabilities
        assert Capability.VPN_HANDSHAKE in eff
        assert Capability.DATALINK_ESTABLISH in eff
        assert Capability.CHAT_SEND in eff  # from PEER role
        assert Capability.EXEC not in eff


# ---------------------------------------------------------------------------
# Role Hierarchy (Cumulative)
# ---------------------------------------------------------------------------


class TestRoleHierarchy:
    def test_admin_includes_operator(self) -> None:
        admin = ROLE_CAPABILITIES[Role.ADMIN]
        operator = ROLE_CAPABILITIES[Role.OPERATOR]
        assert operator.issubset(admin)

    def test_operator_includes_monitor(self) -> None:
        operator = ROLE_CAPABILITIES[Role.OPERATOR]
        monitor = ROLE_CAPABILITIES[Role.MONITOR]
        assert monitor.issubset(operator)

    def test_monitor_includes_peer(self) -> None:
        monitor = ROLE_CAPABILITIES[Role.MONITOR]
        peer = ROLE_CAPABILITIES[Role.PEER]
        assert peer.issubset(monitor)

    def test_peer_does_not_include_monitor(self) -> None:
        peer = ROLE_CAPABILITIES[Role.PEER]
        monitor = ROLE_CAPABILITIES[Role.MONITOR]
        assert not monitor.issubset(peer)

    def test_each_tier_adds_capabilities(self) -> None:
        """Each role tier has strictly more capabilities than the one below."""
        assert len(ROLE_CAPABILITIES[Role.BLOCKED]) == 0
        assert len(ROLE_CAPABILITIES[Role.NONE]) == 0
        assert len(ROLE_CAPABILITIES[Role.PEER]) > 0
        assert len(ROLE_CAPABILITIES[Role.MONITOR]) > len(ROLE_CAPABILITIES[Role.PEER])
        assert len(ROLE_CAPABILITIES[Role.OPERATOR]) > len(ROLE_CAPABILITIES[Role.MONITOR])
        assert len(ROLE_CAPABILITIES[Role.ADMIN]) > len(ROLE_CAPABILITIES[Role.OPERATOR])


# ---------------------------------------------------------------------------
# Allow List Generation (RNS Integration)
# ---------------------------------------------------------------------------


class TestAllowList:
    def test_allow_list_returns_bytes(self, policy: RBACPolicy) -> None:
        result = policy.get_allow_list(Capability.EXEC)
        assert all(isinstance(h, bytes) for h in result)

    def test_allow_list_only_capable_identities(self, policy: RBACPolicy) -> None:
        result = policy.get_allow_list(Capability.EXEC)
        # Only admin has EXEC
        assert len(result) == 1
        assert result[0] == bytes.fromhex(HASH_ADMIN)

    def test_allow_list_multiple_identities(self, policy: RBACPolicy) -> None:
        result = policy.get_allow_list(Capability.CONFIG_UPDATE)
        hashes = {h.hex() for h in result}
        assert HASH_ADMIN in hashes
        assert HASH_OPERATOR in hashes
        assert HASH_MONITOR not in hashes

    def test_allow_list_cache(self, policy: RBACPolicy) -> None:
        r1 = policy.get_allow_list(Capability.EXEC)
        r2 = policy.get_allow_list(Capability.EXEC)
        assert r1 is r2  # same object from cache

    def test_allow_list_cache_invalidation(self, policy: RBACPolicy) -> None:
        r1 = policy.get_allow_list(Capability.EXEC)
        policy.invalidate_cache()
        r2 = policy.get_allow_list(Capability.EXEC)
        assert r1 is not r2  # new object after invalidation
        assert r1 == r2  # but same content

    def test_should_use_allow_all_when_default_grants(self, policy: RBACPolicy) -> None:
        # default_role=PEER, PEER has CHAT_SEND
        assert policy.should_use_allow_all(Capability.CHAT_SEND)

    def test_should_not_use_allow_all_for_exec(self, policy: RBACPolicy) -> None:
        assert not policy.should_use_allow_all(Capability.EXEC)

    def test_should_not_use_allow_all_when_default_none(self) -> None:
        p = RBACPolicy(default_role=Role.NONE)
        assert not p.should_use_allow_all(Capability.CHAT_SEND)

    def test_allow_list_includes_grants(self, policy: RBACPolicy) -> None:
        result = policy.get_allow_list(Capability.VPN_HANDSHAKE)
        hashes = {h.hex() for h in result}
        # VPN_HANDSHAKE is an orthogonal grant — ADMIN role alone is insufficient.
        # Only identities with an explicit 'grants: [vpn.handshake]' entry should appear.
        assert HASH_ADMIN not in hashes, (
            "ADMIN role must NOT auto-grant VPN_HANDSHAKE — "
            "explicit roster grant required"
        )
        assert HASH_VPN_PEER in hashes  # has explicit grant in test fixture


# ---------------------------------------------------------------------------
# Roster Mutations
# ---------------------------------------------------------------------------


class TestMutations:
    def test_add_entry(self, policy: RBACPolicy) -> None:
        new_hash = "1" * 32
        policy.add_entry(RosterEntry(identity_hash=new_hash, role=Role.OPERATOR))
        assert policy.resolve_role(new_hash) == Role.OPERATOR

    def test_remove_entry(self, policy: RBACPolicy) -> None:
        assert policy.remove_entry(HASH_ADMIN)
        assert policy.resolve_role(HASH_ADMIN) == Role.PEER  # falls to default

    def test_remove_nonexistent(self, policy: RBACPolicy) -> None:
        assert not policy.remove_entry("0" * 32)

    def test_block(self, policy: RBACPolicy) -> None:
        policy.block("deadbeef")
        assert policy.resolve_role("deadbeef" + "0" * 24) == Role.BLOCKED

    def test_block_idempotent(self, policy: RBACPolicy) -> None:
        policy.block("ca3e9813")  # already blocked
        assert policy.blocked.count("ca3e9813") == 1

    def test_unblock(self, policy: RBACPolicy) -> None:
        assert policy.unblock("ca3e9813")
        assert policy.resolve_role(HASH_BLOCKED) != Role.BLOCKED

    def test_unblock_nonexistent(self, policy: RBACPolicy) -> None:
        assert not policy.unblock("nonexistent")

    def test_add_invalidates_cache(self, policy: RBACPolicy) -> None:
        _ = policy.get_allow_list(Capability.EXEC)
        assert Capability.EXEC in policy._allow_list_cache
        policy.add_entry(RosterEntry(identity_hash="1" * 32, role=Role.ADMIN))
        assert Capability.EXEC not in policy._allow_list_cache


# ---------------------------------------------------------------------------
# Config Parsing Integration
# ---------------------------------------------------------------------------


class TestConfigParsing:
    def test_parse_rbac_minimal(self) -> None:
        """Config with no rbac section gets default policy."""
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        config = CoreConfig()
        policy = _parse_rbac({}, config)
        assert policy.default_role == Role.PEER
        assert len(policy.roster) == 0

    def test_parse_rbac_full_roster(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {
            "rbac": {
                "default_role": "monitor",
                "roster": [
                    {"identity": "a" * 32, "role": "admin", "label": "test admin"},
                    {"identity": "b" * 32, "role": "operator"},
                ],
                "blocked": ["ca3e9813"],
            }
        }
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        assert policy.default_role == Role.MONITOR
        assert len(policy.roster) == 2
        assert policy.roster["a" * 32].role == Role.ADMIN
        assert policy.roster["a" * 32].label == "test admin"
        assert policy.roster["b" * 32].role == Role.OPERATOR
        assert policy.blocked == ["ca3e9813"]

    def test_parse_rbac_with_grants(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {
            "rbac": {
                "roster": [
                    {
                        "identity": "a" * 32,
                        "role": "peer",
                        "grants": ["vpn.handshake", "datalink.establish"],
                    },
                ],
            }
        }
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        entry = policy.roster["a" * 32]
        assert Capability.VPN_HANDSHAKE in entry.grants
        assert Capability.DATALINK_ESTABLISH in entry.grants

    def test_parse_rbac_case_insensitive(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {"rbac": {"default_role": "ADMIN", "roster": []}}
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        assert policy.default_role == Role.ADMIN

    def test_parse_rbac_unknown_role_skipped(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {
            "rbac": {
                "roster": [{"identity": "a" * 32, "role": "superadmin"}],
            }
        }
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        assert len(policy.roster) == 0

    def test_parse_rbac_unknown_default_role_falls_to_peer(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {"rbac": {"default_role": "superuser"}}
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        assert policy.default_role == Role.PEER

    def test_parse_rbac_unknown_grant_skipped(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {
            "rbac": {
                "roster": [
                    {"identity": "a" * 32, "role": "peer", "grants": ["bogus.cap"]},
                ],
            }
        }
        config = CoreConfig()
        policy = _parse_rbac(data, config)
        assert len(policy.roster["a" * 32].grants) == 0


# ---------------------------------------------------------------------------
# Legacy Migration
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    def test_migrate_terminal_authorized_to_admin(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        config = CoreConfig()
        config.terminal.authorized_identities = {"a" * 32}
        policy = _parse_rbac({}, config)
        assert "a" * 32 in policy.roster
        assert policy.roster["a" * 32].role == Role.ADMIN

    def test_migrate_web_authorized_to_monitor(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        config = CoreConfig()
        config.api.auth.authorized_identities = {"b" * 32}
        policy = _parse_rbac({}, config)
        assert "b" * 32 in policy.roster
        assert policy.roster["b" * 32].role == Role.MONITOR

    def test_migrate_banned_peers_to_blocked(self) -> None:
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        config = CoreConfig()
        config.banned_peers = ["ca3e9813"]
        policy = _parse_rbac({}, config)
        assert "ca3e9813" in policy.blocked

    def test_migrate_no_duplicates(self) -> None:
        """Explicit roster entry takes precedence over migration."""
        from styrened.models.config import CoreConfig
        from styrened.services.config import _parse_rbac

        data = {
            "rbac": {
                "roster": [{"identity": "a" * 32, "role": "operator"}],
                "blocked": ["ca3e9813"],
            }
        }
        config = CoreConfig()
        config.terminal.authorized_identities = {"a" * 32}
        config.banned_peers = ["ca3e9813"]
        policy = _parse_rbac(data, config)
        # Explicit roster wins — stays operator, not migrated to admin
        assert policy.roster["a" * 32].role == Role.OPERATOR
        # No duplicate blocked entries
        assert policy.blocked.count("ca3e9813") == 1


# ---------------------------------------------------------------------------
# Serialization Round-Trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip_via_config(self) -> None:
        """RBAC policy survives save → load cycle."""
        import tempfile
        from pathlib import Path

        from styrened.models.config import CoreConfig
        from styrened.services.config import load_core_config, save_core_config

        policy = RBACPolicy(
            default_role=Role.MONITOR,
            roster={
                "a" * 32: RosterEntry(
                    identity_hash="a" * 32,
                    role=Role.ADMIN,
                    label="test admin",
                ),
                "b" * 32: RosterEntry(
                    identity_hash="b" * 32,
                    role=Role.PEER,
                    grants=frozenset({Capability.VPN_HANDSHAKE}),
                ),
            },
            blocked=["ca3e9813"],
        )

        config = CoreConfig()
        config.rbac = policy

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            save_core_config(config, path)
            loaded = load_core_config(path)

        assert loaded.rbac is not None
        assert loaded.rbac.default_role == Role.MONITOR
        assert len(loaded.rbac.roster) == 2
        assert loaded.rbac.roster["a" * 32].role == Role.ADMIN
        assert loaded.rbac.roster["a" * 32].label == "test admin"
        assert loaded.rbac.roster["b" * 32].role == Role.PEER
        assert Capability.VPN_HANDSHAKE in loaded.rbac.roster["b" * 32].grants
        assert loaded.rbac.blocked == ["ca3e9813"]


# ---------------------------------------------------------------------------
# Capability Registry Integrity
# ---------------------------------------------------------------------------


class TestCapabilityRegistry:
    def test_all_capabilities_in_registry(self) -> None:
        """Every capability constant is in Capability.ALL."""
        for attr in dir(Capability):
            if attr.startswith("_") or attr == "ALL":
                continue
            val = getattr(Capability, attr)
            if isinstance(val, str):
                assert val in Capability.ALL, f"{attr}={val} not in Capability.ALL"

    def test_all_capabilities_in_some_role(self) -> None:
        """Every non-orthogonal capability is granted by at least one role.

        VPN_HANDSHAKE is the only orthogonal capability — it is intentionally
        absent from ROLE_CAPABILITIES and only grantable via explicit roster
        entries.  All other capabilities must be reachable through some role.
        """
        # Capabilities that are purely orthogonal (not in any role tier)
        orthogonal_caps = {Capability.VPN_HANDSHAKE}

        all_granted = set()
        for caps in ROLE_CAPABILITIES.values():
            all_granted |= caps
        for cap in Capability.ALL:
            if cap in orthogonal_caps:
                # Must NOT be in any role — orthogonal means explicit grant only
                assert cap not in all_granted, (
                    f"{cap} is documented as orthogonal but appears in ROLE_CAPABILITIES"
                )
            else:
                assert cap in all_granted, f"{cap} not granted by any role"

    def test_no_duplicate_capability_values(self) -> None:
        """All capability string values are unique."""
        seen: set[str] = set()
        for cap in Capability.ALL:
            assert cap not in seen, f"Duplicate capability value: {cap}"
            seen.add(cap)
