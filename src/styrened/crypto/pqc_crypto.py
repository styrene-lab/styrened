"""Post-quantum cryptographic primitives for Styrene PQC session layer.

Provides hybrid X25519 + ML-KEM-768 key exchange, AES-256-GCM encryption,
and HKDF-based key derivation. All functions are stateless and pure.

ML-KEM-768 operations require liboqs-python (optional dependency).
All other operations use the cryptography library (already a dependency via RNS).
"""

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class PQCNotAvailableError(Exception):
    """Raised when PQC operations are attempted without liboqs installed."""
    pass


def pqc_available() -> bool:
    """Check if liboqs is installed and ML-KEM-768 is supported."""
    try:
        import oqs  # type: ignore[import-not-found]
        kem = oqs.KeyEncapsulation("ML-KEM-768")
        del kem
        return True
    except (ImportError, Exception):
        return False


def kem_generate_keypair() -> tuple[bytes, bytes]:
    """Generate ML-KEM-768 keypair. Returns (public_key, secret_key)."""
    try:
        import oqs  # type: ignore[import-not-found]
    except ImportError as e:
        raise PQCNotAvailableError("liboqs-python not installed") from e
    kem = oqs.KeyEncapsulation("ML-KEM-768")
    public_key = kem.generate_keypair()
    secret_key = kem.export_secret_key()
    return public_key, secret_key


def kem_encapsulate(public_key: bytes) -> tuple[bytes, bytes]:
    """Encapsulate with ML-KEM-768. Returns (ciphertext, shared_secret)."""
    try:
        import oqs  # type: ignore[import-not-found]
    except ImportError as e:
        raise PQCNotAvailableError("liboqs-python not installed") from e
    kem = oqs.KeyEncapsulation("ML-KEM-768")
    ciphertext, shared_secret = kem.encap_secret(public_key)
    return ciphertext, shared_secret


def kem_decapsulate(secret_key: bytes, ciphertext: bytes) -> bytes:
    """Decapsulate ML-KEM-768 ciphertext. Returns shared_secret."""
    try:
        import oqs  # type: ignore[import-not-found]
    except ImportError as e:
        raise PQCNotAvailableError("liboqs-python not installed") from e
    kem = oqs.KeyEncapsulation("ML-KEM-768", secret_key=secret_key)
    shared_secret = kem.decap_secret(ciphertext)
    return shared_secret


def x25519_generate_keypair() -> tuple[bytes, bytes]:
    """Generate X25519 ephemeral keypair. Returns (public_key_bytes, private_key_bytes)."""
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return (
        public_key.public_bytes_raw(),
        private_key.private_bytes_raw(),
    )


def x25519_derive_shared(private_key_bytes: bytes, peer_public_key_bytes: bytes) -> bytes:
    """X25519 ECDH. Returns 32-byte shared secret."""
    private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
    peer_public_key = X25519PublicKey.from_public_bytes(peer_public_key_bytes)
    return private_key.exchange(peer_public_key)


def hybrid_kdf(
    x25519_shared: bytes, kem_shared: bytes, session_id: bytes
) -> bytes:
    """HKDF-SHA256(ikm=x25519 || kem, salt=session_id, info=b'styrene.io:hybrid-pqc:v1')

    Returns 32-byte derived key suitable for AES-256-GCM.
    """
    ikm = x25519_shared + kem_shared
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=session_id,
        info=b"styrene.io:hybrid-pqc:v1",
    )
    return hkdf.derive(ikm)


def aes_gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    """AES-256-GCM encrypt. Returns nonce || ciphertext || tag.

    The nonce is 12 bytes, randomly generated. The tag is included in the
    ciphertext by AESGCM (appended as last 16 bytes).
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ct


def aes_gcm_decrypt(key: bytes, data: bytes, aad: bytes | None = None) -> bytes:
    """AES-256-GCM decrypt. Raises InvalidTag on failure.

    Expects data as nonce (12 bytes) || ciphertext || tag (16 bytes).
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")
    if len(data) < 12 + 16:
        raise ValueError(f"Data too short for nonce + tag: {len(data)} bytes")
    nonce = data[:12]
    ct = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, aad)


def ratchet_key(current_key: bytes, counter: int) -> bytes:
    """HKDF-SHA256(ikm=current_key, salt=counter_bytes, info=b'styrene.io:ratchet:v1')

    Derives a new key from the current key and a monotonic counter.
    Forward secrecy: knowing the derived key does not reveal the original.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=counter.to_bytes(8, "big"),
        info=b"styrene.io:ratchet:v1",
    )
    return hkdf.derive(current_key)
