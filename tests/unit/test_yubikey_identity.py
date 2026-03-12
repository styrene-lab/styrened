"""Unit tests for YubiKey identity derivation module."""
from __future__ import annotations


import base64
from unittest.mock import MagicMock, patch

import pytest

from styrened.services.yubikey import (
    SALT_ENCRYPT,
    SALT_SIGN,
    YubiKeyCredentialError,
    YubiKeyError,
    YubiKeyNotFoundError,
    derive_identity_bytes,
    require_fido2,
    setup_credential,
)


class TestConstants:
    """Tests for module constants."""

    def test_salts_are_32_bytes(self):
        """Salts should be exactly 32 bytes (SHA-256 output)."""
        assert len(SALT_ENCRYPT) == 32
        assert len(SALT_SIGN) == 32

    def test_salts_are_different(self):
        """Encryption and signing salts must differ."""
        assert SALT_ENCRYPT != SALT_SIGN

    def test_salts_are_deterministic(self):
        """Salts should be SHA-256 of known strings."""
        from hashlib import sha256

        assert SALT_ENCRYPT == sha256(b"styrene-encryption-v1").digest()
        assert SALT_SIGN == sha256(b"styrene-signing-v1").digest()


class TestExceptions:
    """Tests for custom exception hierarchy."""

    def test_yubikey_error_is_base(self):
        """YubiKeyError should be the base exception."""
        assert issubclass(YubiKeyNotFoundError, YubiKeyError)
        assert issubclass(YubiKeyCredentialError, YubiKeyError)

    def test_yubikey_error_is_exception(self):
        """All YubiKey exceptions should inherit from Exception."""
        assert issubclass(YubiKeyError, Exception)


class TestRequireFido2:
    """Tests for require_fido2() guard."""

    def test_does_not_raise_when_available(self):
        """Should not raise when fido2 is importable."""
        with patch("styrened.services.yubikey.FIDO2_AVAILABLE", True):
            require_fido2()  # Should not raise

    def test_raises_when_unavailable(self):
        """Should raise ImportError with install guidance."""
        with patch("styrened.services.yubikey.FIDO2_AVAILABLE", False):
            with pytest.raises(ImportError, match="pip install"):
                require_fido2()


class TestSetupCredential:
    """Tests for setup_credential()."""

    def test_returns_base64_credential_id(self):
        """Should return base64-encoded credential ID."""
        mock_cred_data = MagicMock()
        mock_cred_data.credential_id = b"test-credential-id-bytes"

        mock_result = MagicMock()
        mock_result.attestation_object.auth_data.credential_data = mock_cred_data

        mock_client = MagicMock()
        mock_client.make_credential.return_value = mock_result

        with patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client):
            result = setup_credential(rp_id="test.mesh")

        expected = base64.b64encode(b"test-credential-id-bytes").decode("ascii")
        assert result == expected

    def test_raises_on_no_credential_data(self):
        """Should raise YubiKeyCredentialError when no credential data returned."""
        mock_result = MagicMock()
        mock_result.attestation_object.auth_data.credential_data = None

        mock_client = MagicMock()
        mock_client.make_credential.return_value = mock_result

        with patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client):
            with pytest.raises(YubiKeyCredentialError, match="No credential data"):
                setup_credential()

    def test_raises_on_make_credential_failure(self):
        """Should wrap exceptions in YubiKeyCredentialError."""
        mock_client = MagicMock()
        mock_client.make_credential.side_effect = RuntimeError("USB error")

        with patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client):
            with pytest.raises(YubiKeyCredentialError, match="Credential creation failed"):
                setup_credential()

    def test_uses_correct_rp_id(self):
        """Should pass the rp_id to _get_fido2_client and make_credential."""
        mock_cred_data = MagicMock()
        mock_cred_data.credential_id = b"cred"

        mock_result = MagicMock()
        mock_result.attestation_object.auth_data.credential_data = mock_cred_data

        mock_client = MagicMock()
        mock_client.make_credential.return_value = mock_result

        with patch(
            "styrened.services.yubikey._get_fido2_client", return_value=mock_client
        ) as mock_get:
            setup_credential(rp_id="custom.rp")
            mock_get.assert_called_once_with("custom.rp")

            # Verify rp_id in the make_credential call
            call_args = mock_client.make_credential.call_args[0][0]
            assert call_args["rp"]["id"] == "custom.rp"


