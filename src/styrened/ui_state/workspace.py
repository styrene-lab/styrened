"""Canonical workspace and peer-routing state.

These types capture aggregate workspace identity and origin-aware peer
workspace routing without depending on any frontend framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkspaceId(str, Enum):
    """Stable aggregate workspace identifiers."""

    HOME = "home"
    NODES = "nodes"
    MAIL = "mail"
    COMMS = "comms"
    CONTACTS = "contacts"
    ADMIN = "admin"


class PeerWorkspaceFocus(str, Enum):
    """Requested focus within the peer workspace."""

    STATUS = "status"
    MAIL = "mail"
    COMMS = "comms"
    PAGES = "pages"
    OPS = "ops"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class PeerWorkspaceContext:
    """Origin-aware drill-down context for a selected peer."""

    peer_identity_hash: str
    origin_workspace: WorkspaceId
    focus: PeerWorkspaceFocus = PeerWorkspaceFocus.STATUS


_TAB_TO_FOCUS: dict[str, PeerWorkspaceFocus] = {
    "status": PeerWorkspaceFocus.STATUS,
    "chat": PeerWorkspaceFocus.COMMS,
    "mail": PeerWorkspaceFocus.MAIL,
    "pages": PeerWorkspaceFocus.PAGES,
    "fleet-ops": PeerWorkspaceFocus.OPS,
    "ops": PeerWorkspaceFocus.OPS,
    "terminal": PeerWorkspaceFocus.TERMINAL,
}


def _coerce_workspace(value: WorkspaceId | str | None) -> WorkspaceId:
    if isinstance(value, WorkspaceId):
        return value
    if value is None:
        return WorkspaceId.HOME
    try:
        return WorkspaceId(str(value).lower())
    except ValueError:
        return WorkspaceId.HOME


def _coerce_focus(value: PeerWorkspaceFocus | str | None) -> PeerWorkspaceFocus:
    if isinstance(value, PeerWorkspaceFocus):
        return value
    if value is None:
        return PeerWorkspaceFocus.STATUS
    normalized = str(value).lower()
    if normalized in _TAB_TO_FOCUS:
        return _TAB_TO_FOCUS[normalized]
    try:
        return PeerWorkspaceFocus(normalized)
    except ValueError:
        return PeerWorkspaceFocus.STATUS


def build_peer_workspace_context(
    peer_identity_hash: str,
    origin_workspace: WorkspaceId | str | None,
    *,
    focus: PeerWorkspaceFocus | str | None = None,
) -> PeerWorkspaceContext:
    """Build canonical origin-aware context for a peer workspace."""
    return PeerWorkspaceContext(
        peer_identity_hash=peer_identity_hash,
        origin_workspace=_coerce_workspace(origin_workspace),
        focus=_coerce_focus(focus),
    )
