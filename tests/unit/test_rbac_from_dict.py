"""Tests for RBACPolicy.from_dict() deserialization."""

from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry


class TestRBACPolicyFromDict:
    """RBACPolicy.from_dict round-trips the serialized config format."""

    def test_empty_dict_returns_default(self) -> None:
        policy = RBACPolicy.from_dict({})
        assert policy.default_role == Role.PEER
        assert policy.roster == {}
        assert policy.blocked == []

    def test_none_returns_default(self) -> None:
        # Edge: callers may pass None when config section is missing
        policy = RBACPolicy.from_dict(None)  # type: ignore[arg-type]
        assert policy.default_role == Role.PEER
        assert policy.roster == {}
        assert policy.blocked == []

    def test_default_role_parsed(self) -> None:
        policy = RBACPolicy.from_dict({"default_role": "admin"})
        assert policy.default_role == Role.ADMIN

    def test_unknown_default_role_falls_back_to_peer(self) -> None:
        policy = RBACPolicy.from_dict({"default_role": "superuser"})
        assert policy.default_role == Role.PEER

    def test_roster_entry_parsed(self) -> None:
        data = {
            "roster": [
                {"identity": "aabbccdd" * 4, "role": "operator", "label": "Node A"},
            ],
        }
        policy = RBACPolicy.from_dict(data)
        ih = "aabbccdd" * 4
        assert ih in policy.roster
        assert policy.roster[ih].role == Role.OPERATOR
        assert policy.roster[ih].label == "Node A"

    def test_roster_entry_with_grants(self) -> None:
        data = {
            "roster": [
                {
                    "identity": "11223344" * 4,
                    "role": "peer",
                    "grants": ["vpn.handshake"],
                },
            ],
        }
        policy = RBACPolicy.from_dict(data)
        entry = policy.roster["11223344" * 4]
        assert Capability.VPN_HANDSHAKE in entry.grants

    def test_blocked_list_parsed(self) -> None:
        policy = RBACPolicy.from_dict({"blocked": ["deadbeef", "cafebabe"]})
        assert policy.blocked == ["deadbeef", "cafebabe"]

    def test_full_round_trip(self) -> None:
        """Verify from_dict matches the format produced by serialize_config."""
        original = RBACPolicy(
            default_role=Role.MONITOR,
            roster={
                "aabb" * 8: RosterEntry(
                    identity_hash="aabb" * 8,
                    role=Role.ADMIN,
                    label="Hub",
                    grants=frozenset({Capability.VPN_HANDSHAKE}),
                ),
            },
            blocked=["dead"],
        )
        # Simulate serialize_config output format
        serialized = {
            "default_role": original.default_role.name.lower(),
            "roster": [
                {
                    "identity": entry.identity_hash,
                    "role": entry.role.name.lower(),
                    "label": entry.label,
                    "grants": sorted(entry.grants),
                }
                for entry in original.roster.values()
            ],
            "blocked": original.blocked,
        }
        reconstructed = RBACPolicy.from_dict(serialized)
        assert reconstructed.default_role == original.default_role
        assert reconstructed.blocked == original.blocked
        ih = "aabb" * 8
        assert reconstructed.roster[ih].role == original.roster[ih].role
        assert reconstructed.roster[ih].label == original.roster[ih].label
        assert reconstructed.roster[ih].grants == original.roster[ih].grants

    def test_skips_entry_with_empty_identity(self) -> None:
        data = {"roster": [{"identity": "", "role": "peer"}]}
        policy = RBACPolicy.from_dict(data)
        assert policy.roster == {}

    def test_skips_entry_with_unknown_role(self) -> None:
        data = {"roster": [{"identity": "aabb" * 8, "role": "godmode"}]}
        policy = RBACPolicy.from_dict(data)
        assert policy.roster == {}
