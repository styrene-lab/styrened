"""PQC session service — manages hybrid PQC session lifecycle.

Handles 3-message handshake for X25519 + ML-KEM-768 hybrid key exchange,
session-key encryption/decryption, and time-based rekeying.

Handshake flow:
    PQC_INITIATE (A → B): session_id, A's X25519 pub, A's KEM pub
    PQC_RESPOND  (B → A): session_id, B's X25519 pub, KEM ciphertext, HMAC
    PQC_CONFIRM  (A → B): session_id, HMAC — session established on both sides

Key material lives only in memory — never persisted to disk.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import logging
import time
from dataclasses import dataclass
from typing import Any

from styrened.crypto.pqc_crypto import (
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    hybrid_kdf,
    kem_decapsulate,
    kem_encapsulate,
    kem_generate_keypair,
    x25519_derive_shared,
    x25519_generate_keypair,
)
from styrened.models.config import PQCConfig
from styrened.models.pqc import PQCSession, PQCSessionState, SecurityTier
from styrened.models.styrene_wire import (
    StyreneMessageType,
    decode_payload,
    encode_payload,
)

logger = logging.getLogger(__name__)


@dataclass
class _HandshakeState:
    """Ephemeral state for an in-progress PQC handshake.

    Contains key material that MUST NOT be persisted.
    """

    session_id: bytes
    role: str  # "initiator" or "responder"
    x25519_pub: bytes
    x25519_priv: bytes
    peer_hash: str = ""
    kem_pub: bytes | None = None
    kem_sk: bytes | None = None
    kem_shared: bytes | None = None
    peer_x25519_pub: bytes | None = None
    derived_key: bytes | None = None
    created_at: float = 0.0


class PQCSessionService:
    """Manages PQC session lifecycle for all peers.

    Key material lives only in ``_active_keys`` (in memory) and is
    never written to disk.
    """

    def __init__(self, protocol: Any, config: PQCConfig) -> None:
        self._protocol = protocol
        self._config = config
        self._sessions: dict[str, PQCSession] = {}
        self._pending: dict[bytes, _HandshakeState] = {}
        self._active_keys: dict[str, bytes] = {}

        protocol.register_handler(StyreneMessageType.PQC_INITIATE, self.handle_initiate)
        protocol.register_handler(StyreneMessageType.PQC_RESPOND, self.handle_respond)
        protocol.register_handler(StyreneMessageType.PQC_CONFIRM, self.handle_confirm)
        protocol.register_handler(StyreneMessageType.PQC_REKEY, self.handle_rekey)
        protocol.register_handler(StyreneMessageType.PQC_CLOSE, self.handle_close)

    # ------------------------------------------------------------------
    # Initiation
    # ------------------------------------------------------------------

    async def initiate_session(self, peer_hash: str) -> None:
        """Start PQC handshake with a peer."""
        x25519_pub, x25519_priv = x25519_generate_keypair()
        kem_pub, kem_sk = kem_generate_keypair()

        session = PQCSession(peer_hash=peer_hash, security_tier=SecurityTier.RNS_ONLY)
        self._sessions[peer_hash] = session

        state = _HandshakeState(
            session_id=session.session_id,
            role="initiator",
            x25519_pub=x25519_pub,
            x25519_priv=x25519_priv,
            peer_hash=peer_hash,
            kem_pub=kem_pub,
            kem_sk=kem_sk,
            created_at=time.time(),
        )
        self._pending[session.session_id] = state

        payload = encode_payload({
            "session_id": session.session_id,
            "x25519_pub": x25519_pub,
            "kem_pub": kem_pub,
        })
        await self._protocol.send_typed_message(
            destination=peer_hash,
            message_type=StyreneMessageType.PQC_INITIATE,
            payload=payload,
        )
        logger.info(f"PQC session initiated with {peer_hash[:16]}...")

    def initiate_session_sync(self, peer_hash: str) -> None:
        """Schedule initiate_session on the running event loop (sync caller)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.initiate_session(peer_hash))
        except RuntimeError:
            asyncio.run(self.initiate_session(peer_hash))

    # ------------------------------------------------------------------
    # Pending handshake housekeeping
    # ------------------------------------------------------------------

    _PENDING_TTL: float = 60.0  # seconds

    def _sweep_expired_pending(self) -> None:
        """Remove pending handshake entries older than _PENDING_TTL seconds."""
        now = time.time()
        expired = [
            sid for sid, state in self._pending.items()
            if state.created_at > 0 and (now - state.created_at) > self._PENDING_TTL
        ]
        for sid in expired:
            logger.debug(f"Sweeping expired pending handshake {sid.hex()[:16]}")
            del self._pending[sid]

    # ------------------------------------------------------------------
    # Incoming message handlers
    # ------------------------------------------------------------------

    async def handle_initiate(self, message: Any, envelope: Any) -> None:
        """Handle incoming PQC_INITIATE."""
        peer_hash: str = message.source_hash
        data = decode_payload(envelope.payload)

        self._sweep_expired_pending()

        session_id = _ensure_bytes(data["session_id"])
        peer_x25519_pub = _ensure_bytes(data["x25519_pub"])
        peer_kem_pub = _ensure_bytes(data["kem_pub"])

        # Generate our ephemeral keys
        x25519_pub, x25519_priv = x25519_generate_keypair()
        kem_ct, kem_shared = kem_encapsulate(peer_kem_pub)

        # Derive hybrid session key
        x25519_shared = x25519_derive_shared(x25519_priv, peer_x25519_pub)
        derived_key = hybrid_kdf(x25519_shared, kem_shared, session_id)

        # Create session (RESPONDING state, not yet ESTABLISHED)
        session = PQCSession(
            session_id=session_id,
            peer_hash=peer_hash,
            state=PQCSessionState.RESPONDING,
            security_tier=SecurityTier.RNS_ONLY,
        )
        self._sessions[peer_hash] = session

        # Compute RESPOND HMAC (proves we derived the same key)
        confirm_hmac = _compute_hmac(derived_key, b"PQC_RESPOND", session_id, x25519_pub)

        # Store state for PQC_CONFIRM verification
        self._pending[session_id] = _HandshakeState(
            session_id=session_id,
            role="responder",
            x25519_pub=x25519_pub,
            x25519_priv=x25519_priv,
            peer_hash=peer_hash,
            kem_shared=kem_shared,
            peer_x25519_pub=peer_x25519_pub,
            derived_key=derived_key,
            created_at=time.time(),
        )

        payload = encode_payload({
            "session_id": session_id,
            "x25519_pub": x25519_pub,
            "kem_ct": kem_ct,
            "hmac": confirm_hmac,
        })
        await self._protocol.send_typed_message(
            destination=peer_hash,
            message_type=StyreneMessageType.PQC_RESPOND,
            payload=payload,
        )
        logger.info(f"PQC RESPOND sent to {peer_hash[:16]}...")

    async def handle_respond(self, message: Any, envelope: Any) -> None:
        """Handle incoming PQC_RESPOND."""
        peer_hash: str = message.source_hash
        data = decode_payload(envelope.payload)

        session_id = _ensure_bytes(data["session_id"])
        peer_x25519_pub = _ensure_bytes(data["x25519_pub"])
        kem_ct = _ensure_bytes(data["kem_ct"])
        peer_hmac = _ensure_bytes(data["hmac"])

        self._sweep_expired_pending()

        state = self._pending.get(session_id)
        if state is None or state.role != "initiator":
            logger.warning(f"No pending initiator handshake for session {session_id.hex()[:16]}")
            return

        # Verify the responding peer matches the peer we initiated with
        if state.peer_hash and state.peer_hash != peer_hash:
            logger.warning(
                f"PQC RESPOND peer_hash mismatch: expected {state.peer_hash[:16]}, "
                f"got {peer_hash[:16]}. Possible MitM — rejecting."
            )
            del self._pending[session_id]
            return

        # Decapsulate KEM ciphertext with our secret key
        kem_shared = kem_decapsulate(state.kem_sk, kem_ct)

        # Derive the same hybrid session key
        x25519_shared = x25519_derive_shared(state.x25519_priv, peer_x25519_pub)
        derived_key = hybrid_kdf(x25519_shared, kem_shared, session_id)

        # Verify responder's HMAC
        expected_hmac = _compute_hmac(derived_key, b"PQC_RESPOND", session_id, peer_x25519_pub)
        if not hmac_mod.compare_digest(peer_hmac, expected_hmac):
            logger.error(f"PQC HMAC verification failed for {peer_hash[:16]}...")
            del self._pending[session_id]
            if peer_hash in self._sessions:
                self._sessions[peer_hash].state = PQCSessionState.EXPIRED
            return

        # Send PQC_CONFIRM (prove we also derived the key)
        confirm_hmac = _compute_hmac(derived_key, b"PQC_CONFIRM", session_id, state.x25519_pub)
        payload = encode_payload({
            "session_id": session_id,
            "hmac": confirm_hmac,
        })
        await self._protocol.send_typed_message(
            destination=peer_hash,
            message_type=StyreneMessageType.PQC_CONFIRM,
            payload=payload,
        )

        # Session established (initiator side)
        self._active_keys[peer_hash] = derived_key
        session = self._sessions[peer_hash]
        session.state = PQCSessionState.ESTABLISHED
        session.security_tier = SecurityTier.PQC_HYBRID
        del self._pending[session_id]

        logger.info(f"PQC session established (initiator) with {peer_hash[:16]}...")

    async def handle_confirm(self, message: Any, envelope: Any) -> None:
        """Handle incoming PQC_CONFIRM — session established."""
        peer_hash: str = message.source_hash
        data = decode_payload(envelope.payload)

        session_id = _ensure_bytes(data["session_id"])
        peer_hmac = _ensure_bytes(data["hmac"])

        state = self._pending.get(session_id)
        if state is None or state.role != "responder":
            logger.warning(f"No pending responder handshake for session {session_id.hex()[:16]}")
            return

        # Verify the confirming peer matches the peer who initiated
        if state.peer_hash and state.peer_hash != peer_hash:
            logger.warning(
                f"PQC CONFIRM peer_hash mismatch: expected {state.peer_hash[:16]}, "
                f"got {peer_hash[:16]}. Possible MitM — rejecting."
            )
            del self._pending[session_id]
            return

        # Verify initiator's CONFIRM HMAC
        expected_hmac = _compute_hmac(
            state.derived_key, b"PQC_CONFIRM", session_id, state.peer_x25519_pub
        )
        if not hmac_mod.compare_digest(peer_hmac, expected_hmac):
            logger.error(f"PQC confirm HMAC verification failed for {peer_hash[:16]}...")
            del self._pending[session_id]
            if peer_hash in self._sessions:
                self._sessions[peer_hash].state = PQCSessionState.EXPIRED
            return

        # Session established (responder side)
        self._active_keys[peer_hash] = state.derived_key
        session = self._sessions[peer_hash]
        session.state = PQCSessionState.ESTABLISHED
        session.security_tier = SecurityTier.PQC_HYBRID
        del self._pending[session_id]

        logger.info(f"PQC session established (responder) with {peer_hash[:16]}...")

    async def handle_rekey(self, message: Any, envelope: Any) -> None:
        """Handle incoming PQC_REKEY — start a fresh handshake.

        Only honors rekey from peers with an active (established) session.
        Ignores rekey requests from unknown peers to prevent unauthenticated
        session initiation.
        """
        peer_hash: str = message.source_hash
        if peer_hash not in self._active_keys:
            logger.warning(
                f"PQC rekey ignored from {peer_hash[:16]}...: no active session"
            )
            return
        logger.info(f"PQC rekey requested by {peer_hash[:16]}...")
        await self.initiate_session(peer_hash)

    async def handle_close(self, message: Any, envelope: Any) -> None:
        """Handle incoming PQC_CLOSE — tear down session."""
        peer_hash: str = message.source_hash
        if peer_hash in self._active_keys:
            del self._active_keys[peer_hash]
        if peer_hash in self._sessions:
            self._sessions[peer_hash].state = PQCSessionState.EXPIRED
            self._sessions[peer_hash].security_tier = SecurityTier.PQC_DEGRADED
        logger.info(f"PQC session closed by {peer_hash[:16]}...")

    # ------------------------------------------------------------------
    # Encrypt / decrypt
    # ------------------------------------------------------------------

    async def encrypt_payload(self, peer_hash: str, plaintext: bytes) -> bytes:
        """Encrypt with active session key. Raises if no session."""
        key = self._active_keys.get(peer_hash)
        if key is None:
            raise ValueError(f"No active PQC session with {peer_hash[:16]}...")
        session = self._sessions[peer_hash]
        return aes_gcm_encrypt(key, plaintext, aad=session.session_id)

    async def decrypt_payload(self, peer_hash: str, data: bytes) -> bytes:
        """Decrypt with active session key."""
        key = self._active_keys.get(peer_hash)
        if key is None:
            raise ValueError(f"No active PQC session with {peer_hash[:16]}...")
        session = self._sessions[peer_hash]
        return aes_gcm_decrypt(key, data, aad=session.session_id)

    # ------------------------------------------------------------------
    # Security tier
    # ------------------------------------------------------------------

    def get_security_tier(self, peer_hash: str) -> SecurityTier:
        """Return current security tier for a peer."""
        session = self._sessions.get(peer_hash)
        if session is None:
            return SecurityTier.RNS_ONLY
        return session.security_tier

    # ------------------------------------------------------------------
    # Rekey
    # ------------------------------------------------------------------

    async def check_rekey(self) -> None:
        """Called periodically. Rekeys sessions older than rekey_interval_hours."""
        now = time.time()
        interval = self._config.rekey_interval_hours * 3600

        for peer_hash, session in list(self._sessions.items()):
            if session.state != PQCSessionState.ESTABLISHED:
                continue
            if self._should_rekey(session, now, interval):
                await self._rekey_session(peer_hash)

    async def _rekey_session(self, peer_hash: str) -> None:
        """Initiate rekey for an existing session. Currently: new handshake."""
        old_session = self._sessions.get(peer_hash)
        old_rekey_count = old_session.rekey_count if old_session else 0

        await self.initiate_session(peer_hash)

        # Preserve rekey metadata on the new session
        new_session = self._sessions.get(peer_hash)
        if new_session:
            new_session.rekey_count = old_rekey_count + 1

    def _should_rekey(
        self,
        session: PQCSession,
        now: float | None = None,
        interval: float | None = None,
    ) -> bool:
        """Rekey decision logic. Currently: time-based only."""
        if now is None:
            now = time.time()
        if interval is None:
            interval = self._config.rekey_interval_hours * 3600
        return (now - session.last_rekeyed_at) >= interval


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _ensure_bytes(value: Any) -> bytes:
    """Coerce msgpack value to bytes."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("latin-1")
    return bytes(value)


def _compute_hmac(key: bytes, label: bytes, session_id: bytes, pubkey: bytes) -> bytes:
    """HMAC-SHA256(key, label || session_id || pubkey)."""
    return hmac_mod.new(key, label + session_id + pubkey, hashlib.sha256).digest()
