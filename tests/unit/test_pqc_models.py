"""Unit tests for PQC models and wire format extensions."""

import time

from styrened.models.pqc import PQCSession, PQCSessionState, SecurityTier
from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
)


class TestSecurityTier:
    """Tests for SecurityTier enum."""

    def test_security_tier_values(self) -> None:
        """All SecurityTier enum values exist and are correct."""
        assert SecurityTier.NONE.value == "none"
        assert SecurityTier.RNS_ONLY.value == "rns_only"
        assert SecurityTier.PQC_HYBRID.value == "pqc_hybrid"
        assert SecurityTier.PQC_DEGRADED.value == "pqc_degraded"

    def test_security_tier_from_value(self) -> None:
        """SecurityTier can be created from string value."""
        assert SecurityTier("pqc_hybrid") == SecurityTier.PQC_HYBRID
        assert SecurityTier("rns_only") == SecurityTier.RNS_ONLY

    def test_security_tier_count(self) -> None:
        """Exactly 4 security tiers defined."""
        assert len(SecurityTier) == 4


class TestPQCSessionState:
    """Tests for PQCSessionState enum."""

    def test_session_state_values(self) -> None:
        """All PQCSessionState enum values exist and are correct."""
        assert PQCSessionState.INITIATING.value == "initiating"
        assert PQCSessionState.RESPONDING.value == "responding"
        assert PQCSessionState.ESTABLISHED.value == "established"
        assert PQCSessionState.REKEYING.value == "rekeying"
        assert PQCSessionState.EXPIRED.value == "expired"

    def test_session_state_from_value(self) -> None:
        """PQCSessionState can be created from string value."""
        assert PQCSessionState("established") == PQCSessionState.ESTABLISHED

    def test_session_state_count(self) -> None:
        """Exactly 5 session states defined."""
        assert len(PQCSessionState) == 5


class TestPQCSession:
    """Tests for PQCSession dataclass."""

    def test_pqc_session_creation(self) -> None:
        """PQCSession can be created with defaults."""
        session = PQCSession(peer_hash="abcd1234" * 4)
        assert len(session.session_id) == 16
        assert session.peer_hash == "abcd1234" * 4
        assert session.state == PQCSessionState.INITIATING
        assert session.rekey_count == 0
        assert session.security_tier == SecurityTier.PQC_HYBRID

    def test_pqc_session_timestamps(self) -> None:
        """Session timestamps are set to current time by default."""
        before = time.time()
        session = PQCSession(peer_hash="test")
        after = time.time()
        assert before <= session.created_at <= after
        assert before <= session.last_rekeyed_at <= after

    def test_pqc_session_custom_id(self) -> None:
        """Session ID can be set explicitly."""
        custom_id = b"\x01" * 16
        session = PQCSession(session_id=custom_id, peer_hash="test")
        assert session.session_id == custom_id

    def test_pqc_session_state_transitions(self) -> None:
        """Session state can be changed."""
        session = PQCSession(peer_hash="test")
        assert session.state == PQCSessionState.INITIATING

        session.state = PQCSessionState.ESTABLISHED
        assert session.state == PQCSessionState.ESTABLISHED

        session.state = PQCSessionState.EXPIRED
        assert session.state == PQCSessionState.EXPIRED

    def test_pqc_session_unique_ids(self) -> None:
        """Different sessions get different random IDs."""
        s1 = PQCSession(peer_hash="a")
        s2 = PQCSession(peer_hash="b")
        assert s1.session_id != s2.session_id


class TestPQCMessageTypes:
    """Tests for PQC message type wire format integration."""

    def test_pqc_message_types_exist(self) -> None:
        """All PQC message types are defined in StyreneMessageType."""
        assert StyreneMessageType.PQC_INITIATE == 0xD0
        assert StyreneMessageType.PQC_RESPOND == 0xD1
        assert StyreneMessageType.PQC_CONFIRM == 0xD2
        assert StyreneMessageType.PQC_REKEY == 0xD3
        assert StyreneMessageType.PQC_DATA == 0xD4
        assert StyreneMessageType.PQC_CLOSE == 0xD5

    def test_pqc_message_types_are_valid_intenum(self) -> None:
        """PQC message types can be used as integers."""
        assert int(StyreneMessageType.PQC_INITIATE) == 0xD0
        assert int(StyreneMessageType.PQC_CLOSE) == 0xD5

    def test_pqc_initiate_envelope_roundtrip(self) -> None:
        """PQC_INITIATE message round-trips through envelope encoding."""
        payload = encode_payload({
            "session_id": b"\x01" * 16,
            "x25519_pub": b"\x02" * 32,
            "kem_ct": b"\x03" * 1088,
        })
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_INITIATE,
            payload=payload,
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_INITIATE
        assert decoded.version == STYRENE_VERSION
        assert decoded.payload == payload

    def test_pqc_respond_envelope_roundtrip(self) -> None:
        """PQC_RESPOND message round-trips through envelope encoding."""
        payload = encode_payload({
            "x25519_pub": b"\x04" * 32,
            "kem_ct": b"\x05" * 1088,
            "hmac": b"\x06" * 32,
        })
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_RESPOND,
            payload=payload,
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_RESPOND

    def test_pqc_confirm_envelope_roundtrip(self) -> None:
        """PQC_CONFIRM message round-trips through envelope encoding."""
        payload = encode_payload({"hmac": b"\x07" * 32})
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_CONFIRM,
            payload=payload,
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_CONFIRM

    def test_pqc_data_envelope_roundtrip(self) -> None:
        """PQC_DATA message round-trips through envelope encoding."""
        payload = encode_payload({"encrypted": b"\x08" * 256})
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_DATA,
            payload=payload,
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_DATA

    def test_pqc_close_envelope_roundtrip(self) -> None:
        """PQC_CLOSE message round-trips through envelope encoding."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_CLOSE,
            payload=b"",
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_CLOSE

    def test_pqc_rekey_envelope_roundtrip(self) -> None:
        """PQC_REKEY message round-trips through envelope encoding."""
        payload = encode_payload({"session_id": b"\x09" * 16})
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PQC_REKEY,
            payload=payload,
        )
        wire = envelope.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.PQC_REKEY

    def test_all_pqc_types_in_contiguous_range(self) -> None:
        """PQC types occupy 0xD0-0xD5 without gaps."""
        pqc_types = [
            StyreneMessageType.PQC_INITIATE,
            StyreneMessageType.PQC_RESPOND,
            StyreneMessageType.PQC_CONFIRM,
            StyreneMessageType.PQC_REKEY,
            StyreneMessageType.PQC_DATA,
            StyreneMessageType.PQC_CLOSE,
        ]
        values = sorted(t.value for t in pqc_types)
        assert values == [0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5]
