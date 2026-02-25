"""Post-quantum cryptographic session models.

Defines security tiers, session states, and session metadata for the
hybrid X25519 + ML-KEM-768 PQC session layer.
"""

import os
import time
from dataclasses import dataclass, field
from enum import Enum


class SecurityTier(Enum):
    """Security tier for a peer connection.

    Indicates the level of cryptographic protection on the link.
    """

    NONE = "none"  # No encryption (shouldn't happen in practice)
    RNS_ONLY = "rns_only"  # Standard RNS X25519 only
    PQC_HYBRID = "pqc_hybrid"  # X25519 + ML-KEM-768
    PQC_DEGRADED = "pqc_degraded"  # Session expired, awaiting rekey


class PQCSessionState(Enum):
    """State machine for PQC session lifecycle."""

    INITIATING = "initiating"  # Sent PQC_INITIATE, awaiting response
    RESPONDING = "responding"  # Received PQC_INITIATE, sent PQC_RESPOND
    ESTABLISHED = "established"  # Handshake complete, keys active
    REKEYING = "rekeying"  # Rekey in progress
    EXPIRED = "expired"  # Session timed out or daemon restarted


@dataclass
class PQCSession:
    """Metadata for an active or historical PQC session.

    Key material is NEVER stored here — it lives only in the service's
    in-memory dicts and is never persisted to disk.

    Attributes:
        session_id: 16-byte random session identifier.
        peer_hash: RNS destination hash of the remote peer.
        state: Current session state.
        created_at: Unix timestamp of session creation.
        last_rekeyed_at: Unix timestamp of last rekey.
        rekey_count: Number of times this session has been rekeyed.
        security_tier: Current security tier for this session.
    """

    session_id: bytes = field(default_factory=lambda: os.urandom(16))
    peer_hash: str = ""
    state: PQCSessionState = PQCSessionState.INITIATING
    created_at: float = field(default_factory=time.time)
    last_rekeyed_at: float = field(default_factory=time.time)
    rekey_count: int = 0
    security_tier: SecurityTier = SecurityTier.PQC_HYBRID
