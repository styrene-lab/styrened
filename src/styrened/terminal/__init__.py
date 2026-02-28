"""Terminal session support for Styrene.

This module provides interactive terminal sessions over RNS, using a hybrid
architecture:

    Control Plane (LXMF/Styrene):
        - Session request/accept/reject
        - Window resize notifications
        - Signal delivery
        - Session close/cleanup

    Data Plane (RNS Link):
        - Bidirectional terminal I/O
        - Low-latency stream data
        - Reliable delivery via RNS

The architecture follows patterns established by rnsh, but integrates with
Styrene's existing LXMF-based authorization and fleet management.

Usage (server/styrened):
    from styrened.terminal import TerminalService

    service = TerminalService(
        rns_service=rns_service,
        authorized_identities={"abc123...", "def456..."},
    )
    service.start()

Usage (client/TUI):
    from styrened.terminal import TerminalClient

    client = TerminalClient(styrene_protocol)
    session = await client.connect(destination)
    await session.run_interactive()
"""

from styrened.terminal.client import TerminalClient, TerminalClientSession
from styrened.terminal.messages import (
    CommandExited,
    Error,
    Noop,
    StreamData,
    TerminalMessageType,
    VersionInfo,
    WindowSize,
    deserialize_message,
    register_message_types,
    serialize_message,
)

# Legacy alias — TerminalMessage was the old base class, now MessageBase
from RNS.Channel import MessageBase as TerminalMessage
from styrened.terminal.service import TerminalService, TerminalSession

__all__ = [
    # Client
    "TerminalClient",
    "TerminalClientSession",
    # Service (server)
    "TerminalService",
    "TerminalSession",
    # Data plane messages
    "TerminalMessage",
    "TerminalMessageType",
    "StreamData",
    "WindowSize",
    "CommandExited",
    "VersionInfo",
    "Error",
    "Noop",
    # Serialization
    "serialize_message",
    "deserialize_message",
    "register_message_types",
]
