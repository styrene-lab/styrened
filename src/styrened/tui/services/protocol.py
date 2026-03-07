"""Typed service protocol for TUI screens and widgets.

Defines ``TUIServices`` — the single typed interface through which all
screens and widgets access daemon functionality.  Replaces the implicit
``self.app._lifecycle.ipc_bridge`` pattern with a proper contract.

The protocol is deliberately minimal: it exposes the IPC bridge for
async daemon calls, and a handful of synchronously-cached properties
for data that screens read frequently (identity, unread counts).

Usage in screens / widgets::

    @property
    def services(self) -> TUIServices:
        return self.app.services  # typed, no type: ignore
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from styrened.tui.services.ipc_bridge import IPCBridge


@runtime_checkable
class TUIServices(Protocol):
    """Contract between TUI screens/widgets and the daemon.

    Implemented by ``StyreneApp``.  Screens access this via
    ``self.app.services`` — a typed property that avoids reaching
    into private attributes.
    """

    @property
    def bridge(self) -> IPCBridge:
        """IPC bridge for async daemon calls.

        All daemon interaction (chat, devices, config, relay, etc.)
        flows through the bridge.  Never access the bridge via
        ``app._lifecycle`` — always go through this property.
        """
        ...

    @property
    def local_identity_hash(self) -> str:
        """The local operator's RNS identity hash (hex string).

        Empty string when not yet initialized.
        """
        ...
