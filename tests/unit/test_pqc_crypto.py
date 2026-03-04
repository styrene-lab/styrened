"""Unit tests for PQC cryptographic primitives."""

import pytest

from styrened.crypto.pqc_crypto import (
    PQCNotAvailableError,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    hybrid_kdf,
    pqc_available,
    ratchet_key,
    x25519_derive_shared,
    x25519_generate_keypair,
)

# Conditionally import KEM functions
_pqc = pqc_available()


class TestPQCAvailable:
    def test_pqc_available_returns_bool(self):
        """pqc_available() returns True or False depending on liboqs."""
        result = pqc_available()
        assert isinstance(result, bool)


class TestX25519:
    def test_x25519_generate_keypair_lengths(self):
        """X25519 keypair has correct lengths (32 bytes each)."""
        pub, priv = x25519_generate_keypair()
        assert len(pub) == 32
        assert len(priv) == 32

    def test_x25519_roundtrip(self):
        """Both sides derive the same shared secret."""
        pub_a, priv_a = x25519_generate_keypair()
        pub_b, priv_b = x25519_generate_keypair()

        shared_a = x25519_derive_shared(priv_a, pub_b)
        shared_b = x25519_derive_shared(priv_b, pub_a)

        assert shared_a == shared_b
        assert len(shared_a) == 32

    def test_x25519_different_keys_different_shared(self):
        """Different key pairs produce different shared secrets."""
        pub_a, priv_a = x25519_generate_keypair()
        pub_b, priv_b = x25519_generate_keypair()
        pub_c, priv_c = x25519_generate_keypair()

        shared_ab = x25519_derive_shared(priv_a, pub_b)
        shared_ac = x25519_derive_shared(priv_a, pub_c)

        assert shared_ab != shared_ac


class TestHybridKDF:
    def test_hybrid_kdf_deterministic(self):
        """Same inputs produce same output."""
        x25519_shared = b"\x01" * 32
        kem_shared = b"\x02" * 32
        session_id = b"\x03" * 16

        key1 = hybrid_kdf(x25519_shared, kem_shared, session_id)
        key2 = hybrid_kdf(x25519_shared, kem_shared, session_id)

        assert key1 == key2
        assert len(key1) == 32

    def test_hybrid_kdf_different_sessions(self):
        """Different session_id produces different output."""
        x25519_shared = b"\x01" * 32
        kem_shared = b"\x02" * 32

        key1 = hybrid_kdf(x25519_shared, kem_shared, b"\x03" * 16)
        key2 = hybrid_kdf(x25519_shared, kem_shared, b"\x04" * 16)

        assert key1 != key2

    def test_hybrid_kdf_different_x25519(self):
        """Different X25519 shared secret produces different output."""
        kem_shared = b"\x02" * 32
        session_id = b"\x03" * 16

        key1 = hybrid_kdf(b"\x01" * 32, kem_shared, session_id)
        key2 = hybrid_kdf(b"\x05" * 32, kem_shared, session_id)

        assert key1 != key2

    def test_hybrid_kdf_different_kem(self):
        """Different KEM shared secret produces different output."""
        x25519_shared = b"\x01" * 32
        session_id = b"\x03" * 16

        key1 = hybrid_kdf(x25519_shared, b"\x02" * 32, session_id)
        key2 = hybrid_kdf(x25519_shared, b"\x06" * 32, session_id)

        assert key1 != key2


class TestAESGCM:
    def test_aes_gcm_roundtrip(self):
        """Encrypt then decrypt recovers plaintext."""
        key = b"\x00" * 32
        plaintext = b"hello styrene mesh"

        encrypted = aes_gcm_encrypt(key, plaintext)
        decrypted = aes_gcm_decrypt(key, encrypted)

        assert decrypted == plaintext

    def test_aes_gcm_with_aad(self):
        """AAD is authenticated correctly."""
        key = b"\x00" * 32
        plaintext = b"secret data"
        aad = b"associated data"

        encrypted = aes_gcm_encrypt(key, plaintext, aad=aad)
        decrypted = aes_gcm_decrypt(key, encrypted, aad=aad)

        assert decrypted == plaintext

    def test_aes_gcm_tamper_detection(self):
        """Modified ciphertext raises error."""
        key = b"\x00" * 32
        plaintext = b"hello"

        encrypted = aes_gcm_encrypt(key, plaintext)
        # Tamper with ciphertext (after nonce)
        tampered = bytearray(encrypted)
        tampered[15] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(Exception):  # noqa: B017  # InvalidTag
            aes_gcm_decrypt(key, tampered)

    def test_aes_gcm_aad_mismatch(self):
        """Wrong AAD raises error."""
        key = b"\x00" * 32
        plaintext = b"hello"

        encrypted = aes_gcm_encrypt(key, plaintext, aad=b"correct")

        with pytest.raises(Exception):  # noqa: B017  # InvalidTag
            aes_gcm_decrypt(key, encrypted, aad=b"wrong")

    def test_aes_gcm_wrong_key(self):
        """Wrong key raises error."""
        key1 = b"\x00" * 32
        key2 = b"\x01" * 32
        plaintext = b"hello"

        encrypted = aes_gcm_encrypt(key1, plaintext)

        with pytest.raises(Exception):  # noqa: B017
            aes_gcm_decrypt(key2, encrypted)

    def test_aes_gcm_nonce_uniqueness(self):
        """Two encryptions of same plaintext produce different ciphertext (random nonce)."""
        key = b"\x00" * 32
        plaintext = b"hello"

        enc1 = aes_gcm_encrypt(key, plaintext)
        enc2 = aes_gcm_encrypt(key, plaintext)

        assert enc1 != enc2  # Different random nonces

    def test_aes_gcm_invalid_key_length(self):
        """Non-32-byte key raises ValueError."""
        with pytest.raises(ValueError, match="32 bytes"):
            aes_gcm_encrypt(b"\x00" * 16, b"hello")

    def test_aes_gcm_data_too_short(self):
        """Data shorter than nonce + tag raises ValueError."""
        key = b"\x00" * 32
        with pytest.raises(ValueError, match="too short"):
            aes_gcm_decrypt(key, b"\x00" * 10)

    def test_aes_gcm_empty_plaintext(self):
        """Empty plaintext encrypts and decrypts correctly."""
        key = b"\x00" * 32
        encrypted = aes_gcm_encrypt(key, b"")
        assert aes_gcm_decrypt(key, encrypted) == b""


