"""YubiKey-backed identity derivation for Reticulum mesh.

Uses the FIDO2 hmac-secret extension to derive deterministic identity
key material from a hardware token. The YubiKey's internal PRF seed
never leaves the secure element — only the derived outputs are returned.

Two application-specific salts produce two independent 32-byte outputs:
- salt1 → X25519 private key (encryption/key exchange)
- salt2 → Ed25519 seed (signing/verification)

These 64 bytes load directly via RNS.Identity.from_bytes().

Requires: pip install 'styrened[yubikey]'  (python-fido2>=1.0)
"""

import base64
import logging
from hashlib import sha256

logger = logging.getLogger(__name__)

# Optional dependency guard (matches ipc/handlers.py pattern)
try:
    from fido2.client import Fido2Client, UserInteraction
    from fido2.hid import CtapHidDevice

    FIDO2_AVAILABLE = True
except ImportError:
    FIDO2_AVAILABLE = False

# Application-specific salts for key derivation
SALT_ENCRYPT = sha256(b"styrene-encryption-v1").digest()  # 32 bytes → X25519
SALT_SIGN = sha256(b"styrene-signing-v1").digest()  # 32 bytes → Ed25519


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class YubiKeyError(Exception):
    """Base exception for YubiKey operations."""


class YubiKeyNotFoundError(YubiKeyError):
    """No YubiKey device detected."""


class YubiKeyCredentialError(YubiKeyError):
    """Credential creation or assertion failed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def require_fido2() -> None:
    """Raise ImportError with install guidance if python-fido2 is missing."""
    if not FIDO2_AVAILABLE:
        raise ImportError(
            "python-fido2 is required for YubiKey identity support. "
            "Install with: pip install 'styrened[yubikey]'"
        )


def _get_fido2_client(rp_id: str) -> "Fido2Client":
    """Find a connected YubiKey and return a Fido2Client.

    Args:
        rp_id: Relying party ID for FIDO2 operations.

    Returns:
        Configured Fido2Client instance.

    Raises:
        YubiKeyNotFoundError: If no FIDO2 device is connected.
    """
    require_fido2()

    # Define interaction handler inline (requires fido2 imports above)
    class _CliInteraction(UserInteraction):
        """Minimal UserInteraction for CLI use."""

        def request_pin(self, permissions, rd_id):
            import getpass

            return getpass.getpass("YubiKey PIN: ")

        def request_uv(self, permissions, rd_id):
            print("Touch your YubiKey...")

        def prompt_up(self):
            print("Touch your YubiKey...")

    devices = list(CtapHidDevice.list_devices())
    if not devices:
        raise YubiKeyNotFoundError(
            "No YubiKey detected. Insert a YubiKey and try again."
        )

    return Fido2Client(
        devices[0],
        f"https://{rp_id}",
        user_interaction=_CliInteraction(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_credential(rp_id: str = "styrene.mesh") -> str:
    """Create a FIDO2 resident credential with hmac-secret extension.

    This is a one-time operation. The returned credential_id must be stored
    in the styrened config file.

    Args:
        rp_id: Relying party ID (default: "styrene.mesh").

    Returns:
        Base64-encoded credential ID for config storage.

    Raises:
        YubiKeyNotFoundError: If no YubiKey is connected.
        YubiKeyCredentialError: If credential creation fails.
    """
    client = _get_fido2_client(rp_id)

    try:
        result = client.make_credential(
            {
                "rp": {"id": rp_id, "name": "Styrene Mesh"},
                "user": {"id": b"styrene-operator", "name": "operator"},
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},  # ES256
                    {"type": "public-key", "alg": -8},  # EdDSA
                ],
                "extensions": {"hmacCreateSecret": True},
                "authenticatorSelection": {
                    "residentKey": "required",
                    "userVerification": "required",
                },
            }
        )
    except Exception as e:
        raise YubiKeyCredentialError(f"Credential creation failed: {e}") from e

    cred_data = result.attestation_object.auth_data.credential_data
    if cred_data is None:
        raise YubiKeyCredentialError("No credential data in attestation response")

    credential_id_b64 = base64.b64encode(cred_data.credential_id).decode("ascii")
    logger.info(f"Created FIDO2 credential for rp_id={rp_id}")
    return credential_id_b64


def derive_identity_bytes(
    credential_id_b64: str,
    rp_id: str = "styrene.mesh",
    require_touch: bool = False,
) -> bytes:
    """Derive 64-byte RNS identity key material from YubiKey.

    Performs a FIDO2 getAssertion with two hmac-secret salts to produce
    two independent 32-byte outputs that form the complete RNS identity:
    - output1 (from SALT_ENCRYPT) → X25519 private key (bytes 0-31)
    - output2 (from SALT_SIGN) → Ed25519 seed (bytes 32-63)

    Args:
        credential_id_b64: Base64-encoded credential ID from setup_credential().
        rp_id: Relying party ID matching the credential.
        require_touch: Whether to require physical touch.

    Returns:
        64-byte identity key material (X25519 ‖ Ed25519).

    Raises:
        YubiKeyNotFoundError: If no YubiKey is connected.
        YubiKeyCredentialError: If assertion fails or output is invalid.
    """
    require_fido2()

    credential_id = base64.b64decode(credential_id_b64)
    client = _get_fido2_client(rp_id)

    user_verification = "required" if require_touch else "discouraged"

    try:
        result = client.get_assertion(
            {
                "rpId": rp_id,
                "allowCredentials": [
                    {"type": "public-key", "id": credential_id},
                ],
                "extensions": {
                    "hmacGetSecret": {
                        "salt1": SALT_ENCRYPT,
                        "salt2": SALT_SIGN,
                    },
                },
                "userVerification": user_verification,
            }
        )
    except Exception as e:
        raise YubiKeyCredentialError(f"Assertion failed: {e}") from e

    response = result.get_response(0)
    hmac_result = response.extension_results.get("hmacGetSecret")
    if hmac_result is None:
        raise YubiKeyCredentialError(
            "YubiKey did not return hmac-secret output. "
            "Ensure the credential was created with hmac-secret extension enabled."
        )

    encryption_key = hmac_result.get("output1")
    signing_seed = hmac_result.get("output2")

    if not encryption_key or not signing_seed:
        raise YubiKeyCredentialError("Incomplete hmac-secret response from YubiKey")

    if len(encryption_key) != 32 or len(signing_seed) != 32:
        raise YubiKeyCredentialError(
            f"Invalid hmac-secret output sizes: "
            f"encryption={len(encryption_key)}, signing={len(signing_seed)} (expected 32 each)"
        )

    # X25519 private key ‖ Ed25519 seed = 64 bytes
    identity_bytes = bytes(encryption_key) + bytes(signing_seed)
    logger.info("Derived 64-byte identity from YubiKey hmac-secret")
    return identity_bytes
