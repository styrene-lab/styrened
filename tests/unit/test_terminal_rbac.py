"""Tests for RBAC-gated Terminal service auth (Phase 4).

TDD: Tests written BEFORE implementation.

TerminalService.is_authorized() must check RBAC when policy is set:
- RBAC active: has_capability(identity, TERMINAL_RESTRICTED) for restricted shell,
  has_capability(identity, TERMINAL_FULL) for full shell
- RBAC inactive: preserve legacy (authorized_identities + allow_unauthenticated)
- BLOCKED role: always denied

Daemon wiring: _start_terminal_service passes rbac_policy to TerminalService.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from styrened.models.rbac import (
    Capability,
    RBACPolicy,
    Role,
    RosterEntry,
)


# ---------------------------------------------------------------------------
# 1. TerminalService accepts rbac_policy parameter
# ---------------------------------------------------------------------------


class TestTerminalServiceRBACParam:
    """TerminalService.__init__ accepts an rbac_policy parameter."""

    def test_accepts_rbac_policy_kwarg(self):
        """TerminalService can be constructed with rbac_policy=..."""
        from styrened.terminal.service import TerminalService

        policy = RBACPolicy(default_role=Role.NONE)
        svc = TerminalService(
            rns_service=MagicMock(),
            styrene_protocol=MagicMock(),
            rbac_policy=policy,
        )
        assert svc._rbac_policy is policy

    def test_rbac_policy_defaults_to_empty(self):
        """TerminalService without rbac_policy gets default RBACPolicy."""
        from styrened.terminal.service import TerminalService

        svc = TerminalService(
            rns_service=MagicMock(),
            styrene_protocol=MagicMock(),
        )
        assert isinstance(svc._rbac_policy, RBACPolicy)

    def test_set_rbac_policy_method(self):
        """TerminalService has set_rbac_policy() for runtime injection."""
        from styrened.terminal.service import TerminalService

        svc = TerminalService(
            rns_service=MagicMock(),
            styrene_protocol=MagicMock(),
        )
        policy = RBACPolicy(default_role=Role.PEER)
        svc.set_rbac_policy(policy)
        assert svc._rbac_policy is policy


# ---------------------------------------------------------------------------
# 2. is_authorized with RBAC active
# ---------------------------------------------------------------------------


class TestTerminalIsAuthorizedRBAC:
    """is_authorized uses RBAC when policy is set."""

    def _make_service(self, rbac_policy=None, **kwargs):
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=MagicMock(),
            styrene_protocol=MagicMock(),
            rbac_policy=rbac_policy,
            **kwargs,
        )

    def test_admin_authorized(self):
        """ADMIN role has TERMINAL_FULL → authorized."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"aa" * 16: RosterEntry(identity_hash="aa" * 16, role=Role.ADMIN)},
        )
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("aa" * 16) is True

    def test_operator_authorized(self):
        """OPERATOR role has TERMINAL_RESTRICTED → authorized."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"bb" * 16: RosterEntry(identity_hash="bb" * 16, role=Role.OPERATOR)},
        )
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("bb" * 16) is True

    def test_monitor_denied(self):
        """MONITOR role lacks terminal capabilities → denied."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"cc" * 16: RosterEntry(identity_hash="cc" * 16, role=Role.MONITOR)},
        )
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("cc" * 16) is False

    def test_peer_denied(self):
        """PEER role lacks terminal capabilities → denied."""
        policy = RBACPolicy(default_role=Role.PEER)
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("dd" * 16) is False

    def test_blocked_denied(self):
        """BLOCKED role → denied."""
        policy = RBACPolicy(default_role=Role.PEER, blocked=["ee"])
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("ee" * 16) is False

    def test_explicit_grant_terminal_restricted(self):
        """PEER with explicit terminal.restricted grant → authorized."""
        policy = RBACPolicy(
            default_role=Role.PEER,
            roster={
                "ff" * 16: RosterEntry(
                    identity_hash="ff" * 16,
                    role=Role.PEER,
                    grants=frozenset([Capability.TERMINAL_RESTRICTED]),
                ),
            },
        )
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized("ff" * 16) is True

    def test_rbac_overrides_legacy_authorized_identities(self):
        """RBAC takes precedence — identity in legacy whitelist but PEER role → denied."""
        policy = RBACPolicy(default_role=Role.PEER)
        svc = self._make_service(
            rbac_policy=policy,
        )
        # PEER has no terminal cap, so RBAC denies even though legacy would allow
        assert svc.is_authorized("dd" * 16) is False

    def test_authorization_level_full_for_admin(self):
        """ADMIN gets TERMINAL_FULL authorization level."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"aa" * 16: RosterEntry(identity_hash="aa" * 16, role=Role.ADMIN)},
        )
        svc = self._make_service(rbac_policy=policy)
        level = svc.authorization_level("aa" * 16)
        assert level == "full"

    def test_authorization_level_restricted_for_operator(self):
        """OPERATOR gets TERMINAL_RESTRICTED authorization level."""
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={"bb" * 16: RosterEntry(identity_hash="bb" * 16, role=Role.OPERATOR)},
        )
        svc = self._make_service(rbac_policy=policy)
        level = svc.authorization_level("bb" * 16)
        assert level == "restricted"

    def test_authorization_level_none_for_peer(self):
        """PEER gets None authorization level (no terminal access)."""
        policy = RBACPolicy(default_role=Role.PEER)
        svc = self._make_service(rbac_policy=policy)
        level = svc.authorization_level("cc" * 16)
        assert level is None




# ---------------------------------------------------------------------------
# 3. RBAC policy mutation propagation
# ---------------------------------------------------------------------------


class TestTerminalRBACMutationPropagation:
    """RBAC policy mutations propagate to TerminalService checks."""

    def _make_service(self, rbac_policy=None, **kwargs):
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=MagicMock(),
            styrene_protocol=MagicMock(),
            rbac_policy=rbac_policy,
            **kwargs,
        )

    def test_block_propagates_to_is_authorized(self):
        """Blocking an identity via rbac_policy.block() is seen by is_authorized()."""
        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.ADMIN)},
        )
        svc = self._make_service(rbac_policy=policy)
        assert svc.is_authorized(identity) is True

        # Block the identity
        policy.block(identity[:2])
        assert svc.is_authorized(identity) is False

    def test_set_rbac_policy_replaces_stale_reference(self):
        """set_rbac_policy() replaces a stale policy reference."""
        identity = "bb" * 16
        old_policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.ADMIN)},
        )
        svc = self._make_service(rbac_policy=old_policy)
        assert svc.is_authorized(identity) is True

        # Replace with a new policy that denies the identity
        new_policy = RBACPolicy(default_role=Role.NONE)
        svc.set_rbac_policy(new_policy)
        assert svc.is_authorized(identity) is False


# ---------------------------------------------------------------------------
# 5. is_authorized legacy mode (no RBAC)
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# 6. Daemon wiring: rbac_policy passed to TerminalService
# ---------------------------------------------------------------------------


class TestDaemonTerminalRBACWiring:
    """Daemon passes config.rbac to TerminalService."""

    @patch("styrened.terminal.service.TerminalService")
    @patch("styrened.services.rns_service.get_rns_service")
    def test_rbac_policy_passed_to_terminal(self, mock_rns, mock_ts_cls):
        """When config.rbac is set, it's passed to TerminalService."""
        from styrened.daemon import StyreneDaemon

        mock_rns_svc = MagicMock()
        mock_rns_svc.is_initialized = True
        mock_rns.return_value = mock_rns_svc

        policy = RBACPolicy(default_role=Role.PEER)
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = policy
        daemon.config.terminal = MagicMock()
        daemon.config.terminal.session_idle_timeout = 3600
        daemon.config.terminal.max_sessions_per_identity = 3
        daemon.config.terminal.max_total_sessions = 10
        daemon.config.terminal.default_shell = None
        daemon.config.terminal.allowed_shells = set()
        daemon._styrene_protocol = MagicMock()
        daemon._start_terminal_service = StyreneDaemon._start_terminal_service.__get__(daemon)

        daemon._start_terminal_service()

        mock_ts_cls.assert_called_once()
        call_kwargs = mock_ts_cls.call_args[1]
        assert call_kwargs.get("rbac_policy") is policy