class TestRatchetKey:
    def test_ratchet_key_deterministic(self):
        """Same inputs produce same output."""
        key = b"\x00" * 32
        result1 = ratchet_key(key, 1)
        result2 = ratchet_key(key, 1)
        assert result1 == result2
        assert len(result1) == 32

    def test_ratchet_key_different_counter(self):
        """Different counter produces different key."""
        key = b"\x00" * 32
        k1 = ratchet_key(key, 1)
        k2 = ratchet_key(key, 2)
        assert k1 != k2

    def test_ratchet_key_forward_secrecy(self):
        """Derived key is different from input key (can't trivially reverse)."""
        key = b"\x00" * 32
        derived = ratchet_key(key, 0)
        assert derived != key

    def test_ratchet_key_chain(self):
        """Can ratchet multiple times, each step produces different key."""
        key = b"\xAB" * 32
        keys = [key]
        for i in range(5):
            key = ratchet_key(key, i)
            keys.append(key)
        # All keys should be unique
        assert len(set(keys)) == len(keys)


@pytest.mark.skipif(not _pqc, reason="liboqs not installed")
class TestKEM:
    def test_kem_roundtrip(self):
        """generate -> encapsulate -> decapsulate produces same shared secret."""
        from styrened.crypto.pqc_crypto import (
            kem_decapsulate,
            kem_encapsulate,
            kem_generate_keypair,
        )

        pub, sec = kem_generate_keypair()
        ct, shared_enc = kem_encapsulate(pub)
        shared_dec = kem_decapsulate(sec, ct)

        assert shared_enc == shared_dec
        assert len(shared_enc) == 32

    def test_kem_keypair_sizes(self):
        """ML-KEM-768 key sizes match spec."""
        from styrened.crypto.pqc_crypto import kem_generate_keypair

        pub, sec = kem_generate_keypair()
        assert len(pub) == 1184  # ML-KEM-768 public key
        # secret key size varies by implementation

    def test_kem_different_keypairs(self):
        """Different keypairs produce different shared secrets for same ciphertext."""
        from styrened.crypto.pqc_crypto import kem_encapsulate, kem_generate_keypair

        pub1, _ = kem_generate_keypair()
        pub2, _ = kem_generate_keypair()

        _, shared1 = kem_encapsulate(pub1)
        _, shared2 = kem_encapsulate(pub2)

        assert shared1 != shared2


class TestKEMNotAvailable:
    """Test error handling when liboqs is not installed."""

    def test_kem_generate_raises_without_liboqs(self):
        """kem_generate_keypair raises PQCNotAvailableError if liboqs missing."""
        if _pqc:
            pytest.skip("liboqs is installed")
        from styrened.crypto.pqc_crypto import kem_generate_keypair
        with pytest.raises(PQCNotAvailableError):
            kem_generate_keypair()

    def test_kem_encapsulate_raises_without_liboqs(self):
        if _pqc:
            pytest.skip("liboqs is installed")
        from styrened.crypto.pqc_crypto import kem_encapsulate
        with pytest.raises(PQCNotAvailableError):
            kem_encapsulate(b"\x00" * 1184)

    def test_kem_decapsulate_raises_without_liboqs(self):
        if _pqc:
            pytest.skip("liboqs is installed")
        from styrened.crypto.pqc_crypto import kem_decapsulate
        with pytest.raises(PQCNotAvailableError):
            kem_decapsulate(b"\x00" * 32, b"\x00" * 1088)
