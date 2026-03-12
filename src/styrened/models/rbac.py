"""Role-based access control model for Styrene identity authorization.

Provides a unified authorization model that replaces the per-subsystem
identity whitelists (RPC authorized_identities, Terminal authorized_identities,
Web API auth, DirectLink ALLOW_ALL, LXMF blocklist).

Design:
    - Hierarchical roles: BLOCKED < NONE < PEER < MONITOR < OPERATOR < ADMIN
    - Each role grants a cumulative set of capabilities
    - Orthogonal capability grants (e.g., VPN) can be added per-identity
    - Single roster in core-config.yaml is the source of truth
    - No wire protocol changes — entirely local policy

Usage:
    policy = RBACPolicy(
        default_role=Role.PEER,
        roster={"abc123...": RosterEntry(identity_hash="abc123...", role=Role.ADMIN)},
        blocked=["ca3e9813"],
    )

    if policy.has_capability(source_hash, Capability.EXEC):
        # allow exec
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import ClassVar

logger = logging.getLogger(__name__)


class Role(IntEnum):
    """Hierarchical role levels. Higher value = more privilege."""

    BLOCKED = 0
    NONE = 1
    PEER = 10
    MONITOR = 20
    OPERATOR = 30
    ADMIN = 40


class Capability:
    """Fine-grained capabilities as string constants.

    String values used for config readability (e.g., ``grants: [vpn.handshake]``).
    Grouped by the minimum role tier that includes them.
    """

    # --- PEER tier (10) ---
    CHAT_SEND: ClassVar[str] = "chat.send"
    CHAT_RECEIVE: ClassVar[str] = "chat.receive"
    PAGE_BROWSE: ClassVar[str] = "page.browse"
    PING: ClassVar[str] = "rpc.ping"
    STATUS_QUERY: ClassVar[str] = "rpc.status"
    DATALINK_PING: ClassVar[str] = "datalink.ping"
    DATALINK_META: ClassVar[str] = "datalink.meta"
    DATALINK_INFO: ClassVar[str] = "datalink.info"
    DATALINK_STATUS: ClassVar[str] = "datalink.status"

    # --- MONITOR tier (20) ---
    INBOX_READ: ClassVar[str] = "rpc.inbox_read"
    WEB_READ: ClassVar[str] = "web.read"
    DATALINK_ESTABLISH: ClassVar[str] = "datalink.establish"
    DATALINK_SPEEDTEST: ClassVar[str] = "datalink.speedtest"

    # --- OPERATOR tier (30) ---
    CONFIG_UPDATE: ClassVar[str] = "rpc.config_update"
    TERMINAL_RESTRICTED: ClassVar[str] = "terminal.restricted"
    WEB_WRITE: ClassVar[str] = "web.write"

    # --- ADMIN tier (40) ---
    EXEC: ClassVar[str] = "rpc.exec"
    REBOOT: ClassVar[str] = "rpc.reboot"
    SELF_UPDATE: ClassVar[str] = "rpc.self_update"
    TERMINAL_FULL: ClassVar[str] = "terminal.full"

    # --- PEER tier (10) --- relay
    RELAY_REQUEST: ClassVar[str] = "relay.request"
    RELAY_LIST: ClassVar[str] = "relay.list"
    RELAY_TEARDOWN: ClassVar[str] = "relay.teardown"
    RELAY_ACCEPT: ClassVar[str] = "relay.accept"
    RELAY_REJECT: ClassVar[str] = "relay.reject"

    # --- OPERATOR tier (30) --- relay
    RELAY_REQUEST_PERMANENT: ClassVar[str] = "relay.request_permanent"
    RELAY_ACCEPT_PERMANENT: ClassVar[str] = "relay.accept_permanent"
    RELAY_PRIORITIZE: ClassVar[str] = "relay.prioritize"
    RELAY_BRIDGE: ClassVar[str] = "relay.bridge"

    # --- ADMIN tier (40) --- adapter
    ADAPTER_PROVISION: ClassVar[str] = "adapter.provision"

    # --- ADMIN tier (40) --- relay
    RELAY_ADMIN: ClassVar[str] = "relay.admin"

    # --- Orthogonal grants (not part of role hierarchy) ---
    VPN_HANDSHAKE: ClassVar[str] = "vpn.handshake"

    # Registry of all valid capability strings
    ALL: ClassVar[frozenset[str]] = frozenset()  # populated below


# Build ALL registry from class attributes
Capability.ALL = frozenset(
    v
    for k, v in vars(Capability).items()
    if isinstance(v, str) and not k.startswith("_") and k != "ALL"
)


# Cumulative role → capabilities mapping
_PEER_CAPS: frozenset[str] = frozenset(
    {
        Capability.CHAT_SEND,
        Capability.CHAT_RECEIVE,
        Capability.PAGE_BROWSE,
        Capability.PING,
        Capability.STATUS_QUERY,
        Capability.DATALINK_PING,
        Capability.DATALINK_META,
        Capability.DATALINK_INFO,
        Capability.DATALINK_STATUS,
        Capability.RELAY_REQUEST,
        Capability.RELAY_LIST,
        Capability.RELAY_TEARDOWN,
        Capability.RELAY_ACCEPT,
    }
)

_MONITOR_CAPS: frozenset[str] = _PEER_CAPS | frozenset(
    {
        Capability.INBOX_READ,
        Capability.WEB_READ,
        Capability.DATALINK_ESTABLISH,
        Capability.DATALINK_SPEEDTEST,
    }
)

_OPERATOR_CAPS: frozenset[str] = _MONITOR_CAPS | frozenset(
    {
        Capability.CONFIG_UPDATE,
        Capability.TERMINAL_RESTRICTED,
        Capability.WEB_WRITE,
        Capability.RELAY_REQUEST_PERMANENT,
        Capability.RELAY_ACCEPT_PERMANENT,
        Capability.RELAY_PRIORITIZE,
        Capability.RELAY_BRIDGE,
    }
)

_ADMIN_CAPS: frozenset[str] = _OPERATOR_CAPS | frozenset(
    {
        Capability.EXEC,
        Capability.REBOOT,
        Capability.SELF_UPDATE,
        Capability.TERMINAL_FULL,
        Capability.ADAPTER_PROVISION,
        Capability.RELAY_ADMIN,
        # NOTE: VPN_HANDSHAKE is intentionally NOT in _ADMIN_CAPS.
        # It is a pure orthogonal grant — an identity must be given explicit
        # ``grants: [vpn.handshake]`` in the roster regardless of role tier.
        # This prevents all ADMIN-role nodes from automatically receiving VPN
        # access; the operator must explicitly opt each identity in.
    }
)

ROLE_CAPABILITIES: dict[Role, frozenset[str]] = {
    Role.BLOCKED: frozenset(),
    Role.NONE: frozenset(),
    Role.PEER: _PEER_CAPS,
    Role.MONITOR: _MONITOR_CAPS,
    Role.OPERATOR: _OPERATOR_CAPS,
    Role.ADMIN: _ADMIN_CAPS,
}


@dataclass(frozen=True)
class RosterEntry:
    """A single identity's role assignment.

    Attributes:
        identity_hash: 32-char hex identity hash.
        role: Assigned role level.
        label: Human-readable label (optional, for config readability).
        grants: Explicit capability grants beyond the role's defaults.
    """

    identity_hash: str
    role: Role
    label: str = ""
    grants: frozenset[str] = field(default_factory=frozenset)

    @property
    def effective_capabilities(self) -> frozenset[str]:
        """All capabilities: role-derived + explicit grants."""
        return ROLE_CAPABILITIES[self.role] | self.grants


@dataclass
class RBACPolicy:
    """Central authorization policy for a styrened instance.

    Resolves identity hashes to roles and checks capabilities.
    Thread-safe for reads after initialization. Mutations (roster changes)
    should call ``invalidate_cache()`` afterward.

    Attributes:
        default_role: Role for identities not in the roster.
        roster: Map of identity_hash → RosterEntry.
        blocked: List of identity hash prefixes to block.
    """

    default_role: Role = Role.PEER
    roster: dict[str, RosterEntry] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)

    # Cached RNS-format allow lists per capability
    _allow_list_cache: dict[str, list[bytes]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def resolve_role(self, identity_hash: str) -> Role:
        """Resolve the effective role for an identity.

        Check order: blocked list (prefix match) → explicit roster → default role.

        Args:
            identity_hash: Hex identity hash to resolve.

        Returns:
            The effective Role for this identity.
        """
        # Blocked check (prefix matching, same semantics as existing banned_peers)
        for prefix in self.blocked:
            if identity_hash.startswith(prefix) or prefix.startswith(identity_hash):
                return Role.BLOCKED

        # Explicit roster lookup
        entry = self.roster.get(identity_hash)
        if entry is not None:
            return entry.role

        return self.default_role

    def has_capability(self, identity_hash: str, cap: str) -> bool:
        """Check if an identity has a specific capability.

        Args:
            identity_hash: Hex identity hash to check.
            cap: Capability string (e.g., ``Capability.EXEC``).

        Returns:
            True if the identity holds the capability.
        """
        role = self.resolve_role(identity_hash)
        if role == Role.BLOCKED:
            return False

        # Check role-derived capabilities
        if cap in ROLE_CAPABILITIES.get(role, frozenset()):
            return True

        # Check explicit grants for rostered identities
        entry = self.roster.get(identity_hash)
        if entry is not None and cap in entry.grants:
            return True

        return False

    def get_allow_list(self, cap: str) -> list[bytes]:
        """Get RNS-format allowed_list for a capability.

        Returns list of identity hashes (as bytes) for identities that hold
        the given capability. For use with::

            RNS.Destination.register_request_handler(
                allow=RNS.Destination.ALLOW_LIST,
                allowed_list=policy.get_allow_list(cap),
            )

        Note:
            Only includes explicitly rostered identities. If ``default_role``
            grants the capability, use ``should_use_allow_all()`` to check
            and pass ``ALLOW_ALL`` instead.

        Args:
            cap: Capability string.

        Returns:
            List of identity hash bytes.
        """
        if cap in self._allow_list_cache:
            return self._allow_list_cache[cap]

        result: list[bytes] = []
        for entry in self.roster.values():
            if entry.role == Role.BLOCKED:
                continue
            if cap in entry.effective_capabilities:
                result.append(bytes.fromhex(entry.identity_hash))
        self._allow_list_cache[cap] = result
        return result

    def should_use_allow_all(self, cap: str) -> bool:
        """Check if default_role grants this capability.

        When True, request handlers should use ``ALLOW_ALL`` instead of
        ``ALLOW_LIST``, because unidentified peers also have access.

        Args:
            cap: Capability string.

        Returns:
            True if the default role includes this capability.
        """
        return cap in ROLE_CAPABILITIES.get(self.default_role, frozenset())

    def invalidate_cache(self) -> None:
        """Clear allow list caches. Call after any roster mutation."""
        self._allow_list_cache.clear()

    def add_entry(self, entry: RosterEntry) -> None:
        """Add or replace a roster entry.

        Args:
            entry: RosterEntry to add.
        """
        self.roster[entry.identity_hash] = entry
        self.invalidate_cache()

    def remove_entry(self, identity_hash: str) -> bool:
        """Remove a roster entry.

        Args:
            identity_hash: Identity to remove.

        Returns:
            True if the entry existed and was removed.
        """
        if identity_hash in self.roster:
            del self.roster[identity_hash]
            self.invalidate_cache()
            return True
        return False

    def block(self, prefix: str) -> None:
        """Add an identity hash prefix to the blocked list.

        Args:
            prefix: Hex prefix to block (prefix matching).
        """
        if prefix not in self.blocked:
            self.blocked.append(prefix)
            self.invalidate_cache()

    def unblock(self, prefix: str) -> bool:
        """Remove a prefix from the blocked list.

        Args:
            prefix: Hex prefix to unblock.

        Returns:
            True if the prefix was in the list and removed.
        """
        if prefix in self.blocked:
            self.blocked.remove(prefix)
            self.invalidate_cache()
            return True
        return False

    @classmethod
    def from_dict(cls, data: dict) -> RBACPolicy:
        """Deserialize an RBACPolicy from a serialized config dict.

        Accepts the format produced by ``serialize_config`` in
        ``services/config.py``::

            {
                "default_role": "peer",
                "roster": [
                    {"identity": "abc123...", "role": "admin", "label": "...", "grants": [...]},
                ],
                "blocked": ["deadbeef"],
            }

        Args:
            data: Serialized RBAC dict (the ``rbac`` section of a config).

        Returns:
            Reconstructed RBACPolicy.
        """
        if not data:
            return cls()

        # Parse default_role
        default_role_str = str(data.get("default_role", "peer")).upper()
        try:
            default_role = Role[default_role_str]
        except KeyError:
            logger.warning("Unknown RBAC default_role '%s', using PEER", default_role_str)
            default_role = Role.PEER

        # Parse roster
        roster: dict[str, RosterEntry] = {}
        for entry_data in data.get("roster", []):
            identity = str(entry_data.get("identity", "")).lower().strip()
            if not identity:
                continue
            role_str = str(entry_data.get("role", "peer")).upper()
            try:
                role = Role[role_str]
            except KeyError:
                logger.warning("Unknown role '%s' for %s, skipping", role_str, identity[:16])
                continue
            label = str(entry_data.get("label", ""))
            grants_raw = entry_data.get("grants", [])
            grants = frozenset(
                str(g).strip() for g in grants_raw if str(g).strip() in Capability.ALL
            )
            roster[identity] = RosterEntry(
                identity_hash=identity, role=role, label=label, grants=grants,
            )

        # Parse blocked list
        blocked = [
            str(h).lower().strip() for h in data.get("blocked", []) if h
        ]

        return cls(default_role=default_role, roster=roster, blocked=blocked)
