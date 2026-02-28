"""Unit tests for PQC session service."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.crypto.pqc_crypto import x25519_generate_keypair
from styrened.models.config import PQCConfig
from styrened.models.pqc import PQCSession, PQCSessionState, SecurityTier
from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    decode_payload,
    encode_payload,
)
from styrened.services.pqc_session import PQCSessionService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(source_hash: str) -> MagicMock:
    """Create a mock LXMF message with the given source hash."""
    msg = MagicMock()
    msg.source_hash = source_hash
    return msg


def _make_envelope(message_type: StyreneMessageType, payload: bytes) -> StyreneEnvelope:
    """Create a StyreneEnvelope for handler testing."""
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=message_type,
        payload=payload,
    )


# Fake KEM values (consistent so both sides derive the same shared secret)
_FAKE_KEM_PUB = b"\x01" * 1184
_FAKE_KEM_SK = b"\x02" * 2400
_FAKE_KEM_CT = b"\x03" * 1088
_FAKE_KEM_SHARED = b"\x04" * 32


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_protocol() -> MagicMock:
    proto = MagicMock()
    proto.send_typed_message = AsyncMock()
    proto.register_handler = MagicMock()
    return proto


@pytest.fixture
def config() -> PQCConfig:
    return PQCConfig()


@pytest.fixture
def service(mock_protocol: MagicMock, config: PQCConfig) -> PQCSessionService:
    return PQCSessionService(mock_protocol, config)


@pytest.fixture
def kem_mocks():
    """Mock ML-KEM-768 functions so tests run without liboqs."""
    with (
        patch(
            "styrened.services.pqc_session.kem_generate_keypair",
            return_value=(_FAKE_KEM_PUB, _FAKE_KEM_SK),
        ),
        patch(
            "styrened.services.pqc_session.kem_encapsulate",
            return_value=(_FAKE_KEM_CT, _FAKE_KEM_SHARED),
        ),
        patch(
            "styrened.services.pqc_session.kem_decapsulate",
            return_value=_FAKE_KEM_SHARED,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestPQCSessionServiceInit:
    """Handler registration on construction."""

    def test_registers_all_handlers(self, mock_protocol: MagicMock, config: PQCConfig) -> None:
        """All PQC message type handlers are registered with the protocol."""
        PQCSessionService(mock_protocol, config)
        registered = {c[0][0] for c in mock_protocol.register_handler.call_args_list}
        assert StyreneMessageType.PQC_INITIATE in registered
        assert StyreneMessageType.PQC_RESPOND in registered
        assert StyreneMessageType.PQC_CONFIRM in registered
        assert StyreneMessageType.PQC_REKEY in registered
        assert StyreneMessageType.PQC_CLOSE in registered


# ---------------------------------------------------------------------------
# Initiate session
# ---------------------------------------------------------------------------


class TestInitiateSession:
    """Tests for the initiator side of the handshake."""

    @pytest.mark.asyncio
    async def test_sends_pqc_initiate(
        self, service: PQCSessionService, mock_protocol: MagicMock, kem_mocks: None
    ) -> None:
        """initiate_session sends a PQC_INITIATE message with required fields."""
        await service.initiate_session("b" * 32)

        mock_protocol.send_typed_message.assert_called_once()
        kw = mock_protocol.send_typed_message.call_args[1]
        assert kw["destination"] == "b" * 32
        assert kw["message_type"] == StyreneMessageType.PQC_INITIATE

        payload = decode_payload(kw["payload"])
        assert "session_id" in payload
        assert "x25519_pub" in payload
        assert "kem_pub" in payload

    @pytest.mark.asyncio
    async def test_creates_session_as_initiating(
        self, service: PQCSessionService, kem_mocks: None
    ) -> None:
        """New session starts in INITIATING state with RNS_ONLY tier."""
        await service.initiate_session("b" * 32)

        session = service._sessions["b" * 32]
        assert session.state == PQCSessionState.INITIATING
        assert service.get_security_tier("b" * 32) == SecurityTier.RNS_ONLY


# ---------------------------------------------------------------------------
# Full handshake (3-message exchange between two services)
# ---------------------------------------------------------------------------


def _run_handshake(kem_mocks: None):
    """Run a full handshake and return (svc_a, svc_b, peer_a, peer_b)."""
    # This is a helper coroutine; must be awaited.
    pass


class TestFullHandshake:
    """Simulate complete 3-message PQC handshake between two services."""

    async def _handshake(self):
        """Run a full handshake and return both services + peer hashes."""
        proto_a = MagicMock()
        proto_a.send_typed_message = AsyncMock()
        proto_a.register_handler = MagicMock()
        proto_b = MagicMock()
        proto_b.send_typed_message = AsyncMock()
        proto_b.register_handler = MagicMock()

        config = PQCConfig()
        svc_a = PQCSessionService(proto_a, config)
        svc_b = PQCSessionService(proto_b, config)

        peer_a = "a" * 32
        peer_b = "b" * 32

        # Step 1: A initiates to B
        await svc_a.initiate_session(peer_b)
        initiate_kw = proto_a.send_typed_message.call_args[1]
        assert initiate_kw["message_type"] == StyreneMessageType.PQC_INITIATE

        # Step 2: B handles INITIATE
        await svc_b.handle_initiate(
            _make_message(peer_a),
            _make_envelope(StyreneMessageType.PQC_INITIATE, initiate_kw["payload"]),
        )
        respond_kw = proto_b.send_typed_message.call_args[1]
        assert respond_kw["message_type"] == StyreneMessageType.PQC_RESPOND

        # Step 3: A handles RESPOND
        await svc_a.handle_respond(
            _make_message(peer_b),
            _make_envelope(StyreneMessageType.PQC_RESPOND, respond_kw["payload"]),
        )
        confirm_kw = proto_a.send_typed_message.call_args[1]
        assert confirm_kw["message_type"] == StyreneMessageType.PQC_CONFIRM

        # Step 4: B handles CONFIRM
        await svc_b.handle_confirm(
            _make_message(peer_a),
            _make_envelope(StyreneMessageType.PQC_CONFIRM, confirm_kw["payload"]),
        )

        return svc_a, svc_b, peer_a, peer_b

    @pytest.mark.asyncio
    async def test_full_handshake_establishes_session(self, kem_mocks: None) -> None:
        """Both sides reach ESTABLISHED with PQC_HYBRID tier after handshake."""
        svc_a, svc_b, peer_a, peer_b = await self._handshake()

        assert svc_a._sessions[peer_b].state == PQCSessionState.ESTABLISHED
        assert svc_b._sessions[peer_a].state == PQCSessionState.ESTABLISHED
        assert svc_a.get_security_tier(peer_b) == SecurityTier.PQC_HYBRID
        assert svc_b.get_security_tier(peer_a) == SecurityTier.PQC_HYBRID

    @pytest.mark.asyncio
    async def test_handshake_keys_match(self, kem_mocks: None) -> None:
        """Both sides derive the same session key."""
        svc_a, svc_b, peer_a, peer_b = await self._handshake()

        assert svc_a._active_keys[peer_b] == svc_b._active_keys[peer_a]

    @pytest.mark.asyncio
    async def test_cross_service_encrypt_decrypt(self, kem_mocks: None) -> None:
        """A encrypts, B decrypts successfully after handshake."""
        svc_a, svc_b, peer_a, peer_b = await self._handshake()

        plaintext = b"hello, post-quantum world"
        encrypted = await svc_a.encrypt_payload(peer_b, plaintext)
        decrypted = await svc_b.decrypt_payload(peer_a, encrypted)
        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_no_pending_state_after_handshake(self, kem_mocks: None) -> None:
        """Handshake state is cleaned up once session is established."""
        svc_a, svc_b, _, _ = await self._handshake()

        assert len(svc_a._pending) == 0
        assert len(svc_b._pending) == 0


# ---------------------------------------------------------------------------
# Handshake failure modes
# ---------------------------------------------------------------------------


class TestHandshakeFailures:
    """Bad HMAC and missing state edge cases."""

    @pytest.mark.asyncio
    async def test_respond_bad_hmac_rejects(self, kem_mocks: None) -> None:
        """Initiator rejects PQC_RESPOND with incorrect HMAC."""
        proto_a = MagicMock()
        proto_a.send_typed_message = AsyncMock()
        proto_a.register_handler = MagicMock()

        svc_a = PQCSessionService(proto_a, PQCConfig())
        peer_b = "b" * 32

        await svc_a.initiate_session(peer_b)
        initiate_kw = proto_a.send_typed_message.call_args[1]
        initiate_data = decode_payload(initiate_kw["payload"])

        # Craft a RESPOND with an invalid HMAC
        resp_x25519_pub, _ = x25519_generate_keypair()
        bad_respond = encode_payload({
            "session_id": initiate_data["session_id"],
            "x25519_pub": resp_x25519_pub,
            "kem_ct": _FAKE_KEM_CT,
            "hmac": b"\xff" * 32,
        })

        proto_a.send_typed_message.reset_mock()

        await svc_a.handle_respond(
            _make_message(peer_b),
            _make_envelope(StyreneMessageType.PQC_RESPOND, bad_respond),
        )

        # Should NOT have sent PQC_CONFIRM
        proto_a.send_typed_message.assert_not_called()
        # Session expired
        assert svc_a._sessions[peer_b].state == PQCSessionState.EXPIRED

    @pytest.mark.asyncio
    async def test_no_pending_ignores_respond(self, service: PQCSessionService) -> None:
        """PQC_RESPOND without a pending INITIATE is silently ignored."""
        payload = encode_payload({
            "session_id": b"\x00" * 16,
            "x25519_pub": b"\x00" * 32,
            "kem_ct": b"\x00" * 1088,
            "hmac": b"\x00" * 32,
        })
        await service.handle_respond(
            _make_message("q" * 32),
            _make_envelope(StyreneMessageType.PQC_RESPOND, payload),
        )
        assert "q" * 32 not in service._sessions

    @pytest.mark.asyncio
    async def test_no_pending_ignores_confirm(self, service: PQCSessionService) -> None:
        """PQC_CONFIRM without a pending RESPOND is silently ignored."""
        payload = encode_payload({
            "session_id": b"\x00" * 16,
            "hmac": b"\x00" * 32,
        })
        await service.handle_confirm(
            _make_message("q" * 32),
            _make_envelope(StyreneMessageType.PQC_CONFIRM, payload),
        )
        assert "q" * 32 not in service._sessions


# ---------------------------------------------------------------------------
# Encrypt / decrypt
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    """AES-256-GCM encrypt/decrypt with active session key."""

    @pytest.mark.asyncio
    async def test_roundtrip(self, service: PQCSessionService) -> None:
        """Encrypt then decrypt recovers original plaintext."""
        peer = "c" * 32
        session = PQCSession(
            peer_hash=peer, state=PQCSessionState.ESTABLISHED,
            security_tier=SecurityTier.PQC_HYBRID,
        )
        service._active_keys[peer] = b"\xaa" * 32
        service._sessions[peer] = session

        plaintext = b"hello, post-quantum world"
        encrypted = await service.encrypt_payload(peer, plaintext)
        decrypted = await service.decrypt_payload(peer, encrypted)
        assert decrypted == plaintext

    @pytest.mark.asyncio
    async def test_encrypt_without_session_raises(self, service: PQCSessionService) -> None:
        """Encrypting without an active session raises ValueError."""
        with pytest.raises(ValueError, match="No active PQC session"):
            await service.encrypt_payload("unknown" * 4, b"data")

    @pytest.mark.asyncio
    async def test_decrypt_without_session_raises(self, service: PQCSessionService) -> None:
        """Decrypting without an active session raises ValueError."""
        with pytest.raises(ValueError, match="No active PQC session"):
            await service.decrypt_payload("unknown" * 4, b"\x00" * 40)


# ---------------------------------------------------------------------------
# Security tier queries
# ---------------------------------------------------------------------------


class TestSecurityTier:
    """get_security_tier returns the correct tier for each session state."""

    def test_no_session_returns_rns_only(self, service: PQCSessionService) -> None:
        """Peer with no PQC session reports RNS_ONLY."""
        assert service.get_security_tier("x" * 32) == SecurityTier.RNS_ONLY

    def test_established_returns_pqc_hybrid(self, service: PQCSessionService) -> None:
        """Established session reports PQC_HYBRID."""
        peer = "y" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer,
            state=PQCSessionState.ESTABLISHED,
            security_tier=SecurityTier.PQC_HYBRID,
        )
        assert service.get_security_tier(peer) == SecurityTier.PQC_HYBRID

    def test_expired_returns_pqc_degraded(self, service: PQCSessionService) -> None:
        """Expired session reports PQC_DEGRADED."""
        peer = "z" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer,
            state=PQCSessionState.EXPIRED,
            security_tier=SecurityTier.PQC_DEGRADED,
        )
        assert service.get_security_tier(peer) == SecurityTier.PQC_DEGRADED


# ---------------------------------------------------------------------------
# Periodic rekey
# ---------------------------------------------------------------------------


class TestCheckRekey:
    """Time-based session rekeying."""

    @pytest.mark.asyncio
    async def test_triggers_at_interval(
        self, service: PQCSessionService, mock_protocol: MagicMock, kem_mocks: None
    ) -> None:
        """Session older than rekey_interval_hours triggers rekey."""
        peer = "r" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer,
            state=PQCSessionState.ESTABLISHED,
            last_rekeyed_at=time.time() - 25 * 3600,  # 25 h ago
        )
        service._active_keys[peer] = b"\xbb" * 32

        await service.check_rekey()

        mock_protocol.send_typed_message.assert_called_once()
        kw = mock_protocol.send_typed_message.call_args[1]
        assert kw["message_type"] == StyreneMessageType.PQC_INITIATE
        # Rekey count incremented
        assert service._sessions[peer].rekey_count == 1

    @pytest.mark.asyncio
    async def test_skips_fresh_session(
        self, service: PQCSessionService, mock_protocol: MagicMock
    ) -> None:
        """Recently established session is not rekeyed."""
        peer = "f" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer,
            state=PQCSessionState.ESTABLISHED,
            last_rekeyed_at=time.time(),
        )
        service._active_keys[peer] = b"\xcc" * 32

        await service.check_rekey()

        mock_protocol.send_typed_message.assert_not_called()
        assert service._sessions[peer].state == PQCSessionState.ESTABLISHED


class TestShouldRekey:
    """Rekey decision logic."""

    def test_returns_true_for_old_session(self, service: PQCSessionService) -> None:
        """Session past rekey interval should be rekeyed."""
        session = PQCSession(
            peer_hash="t" * 32,
            last_rekeyed_at=time.time() - 25 * 3600,
        )
        assert service._should_rekey(session) is True

    def test_returns_false_for_fresh_session(self, service: PQCSessionService) -> None:
        """Session within rekey interval should not be rekeyed."""
        session = PQCSession(
            peer_hash="t" * 32,
            last_rekeyed_at=time.time(),
        )
        assert service._should_rekey(session) is False


# ---------------------------------------------------------------------------
# Handle close / rekey messages
# ---------------------------------------------------------------------------


class TestHandleClose:
    """PQC_CLOSE tears down the session."""

    @pytest.mark.asyncio
    async def test_close_expires_session(self, service: PQCSessionService) -> None:
        """PQC_CLOSE sets session to EXPIRED / PQC_DEGRADED and removes key."""
        peer = "d" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer, state=PQCSessionState.ESTABLISHED,
        )
        service._active_keys[peer] = b"\xdd" * 32

        await service.handle_close(
            _make_message(peer),
            _make_envelope(StyreneMessageType.PQC_CLOSE, b""),
        )

        assert service._sessions[peer].state == PQCSessionState.EXPIRED
        assert service._sessions[peer].security_tier == SecurityTier.PQC_DEGRADED
        assert peer not in service._active_keys


class TestHandleRekey:
    """PQC_REKEY triggers a new handshake."""

    @pytest.mark.asyncio
    async def test_rekey_initiates_new_handshake(
        self, service: PQCSessionService, mock_protocol: MagicMock, kem_mocks: None
    ) -> None:
        """Receiving PQC_REKEY starts a fresh PQC_INITIATE exchange."""
        peer = "e" * 32
        service._sessions[peer] = PQCSession(
            peer_hash=peer, state=PQCSessionState.ESTABLISHED,
        )
        service._active_keys[peer] = b"\xee" * 32

        await service.handle_rekey(
            _make_message(peer),
            _make_envelope(StyreneMessageType.PQC_REKEY, b""),
        )

        mock_protocol.send_typed_message.assert_called_once()
        kw = mock_protocol.send_typed_message.call_args[1]
        assert kw["message_type"] == StyreneMessageType.PQC_INITIATE

    @pytest.mark.asyncio
    async def test_rekey_ignored_without_active_session(
        self, service: PQCSessionService, mock_protocol: MagicMock, kem_mocks: None
    ) -> None:
        """PQC_REKEY from peer with no active session is ignored (W3)."""
        peer = "e" * 32
        # No active key for this peer

        await service.handle_rekey(
            _make_message(peer),
            _make_envelope(StyreneMessageType.PQC_REKEY, b""),
        )

        mock_protocol.send_typed_message.assert_not_called()


# ---------------------------------------------------------------------------
# MitM peer_hash verification (C2)
# ---------------------------------------------------------------------------


class TestPeerHashVerification:
    """Verify handle_respond and handle_confirm reject mismatched peer_hash."""

    @pytest.mark.asyncio
    async def test_respond_from_wrong_peer_rejected(self, kem_mocks: None) -> None:
        """PQC_RESPOND from different peer than INITIATE target is rejected (C2)."""
        proto = MagicMock()
        proto.send_typed_message = AsyncMock()
        proto.register_handler = MagicMock()

        svc = PQCSessionService(proto, PQCConfig())
        peer_b = "b" * 32
        impersonator = "c" * 32

        await svc.initiate_session(peer_b)
        initiate_kw = proto.send_typed_message.call_args[1]
        initiate_data = decode_payload(initiate_kw["payload"])

        # Craft a RESPOND that appears to come from impersonator, not peer_b
        resp_x25519_pub, _ = x25519_generate_keypair()
        respond_payload = encode_payload({
            "session_id": initiate_data["session_id"],
            "x25519_pub": resp_x25519_pub,
            "kem_ct": _FAKE_KEM_CT,
            "hmac": b"\x00" * 32,
        })

        proto.send_typed_message.reset_mock()

        await svc.handle_respond(
            _make_message(impersonator),  # Wrong peer
            _make_envelope(StyreneMessageType.PQC_RESPOND, respond_payload),
        )

        # Should NOT have sent PQC_CONFIRM
        proto.send_typed_message.assert_not_called()
        # Pending state should be cleaned up
        session_id = initiate_data["session_id"]
        if isinstance(session_id, str):
            session_id = session_id.encode("latin-1")
        assert session_id not in svc._pending

    @pytest.mark.asyncio
    async def test_confirm_from_wrong_peer_rejected(self, kem_mocks: None) -> None:
        """PQC_CONFIRM from different peer than INITIATE source is rejected (C2)."""
        proto_a = MagicMock()
        proto_a.send_typed_message = AsyncMock()
        proto_a.register_handler = MagicMock()
        proto_b = MagicMock()
        proto_b.send_typed_message = AsyncMock()
        proto_b.register_handler = MagicMock()

        config = PQCConfig()
        svc_a = PQCSessionService(proto_a, config)
        svc_b = PQCSessionService(proto_b, config)

        peer_a = "a" * 32
        peer_b = "b" * 32
        impersonator = "d" * 32

        # A initiates to B
        await svc_a.initiate_session(peer_b)
        initiate_kw = proto_a.send_typed_message.call_args[1]

        # B handles INITIATE (from peer_a)
        await svc_b.handle_initiate(
            _make_message(peer_a),
            _make_envelope(StyreneMessageType.PQC_INITIATE, initiate_kw["payload"]),
        )
        respond_kw = proto_b.send_typed_message.call_args[1]

        # A handles RESPOND (from peer_b)
        await svc_a.handle_respond(
            _make_message(peer_b),
            _make_envelope(StyreneMessageType.PQC_RESPOND, respond_kw["payload"]),
        )
        confirm_kw = proto_a.send_typed_message.call_args[1]

        # Get session_id from the confirm payload to check cleanup
        confirm_data = decode_payload(confirm_kw["payload"])
        session_id = confirm_data["session_id"]
        if isinstance(session_id, str):
            session_id = session_id.encode("latin-1")

        # Impersonator sends the CONFIRM to B instead of peer_a
        await svc_b.handle_confirm(
            _make_message(impersonator),  # Wrong peer
            _make_envelope(StyreneMessageType.PQC_CONFIRM, confirm_kw["payload"]),
        )

        # B should NOT have established the session
        assert impersonator not in svc_b._active_keys
        # Pending state should be cleaned up
        assert session_id not in svc_b._pending


# ---------------------------------------------------------------------------
# Pending TTL sweep (W4)
# ---------------------------------------------------------------------------


class TestPendingTTL:
    """Verify expired pending handshakes are swept."""

    @pytest.mark.asyncio
    async def test_expired_pending_swept_on_initiate(
        self, service: PQCSessionService, kem_mocks: None
    ) -> None:
        """Stale _pending entries are removed when handle_initiate runs (W4)."""
        from styrened.services.pqc_session import _HandshakeState

        stale_sid = b"\xaa" * 16
        service._pending[stale_sid] = _HandshakeState(
            session_id=stale_sid,
            role="initiator",
            x25519_pub=b"\x00" * 32,
            x25519_priv=b"\x00" * 32,
            peer_hash="stale" + "0" * 27,
            created_at=time.time() - 120,  # 2 minutes ago, past 60s TTL
        )

        # Trigger sweep via handle_initiate with a valid INITIATE message
        x25519_pub, _ = x25519_generate_keypair()
        payload = encode_payload({
            "session_id": b"\xbb" * 16,
            "x25519_pub": x25519_pub,
            "kem_pub": _FAKE_KEM_PUB,
        })
        await service.handle_initiate(
            _make_message("f" * 32),
            _make_envelope(StyreneMessageType.PQC_INITIATE, payload),
        )

        # Stale entry should be gone
        assert stale_sid not in service._pending

    @pytest.mark.asyncio
    async def test_fresh_pending_not_swept(
        self, service: PQCSessionService, kem_mocks: None
    ) -> None:
        """Fresh _pending entries are NOT swept (W4)."""
        from styrened.services.pqc_session import _HandshakeState

        fresh_sid = b"\xcc" * 16
        service._pending[fresh_sid] = _HandshakeState(
            session_id=fresh_sid,
            role="initiator",
            x25519_pub=b"\x00" * 32,
            x25519_priv=b"\x00" * 32,
            peer_hash="fresh" + "0" * 27,
            created_at=time.time(),  # just now
        )

        service._sweep_expired_pending()

        # Fresh entry should still be present
        assert fresh_sid in service._pending
