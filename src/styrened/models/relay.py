"""Relay data models for TURN-style link relay."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# ---------------------------------------------------------------------------
# LinkType
# ---------------------------------------------------------------------------

class LinkType(Enum):
    """Whether a DirectLink is direct or hub-relayed."""
    DIRECT = "direct"
    RELAYED = "relayed"


# ---------------------------------------------------------------------------
# RelayConfig
# ---------------------------------------------------------------------------

@dataclass
class RelayConfig:
    """Configuration for the hub relay service."""
    enabled: bool = False
    max_sessions: int = 16
    max_per_identity: int = 2
    max_bytes_per_session: int = 52_428_800  # 50 MiB
    idle_timeout: int = 900  # seconds
    allow_permanent: bool = False
    allowed_identities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RelaySession
# ---------------------------------------------------------------------------

@dataclass
class RelaySession:
    """An active relay session bridging two peers through the hub."""
    requester_hash: str
    target_hash: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    bytes_forwarded: int = 0
    is_permanent: bool = False
    is_priority: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def record_bytes(self, n: int) -> None:
        """Record n bytes forwarded and update last_activity.

        Raises ValueError if n is negative.
        """
        if n < 0:
            raise ValueError(f"record_bytes() requires non-negative value, got {n}")
        self.bytes_forwarded += n
        self.last_activity = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# RelayError hierarchy — 12 distinct subclasses
# ---------------------------------------------------------------------------

class RelayError(Exception):
    """Base exception for all relay errors."""
    error_code: str = "relay_error"


class RelayDisabled(RelayError):
    error_code = "relay.disabled"

class RelayMaxSessions(RelayError):
    error_code = "relay.max_sessions"

class RelayMaxPerIdentity(RelayError):
    error_code = "relay.max_per_identity"

class RelayByteLimitExceeded(RelayError):
    error_code = "relay.byte_limit"

class RelayIdleTimeout(RelayError):
    error_code = "relay.idle_timeout"

class RelayUnauthorized(RelayError):
    error_code = "relay.unauthorized"

class RelayPermanentDenied(RelayError):
    error_code = "relay.permanent_denied"

class RelayTargetRejected(RelayError):
    error_code = "relay.target_rejected"

class RelayTargetOffline(RelayError):
    error_code = "relay.target_offline"

class RelayPermanentConsentDenied(RelayError):
    error_code = "relay.consent_denied"

class RelayEvicted(RelayError):
    error_code = "relay.evicted"

class RelayBridgeDenied(RelayError):
    error_code = "relay.bridge_denied"