class TestDeriveIdentityBytes:
    """Tests for derive_identity_bytes()."""

    def _make_mock_client(self, output1: bytes, output2: bytes) -> MagicMock:
        """Create a mock Fido2Client that returns the given hmac-secret outputs."""
        mock_response = MagicMock()
        mock_response.extension_results = {
            "hmacGetSecret": {
                "output1": output1,
                "output2": output2,
            }
        }

        mock_result = MagicMock()
        mock_result.get_response.return_value = mock_response

        mock_client = MagicMock()
        mock_client.get_assertion.return_value = mock_result
        return mock_client

    def _patch_fido2_and_client(self, mock_client):
        """Return a context manager that patches FIDO2_AVAILABLE and _get_fido2_client."""
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("styrened.services.yubikey.FIDO2_AVAILABLE", True))
        stack.enter_context(
            patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client)
        )
        return stack

    def test_returns_64_bytes(self):
        """Should return exactly 64 bytes (32 + 32)."""
        output1 = b"\x01" * 32
        output2 = b"\x02" * 32
        mock_client = self._make_mock_client(output1, output2)

        cred_id = base64.b64encode(b"test-cred").decode()
        with self._patch_fido2_and_client(mock_client):
            result = derive_identity_bytes(cred_id)

        assert len(result) == 64

    def test_output_order_is_encrypt_then_sign(self):
        """X25519 (output1) should be first 32 bytes, Ed25519 (output2) last 32."""
        output1 = b"\xaa" * 32  # encryption key
        output2 = b"\xbb" * 32  # signing seed
        mock_client = self._make_mock_client(output1, output2)

        cred_id = base64.b64encode(b"test-cred").decode()
        with self._patch_fido2_and_client(mock_client):
            result = derive_identity_bytes(cred_id)

        assert result[:32] == output1  # X25519
        assert result[32:] == output2  # Ed25519

    def test_deterministic_for_same_inputs(self):
        """Same credential + salts should yield same output."""
        output1 = b"\xcc" * 32
        output2 = b"\xdd" * 32

        cred_id = base64.b64encode(b"test-cred").decode()

        mock_client1 = self._make_mock_client(output1, output2)
        with self._patch_fido2_and_client(mock_client1):
            result1 = derive_identity_bytes(cred_id)

        mock_client2 = self._make_mock_client(output1, output2)
        with self._patch_fido2_and_client(mock_client2):
            result2 = derive_identity_bytes(cred_id)

        assert result1 == result2

    def test_sends_correct_salts(self):
        """Should send SALT_ENCRYPT as salt1 and SALT_SIGN as salt2."""
        mock_client = self._make_mock_client(b"\x00" * 32, b"\x00" * 32)

        cred_id = base64.b64encode(b"test-cred").decode()
        with self._patch_fido2_and_client(mock_client):
            derive_identity_bytes(cred_id)

        call_args = mock_client.get_assertion.call_args[0][0]
        hmac_ext = call_args["extensions"]["hmacGetSecret"]
        assert hmac_ext["salt1"] == SALT_ENCRYPT
        assert hmac_ext["salt2"] == SALT_SIGN

    def test_decodes_base64_credential_id(self):
        """Should decode the base64 credential ID for the assertion."""
        mock_client = self._make_mock_client(b"\x00" * 32, b"\x00" * 32)

        raw_cred = b"my-raw-credential-id"
        cred_id = base64.b64encode(raw_cred).decode()

        with self._patch_fido2_and_client(mock_client):
            derive_identity_bytes(cred_id)

        call_args = mock_client.get_assertion.call_args[0][0]
        assert call_args["allowCredentials"][0]["id"] == raw_cred

    def test_raises_on_missing_hmac_result(self):
        """Should raise when hmac-secret extension result is missing."""
        mock_response = MagicMock()
        mock_response.extension_results = {}

        mock_result = MagicMock()
        mock_result.get_response.return_value = mock_response

        mock_client = MagicMock()
        mock_client.get_assertion.return_value = mock_result

        cred_id = base64.b64encode(b"test-cred").decode()
        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client),
        ):
            with pytest.raises(YubiKeyCredentialError, match="hmac-secret output"):
                derive_identity_bytes(cred_id)

    def test_raises_on_wrong_output_size(self):
        """Should raise when output sizes are not 32 bytes."""
        mock_client = self._make_mock_client(b"\x00" * 16, b"\x00" * 32)

        cred_id = base64.b64encode(b"test-cred").decode()
        with self._patch_fido2_and_client(mock_client):
            with pytest.raises(YubiKeyCredentialError, match="Invalid hmac-secret output"):
                derive_identity_bytes(cred_id)

    def test_raises_on_assertion_failure(self):
        """Should wrap assertion exceptions in YubiKeyCredentialError."""
        mock_client = MagicMock()
        mock_client.get_assertion.side_effect = RuntimeError("Device disconnected")

        cred_id = base64.b64encode(b"test-cred").decode()
        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.yubikey._get_fido2_client", return_value=mock_client),
        ):
            with pytest.raises(YubiKeyCredentialError, match="Assertion failed"):
                derive_identity_bytes(cred_id)

    def test_passes_rp_id_through(self):
        """Should pass the rp_id to _get_fido2_client."""
        mock_client = self._make_mock_client(b"\x00" * 32, b"\x00" * 32)

        cred_id = base64.b64encode(b"test-cred").decode()
        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey._get_fido2_client", return_value=mock_client
            ) as mock_get,
        ):
            derive_identity_bytes(cred_id, rp_id="custom.rp")
            mock_get.assert_called_once_with("custom.rp")


