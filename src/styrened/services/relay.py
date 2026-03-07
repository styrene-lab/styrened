"""TURN-style link relay service for hub-mediated peer connections."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from styrened.models.relay import (
    RelayConfig,
    RelaySession,
    RelayDisabled,
    RelayMaxSessions,
    RelayMaxPerIdentity,
    RelayByteLimitExceeded,
    RelayIdleTimeout,
    RelayTargetOffline,
    RelayEvicted,
)

logger = logging.getLogger(__name__)


class RelayService:
    """Manages TURN-style relay sessions bridging two peers through the hub.

    Args:
        config: RelayConfig controlling limits and behavior.
    """

    def __init__(self, config: RelayConfig) -> None:
        self._config = config
        self._sessions: dict[int, RelaySession] = {}
        self._lock = asyncio.Lock()
        self._rbac_policy: Any = None

    def set_rbac_policy(self, policy: Any) -> None:
        """Inject the RBAC policy for authorization checks."""
        self._rbac_policy = policy

    def _is_target_online(self, target_hash: str) -> bool:
        """Check if target peer is connected. Stub — always True."""
        return True

    async def create_session(
        self,
        requester_hash: str,
        target_hash: str,
        permanent: bool = False,
        priority: bool = False,
    ) -> RelaySession:
        """Create a new relay session between requester and target.

        Raises:
            RelayDisabled: Relay not enabled.
            RelayTargetOffline: Target not connected.
            RelayMaxPerIdentity: Requester at per-identity cap.
            RelayMaxSessions: Global cap reached (after LRU eviction attempt).
        """
        if not self._config.enabled:
            raise RelayDisabled("Relay is disabled")

        if not self._is_target_online(target_hash):
            raise RelayTargetOffline(f"Target {target_hash} is offline")

        async with self._lock:
            # Per-identity cap
            requester_count = sum(
                1 for s in self._sessions.values()
                if s.requester_hash == requester_hash
            )
            if requester_count >= self._config.max_per_identity:
                raise RelayMaxPerIdentity(
                    f"Identity {requester_hash} at cap ({self._config.max_per_identity})"
                )

            # Global cap — try LRU eviction if priority
            if len(self._sessions) >= self._config.max_sessions:
                if priority:
                    self._evict_oldest_non_priority()
                # Re-check after possible eviction
                if len(self._sessions) >= self._config.max_sessions:
                    raise RelayMaxSessions(
                        f"Global session cap reached ({self._config.max_sessions})"
                    )

            session = RelaySession(
                requester_hash=requester_hash,
                target_hash=target_hash,
                is_permanent=permanent,
                is_priority=priority,
            )
            self._sessions[id(session)] = session
            logger.info(
                "Relay session created: %s -> %s (permanent=%s, priority=%s)",
                requester_hash, target_hash, permanent, priority,
            )
            return session

    def _evict_oldest_non_priority(self) -> None:
        """Evict the oldest non-priority session. Raises RelayMaxSessions if none."""
        non_priority = [
            (sid, s) for sid, s in self._sessions.items() if not s.is_priority
        ]
        if not non_priority:
            return  # caller will raise RelayMaxSessions
        non_priority.sort(key=lambda x: x[1].created_at)
        evict_sid, evict_session = non_priority[0]
        del self._sessions[evict_sid]
        logger.info("Evicted relay session %s (RelayEvicted)", evict_sid)

    async def teardown_session(self, session_id: int) -> None:
        """Tear down a session by ID. No-op if not found."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def disconnect_peer(self, session_id: int, peer_hash: str) -> None:
        """Handle peer disconnect for a session.

        Default (non-permanent): tear down entire session.
        Permanent: keep surviving half alive for reconnect grace period.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            if session.is_permanent:
                # Keep session alive for reconnect
                logger.info(
                    "Permanent session %s: peer %s disconnected, keeping alive",
                    session_id, peer_hash,
                )
            else:
                del self._sessions[session_id]
                logger.info(
                    "Session %s torn down on peer %s disconnect",
                    session_id, peer_hash,
                )

    async def enforce_byte_limit(self, session_id: int, nbytes: int) -> None:
        """Check byte limit for a session. Tears down and raises on exceed.

        Permanent sessions are exempt.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            if session.is_permanent:
                return
            if session.bytes_forwarded + nbytes > self._config.max_bytes_per_session:
                del self._sessions[session_id]
                raise RelayByteLimitExceeded(
                    f"Session {session_id} exceeded byte limit "
                    f"({session.bytes_forwarded + nbytes} > {self._config.max_bytes_per_session})"
                )

    async def idle_check(self) -> None:
        """Scan sessions and tear down idle non-permanent ones."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            to_remove = []
            for sid, session in self._sessions.items():
                if session.is_permanent:
                    continue
                elapsed = (now - session.last_activity).total_seconds()
                if elapsed > self._config.idle_timeout:
                    to_remove.append(sid)
                    logger.info("Session %s idle-timed out (%.0fs)", sid, elapsed)
            for sid in to_remove:
                del self._sessions[sid]
