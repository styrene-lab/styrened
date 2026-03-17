"""Unit tests for YubiKey CLI commands."""
from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

from styrened.cli import cmd_identity_yubikey_derive, cmd_identity_yubikey_setup


class TestIdentityYubiKeySetup:
    """Tests for identity-yubikey-setup CLI command."""

    def test_missing_fido2_returns_error(self, capsys):
        """Should return 1 with install guidance when fido2 is missing."""
        args = argparse.Namespace(rp_id="styrene.mesh", json=False)

        with patch(
            "styrened.services.yubikey.FIDO2_AVAILABLE", False,
        ):
            result = cmd_identity_yubikey_setup(args)

        assert result == 1
        assert "pip install" in capsys.readouterr().err

    def test_successful_setup_text_output(self, capsys):
        """Should print config snippet on success."""
        args = argparse.Namespace(rp_id="styrene.mesh", json=False)

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.yubikey.setup_credential", return_value="dGVzdENyZWQ="),
        ):
            result = cmd_identity_yubikey_setup(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "dGVzdENyZWQ=" in output
        assert 'provider: "yubikey"' in output
        assert "styrene.mesh" in output

    def test_successful_setup_json_output(self, capsys):
        """Should output JSON with credential_id and rp_id."""
        args = argparse.Namespace(rp_id="custom.mesh", json=True)

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.yubikey.setup_credential", return_value="Y3JlZA=="),
        ):
            result = cmd_identity_yubikey_setup(args)

        assert result == 0
        output = json.loads(capsys.readouterr().out)
        assert output["credential_id"] == "Y3JlZA=="
        assert output["rp_id"] == "custom.mesh"

    def test_setup_error_returns_1(self, capsys):
        """Should return 1 and print error on setup failure."""
        args = argparse.Namespace(rp_id="styrene.mesh", json=False)

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey.setup_credential",
                side_effect=RuntimeError("YubiKey not found"),
            ),
        ):
            result = cmd_identity_yubikey_setup(args)

        assert result == 1
        assert "YubiKey not found" in capsys.readouterr().err

    def test_custom_rp_id_passed_through(self):
        """Should pass rp_id to setup_credential."""
        args = argparse.Namespace(rp_id="my.custom.rp", json=False)

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey.setup_credential", return_value="Y3JlZA=="
            ) as mock_setup,
        ):
            cmd_identity_yubikey_setup(args)
            mock_setup.assert_called_once_with(rp_id="my.custom.rp")


class TestIdentityYubiKeyDerive:
    """Tests for identity-yubikey-derive CLI command."""

    def test_missing_fido2_returns_error(self, capsys):
        """Should return 1 with install guidance when fido2 is missing."""
        args = argparse.Namespace(credential_id=None, rp_id=None, json=False)

        with patch("styrened.services.yubikey.FIDO2_AVAILABLE", False):
            result = cmd_identity_yubikey_derive(args)

        assert result == 1
        assert "pip install" in capsys.readouterr().err

    def test_successful_derive_text_output(self, capsys):
        """Should print identity hash on success."""
        args = argparse.Namespace(credential_id="dGVzdA==", rp_id="styrene.mesh", json=False)

        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "ab" * 16

        mock_rns = MagicMock()
        mock_rns.Identity.from_bytes.return_value = mock_identity

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey.derive_identity_bytes", return_value=b"\x00" * 64
            ),
            patch.dict("sys.modules", {"RNS": mock_rns}),
        ):
            result = cmd_identity_yubikey_derive(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "ab" * 16 in output
        assert "yubikey" in output

    def test_successful_derive_json_output(self, capsys):
        """Should output JSON with identity_hash."""
        args = argparse.Namespace(credential_id="dGVzdA==", rp_id="styrene.mesh", json=True)

        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "cd" * 16

        mock_rns = MagicMock()
        mock_rns.Identity.from_bytes.return_value = mock_identity

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey.derive_identity_bytes", return_value=b"\x00" * 64
            ),
            patch.dict("sys.modules", {"RNS": mock_rns}),
        ):
            result = cmd_identity_yubikey_derive(args)

        assert result == 0
        output = json.loads(capsys.readouterr().out)
        assert output["identity_hash"] == "cd" * 16
        assert output["provider"] == "yubikey"

    def test_reads_credential_from_config(self, capsys):
        """Should read credential_id from config when not on command line."""
        args = argparse.Namespace(credential_id=None, rp_id=None, json=False)

        from styrened.models.config import CoreConfig, IdentityConfig, YubiKeyConfig

        config = CoreConfig(
            identity=IdentityConfig(
                provider="yubikey",
                yubikey=YubiKeyConfig(
                    credential_id="Y29uZmlnQ3JlZA==",
                    rp_id="config.mesh",
                ),
            )
        )

        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "ee" * 16

        mock_rns = MagicMock()
        mock_rns.Identity.from_bytes.return_value = mock_identity

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.config.load_core_config", return_value=config),
            patch(
                "styrened.services.yubikey.derive_identity_bytes", return_value=b"\x00" * 64
            ) as mock_derive,
            patch.dict("sys.modules", {"RNS": mock_rns}),
        ):
            result = cmd_identity_yubikey_derive(args)

        assert result == 0
        mock_derive.assert_called_once_with(
            credential_id_b64="Y29uZmlnQ3JlZA==",
            rp_id="config.mesh",
        )

    def test_no_credential_returns_error(self, capsys):
        """Should return 1 when no credential_id is available."""
        args = argparse.Namespace(credential_id=None, rp_id=None, json=False)

        from styrened.models.config import CoreConfig

        config = CoreConfig()  # provider is "file", no yubikey config

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch("styrened.services.config.load_core_config", return_value=config),
        ):
            result = cmd_identity_yubikey_derive(args)

        assert result == 1
        assert "No credential_id" in capsys.readouterr().err

    def test_derive_error_returns_1(self, capsys):
        """Should return 1 and print error on derivation failure."""
        args = argparse.Namespace(credential_id="dGVzdA==", rp_id="styrene.mesh", json=False)

        with (
            patch("styrened.services.yubikey.FIDO2_AVAILABLE", True),
            patch(
                "styrened.services.yubikey.derive_identity_bytes",
                side_effect=RuntimeError("Device disconnected"),
            ),
        ):
            result = cmd_identity_yubikey_derive(args)

        assert result == 1
        assert "Device disconnected" in capsys.readouterr().err