class TestGetFido2Client:
    """Tests for _get_fido2_client() helper."""

    def test_raises_when_no_devices(self):
        """Should raise YubiKeyNotFoundError when no devices found."""
        from styrened.services.yubikey import _get_fido2_client

        mock_ctap = MagicMock()
        mock_ctap.list_devices.return_value = []

        yubikey_mod = __import__("styrened.services.yubikey", fromlist=["yubikey"])
        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch.object(yubikey_mod, "CtapHidDevice", mock_ctap, create=True),
            patch.object(yubikey_mod, "UserInteraction", MagicMock, create=True),
        ):
            with pytest.raises(YubiKeyNotFoundError, match="No YubiKey detected"):
                _get_fido2_client("test.mesh")

    def test_creates_client_with_first_device(self):
        """Should use the first detected device."""
        from styrened.services.yubikey import _get_fido2_client

        mock_device = MagicMock()
        mock_ctap = MagicMock()
        mock_ctap.list_devices.return_value = [mock_device]
        mock_fido2_cls = MagicMock()
        mock_user_interaction = MagicMock()

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch.object(
                __import__("styrened.services.yubikey", fromlist=["yubikey"]),
                "CtapHidDevice",
                mock_ctap,
                create=True,
            ),
            patch.object(
                __import__("styrened.services.yubikey", fromlist=["yubikey"]),
                "Fido2Client",
                mock_fido2_cls,
                create=True,
            ),
            patch.object(
                __import__("styrened.services.yubikey", fromlist=["yubikey"]),
                "UserInteraction",
                mock_user_interaction,
                create=True,
            ),
        ):
            _get_fido2_client("test.mesh")

            mock_fido2_cls.assert_called_once()
            call_args = mock_fido2_cls.call_args
            assert call_args[0][0] == mock_device
            assert call_args[0][1] == "https://test.mesh"
