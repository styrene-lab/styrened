"""Protocol abstraction layer for LXMF messaging.

This package provides the infrastructure for multiplexing different
protocol types (chat, RPC, styrene) over LXMF messages.
"""
from __future__ import annotations


# Re-export from styrene-core (all protocols migrated)
from styrened.protocols.base import LXMFMessage, Protocol
from styrened.protocols.chat import ChatProtocol
from styrened.protocols.registry import ProtocolNotFoundError, ProtocolRegistry
from styrened.protocols.styrene import StyreneProtocol

__all__ = [
    "ChatProtocol",
    "LXMFMessage",
    "Protocol",
    "ProtocolNotFoundError",
    "ProtocolRegistry",
    "StyreneProtocol",
]
