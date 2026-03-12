"""Unit tests for LXMF identity detection and sharing."""
from __future__ import annotations


from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from styrened.services.reticulum import (
    KNOWN_LXMF_IDENTITY_PATHS,
    LXMF_SYMLINK_TARGETS,
    detect_existing_lxmf_identity,
    ensure_operator_identity,
    get_identity_sharing_status,
    get_operator_identity,
    share_identity_with_apps,
    unshare_identity_from_apps,
)

# Patch SYSTEM_IDENTITY_PATH to a non-existent path in all tests to avoid
# interference from /etc/styrene/identity on the host machine.
_NO_SYSTEM_IDENTITY = Path("/nonexistent/styrene/identity")


class TestKnownIdentityPaths:
    """Tests for KNOWN_LXMF_IDENTITY_PATHS constant."""

    def test_paths_are_tuples(self):
        """Each entry should be a (name, path) tuple."""
        for entry in KNOWN_LXMF_IDENTITY_PATHS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            name, path = entry
            assert isinstance(name, str)
            assert isinstance(path, Path)

    def test_nomadnet_paths_present(self):
        """NomadNet paths should be included."""
        names = [name for name, _ in KNOWN_LXMF_IDENTITY_PATHS]
        assert any("NomadNet" in name for name in names)

    def test_sideband_paths_present(self):
        """Sideband paths should be included."""
        names = [name for name, _ in KNOWN_LXMF_IDENTITY_PATHS]
        assert any("Sideband" in name for name in names)

    def test_meshchat_paths_present(self):
        """MeshChat paths should be included."""
        names = [name for name, _ in KNOWN_LXMF_IDENTITY_PATHS]
        assert any("MeshChat" in name for name in names)


class TestDetectExistingLxmfIdentity:
    """Tests for detect_existing_lxmf_identity()."""

    def test_returns_none_when_no_identity_exists(self, tmp_path):
        """Should return None when no identity files exist."""
        # Patch the known paths to use temp directory
        fake_paths = [
            ("TestApp", tmp_path / "nonexistent" / "identity"),
        ]
        with patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths):
            result = detect_existing_lxmf_identity()
            assert result is None

    def test_detects_existing_identity(self, tmp_path):
        """Should detect and return existing identity."""
        # Create a fake identity file (minimum 32 bytes)
        identity_dir = tmp_path / "nomadnetwork" / "storage"
        identity_dir.mkdir(parents=True)
        identity_file = identity_dir / "identity"
        identity_file.write_bytes(b"x" * 64)  # Fake identity data

        fake_paths = [
            ("NomadNet", identity_file),
        ]
        with patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths):
            result = detect_existing_lxmf_identity()
            assert result is not None
            app_name, path = result
            assert app_name == "NomadNet"
            assert path == identity_file

    def test_skips_too_small_files(self, tmp_path):
        """Should skip files smaller than 32 bytes."""
        identity_file = tmp_path / "identity"
        identity_file.write_bytes(b"x" * 16)  # Too small

        fake_paths = [
            ("TestApp", identity_file),
        ]
        with patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths):
            result = detect_existing_lxmf_identity()
            assert result is None

    def test_priority_order_respected(self, tmp_path):
        """Should return first valid identity in priority order."""
        # Create two identity files
        first_identity = tmp_path / "first" / "identity"
        first_identity.parent.mkdir(parents=True)
        first_identity.write_bytes(b"first" * 20)

        second_identity = tmp_path / "second" / "identity"
        second_identity.parent.mkdir(parents=True)
        second_identity.write_bytes(b"second" * 20)

        fake_paths = [
            ("FirstApp", first_identity),
            ("SecondApp", second_identity),
        ]
        with patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths):
            result = detect_existing_lxmf_identity()
            assert result is not None
            app_name, _ = result
            assert app_name == "FirstApp"

    def test_skips_unreadable_files(self, tmp_path):
        """Should skip files that can't be read."""
        # Create a directory instead of a file (can't read as bytes)
        identity_path = tmp_path / "identity"
        identity_path.mkdir()

        fake_paths = [
            ("TestApp", identity_path),
        ]
        with patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths):
            result = detect_existing_lxmf_identity()
            assert result is None


class TestEnsureOperatorIdentityWithDetection:
    """Tests for ensure_operator_identity() with identity detection."""

    @pytest.fixture
    def mock_rns(self):
        """Mock RNS module."""
        mock = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "a" * 32
        mock.Identity.return_value = mock_identity
        mock.Identity.from_file.return_value = mock_identity
        return mock

    def test_loads_existing_styrened_identity(self, tmp_path, mock_rns):
        """Should load existing styrened identity without checking others."""
        styrened_identity = tmp_path / "operator.key"
        styrened_identity.write_bytes(b"x" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            result = ensure_operator_identity()
            assert result == "a" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(styrened_identity))

    def test_imports_existing_lxmf_identity(self, tmp_path, mock_rns):
        """Should import existing LXMF identity when no styrened identity exists."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        # Don't create it - simulate first run

        nomadnet_identity = tmp_path / "nomadnetwork" / "storage" / "identity"
        nomadnet_identity.parent.mkdir(parents=True)
        nomadnet_identity.write_bytes(b"nomad" * 20)

        fake_paths = [
            ("NomadNet", nomadnet_identity),
        ]

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
            patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths),
        ):
            result = ensure_operator_identity(use_existing=True)
            assert result == "a" * 32
            # Should load from NomadNet path
            mock_rns.Identity.from_file.assert_called_with(str(nomadnet_identity))
            # Should save to styrened path
            mock_rns.Identity.from_file.return_value.to_file.assert_called()

    def test_creates_new_when_use_existing_false(self, tmp_path, mock_rns):
        """Should create new identity when use_existing=False."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        # Don't create it

        nomadnet_identity = tmp_path / "nomadnetwork" / "storage" / "identity"
        nomadnet_identity.parent.mkdir(parents=True)
        nomadnet_identity.write_bytes(b"nomad" * 20)

        fake_paths = [
            ("NomadNet", nomadnet_identity),
        ]

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
            patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths),
        ):
            result = ensure_operator_identity(use_existing=False)
            assert result == "a" * 32
            # Should create new identity, not load from NomadNet
            mock_rns.Identity.assert_called_once_with(create_keys=True)

    def test_creates_new_when_no_existing_found(self, tmp_path, mock_rns):
        """Should create new identity when no existing LXMF identity found."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        # Don't create it

        fake_paths = [
            ("NomadNet", tmp_path / "nonexistent" / "identity"),
        ]

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
            patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths),
        ):
            result = ensure_operator_identity(use_existing=True)
            assert result == "a" * 32
            # Should create new identity
            mock_rns.Identity.assert_called_once_with(create_keys=True)

    def test_creates_new_when_existing_invalid(self, tmp_path, mock_rns):
        """Should create new identity when existing LXMF identity is invalid."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        # Don't create it

        nomadnet_identity = tmp_path / "nomadnetwork" / "storage" / "identity"
        nomadnet_identity.parent.mkdir(parents=True)
        nomadnet_identity.write_bytes(b"nomad" * 20)

        fake_paths = [
            ("NomadNet", nomadnet_identity),
        ]

        # Make from_file return None for the NomadNet identity (invalid)
        mock_rns.Identity.from_file.return_value = None

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
            patch("styrened.services.reticulum.KNOWN_LXMF_IDENTITY_PATHS", fake_paths),
        ):
            result = ensure_operator_identity(use_existing=True)
            assert result == "a" * 32
            # Should create new identity after failing to load existing
            mock_rns.Identity.assert_called_with(create_keys=True)


class TestEnsureOperatorIdentityCorruptRecovery:
    """Tests for self-healing when operator.key is corrupt."""

    @pytest.fixture
    def mock_rns(self):
        """Mock RNS module where from_file fails on corrupt data."""
        mock = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "b" * 32
        mock.Identity.return_value = mock_identity
        # from_file returns None for corrupt files (first call),
        # normal identity for regenerated (second call, if any)
        mock.Identity.from_file.return_value = None
        return mock

    def test_corrupt_identity_backed_up_and_regenerated(self, tmp_path, mock_rns):
        """Corrupt identity should be backed up and a new one generated."""
        identity_file = tmp_path / "operator.key"
        identity_file.write_bytes(b"x" * 32)  # Wrong size / format

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=identity_file),
        ):
            result = ensure_operator_identity(use_existing=False)

        assert result == "b" * 32
        # Original file should be gone
        assert not identity_file.exists()
        # Backup should exist
        backup = tmp_path / "operator.key.corrupt"
        assert backup.exists()
        assert backup.read_bytes() == b"x" * 32
        # New identity should have been created
        mock_rns.Identity.assert_called_with(create_keys=True)

    def test_corrupt_identity_exception_also_recovers(self, tmp_path, mock_rns):
        """Identity file that raises on load should also be backed up."""
        identity_file = tmp_path / "operator.key"
        identity_file.write_bytes(b"bad")

        mock_rns.Identity.from_file.side_effect = [
            Exception("An Ed25519 private key is 32 bytes long"),
            None,  # won't be called, but just in case
        ]

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=identity_file),
        ):
            result = ensure_operator_identity(use_existing=False)

        assert result == "b" * 32
        assert not identity_file.exists()
        backup = tmp_path / "operator.key.corrupt"
        assert backup.exists()
        assert backup.read_bytes() == b"bad"

    def test_corrupt_identity_backup_failure_raises(self, tmp_path, mock_rns):
        """If backup rename fails, should raise with manual instructions."""
        identity_file = tmp_path / "operator.key"
        identity_file.write_bytes(b"x" * 32)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=identity_file),
            patch.object(type(identity_file), "rename", side_effect=OSError("Permission denied")),
        ):
            with pytest.raises(ValueError, match="corrupt and could not be backed up"):
                ensure_operator_identity(use_existing=False)


class TestEnsureOperatorIdentityYubiKey:
    """Tests for ensure_operator_identity() with YubiKey provider."""

    @pytest.fixture
    def mock_rns(self):
        """Mock RNS module."""
        mock = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "y" * 32
        mock.Identity.from_bytes.return_value = mock_identity
        return mock

    def test_yubikey_provider_calls_derive(self, mock_rns):
        """Should call derive_identity_bytes when provider is 'yubikey'."""
        from styrened.models.config import IdentityConfig, YubiKeyConfig

        identity_config = IdentityConfig(
            provider="yubikey",
            yubikey=YubiKeyConfig(
                credential_id="dGVzdA==",
                rp_id="test.mesh",
                require_touch=False,
            ),
        )

        fake_bytes = b"\xaa" * 32 + b"\xbb" * 32

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch(
                "styrened.services.yubikey.derive_identity_bytes",
                return_value=fake_bytes,
            ) as mock_derive,
        ):
            result = ensure_operator_identity(identity_config=identity_config)

            mock_derive.assert_called_once_with(
                credential_id_b64="dGVzdA==",
                rp_id="test.mesh",
                require_touch=False,
            )
            mock_rns.Identity.from_bytes.assert_called_once_with(fake_bytes)
            assert result == "y" * 32

    def test_yubikey_provider_raises_on_invalid_identity(self, mock_rns):
        """Should raise ValueError when RNS.Identity.from_bytes returns None."""
        from styrened.models.config import IdentityConfig, YubiKeyConfig

        identity_config = IdentityConfig(
            provider="yubikey",
            yubikey=YubiKeyConfig(credential_id="dGVzdA=="),
        )

        mock_rns.Identity.from_bytes.return_value = None

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch(
                "styrened.services.yubikey.derive_identity_bytes",
                return_value=b"\x00" * 64,
            ),
        ):
            with pytest.raises(ValueError, match="YubiKey-derived bytes"):
                ensure_operator_identity(identity_config=identity_config)

    def test_file_provider_skips_yubikey(self, tmp_path, mock_rns):
        """Should use file-based path when provider is 'file'."""
        from styrened.models.config import IdentityConfig

        identity_config = IdentityConfig(provider="file")

        styrened_identity = tmp_path / "operator.key"
        styrened_identity.write_bytes(b"x" * 64)

        mock_rns.Identity.from_file.return_value = mock_rns.Identity.from_bytes.return_value

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            result = ensure_operator_identity(identity_config=identity_config)
            assert result == "y" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(styrened_identity))

    def test_none_identity_config_uses_file_path(self, tmp_path):
        """Should behave as before when identity_config is None."""
        mock_rns = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "a" * 32
        mock_rns.Identity.from_file.return_value = mock_identity

        styrened_identity = tmp_path / "operator.key"
        styrened_identity.write_bytes(b"x" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            result = ensure_operator_identity(identity_config=None)
            assert result == "a" * 32


class TestSymlinkTargets:
    """Tests for LXMF_SYMLINK_TARGETS constant."""

    def test_has_expected_apps(self):
        """Should have entries for known LXMF applications."""
        assert "nomadnet" in LXMF_SYMLINK_TARGETS
        assert "sideband" in LXMF_SYMLINK_TARGETS
        assert "meshchat" in LXMF_SYMLINK_TARGETS
        assert "lxmf" in LXMF_SYMLINK_TARGETS

    def test_paths_are_path_objects(self):
        """All values should be Path objects."""
        for app, path in LXMF_SYMLINK_TARGETS.items():
            assert isinstance(path, Path), f"{app} path is not a Path"


class TestGetIdentitySharingStatus:
    """Tests for get_identity_sharing_status()."""

    def test_returns_status_for_all_apps(self, tmp_path):
        """Should return status for all known applications."""
        fake_targets = {
            "app1": tmp_path / "app1" / "identity",
            "app2": tmp_path / "app2" / "identity",
        }
        with patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets):
            status = get_identity_sharing_status()
            assert "app1" in status
            assert "app2" in status

    def test_detects_nonexistent_path(self, tmp_path):
        """Should detect when identity path doesn't exist."""
        fake_targets = {"testapp": tmp_path / "nonexistent" / "identity"}
        with patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets):
            status = get_identity_sharing_status()
            assert status["testapp"]["exists"] is False
            assert status["testapp"]["is_symlink"] is False

    def test_detects_regular_file(self, tmp_path):
        """Should detect regular identity file."""
        identity_file = tmp_path / "identity"
        identity_file.write_bytes(b"x" * 64)

        fake_targets = {"testapp": identity_file}
        with patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets):
            status = get_identity_sharing_status()
            assert status["testapp"]["exists"] is True
            assert status["testapp"]["is_symlink"] is False
            assert status["testapp"]["points_to_styrened"] is False

    def test_detects_symlink_to_styrened(self, tmp_path):
        """Should detect symlink pointing to styrened."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(styrened_identity)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            status = get_identity_sharing_status()
            assert status["testapp"]["exists"] is True
            assert status["testapp"]["is_symlink"] is True
            assert status["testapp"]["points_to_styrened"] is True


class TestShareIdentityWithApps:
    """Tests for share_identity_with_apps()."""

    def test_raises_if_styrened_identity_missing(self, tmp_path):
        """Should raise FileNotFoundError if styrened identity doesn't exist."""
        styrened_identity = tmp_path / "nonexistent" / "operator.key"
        with (
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            with pytest.raises(FileNotFoundError):
                share_identity_with_apps()

    def test_creates_symlink_for_app(self, tmp_path):
        """Should create symlink from app to styrened identity."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = share_identity_with_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is True
            assert app_identity.is_symlink()
            assert app_identity.resolve() == styrened_identity

    def test_skips_existing_without_force(self, tmp_path):
        """Should skip existing files without force flag."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.write_bytes(b"existing" * 10)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = share_identity_with_apps(apps=["testapp"], force=False)
            assert len(results) == 1
            assert results[0].success is False
            assert "exists" in results[0].message
            # Original file should be unchanged
            assert app_identity.read_bytes() == b"existing" * 10

    def test_replaces_existing_with_force_and_backup(self, tmp_path):
        """Should backup and replace existing files with force flag."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.write_bytes(b"original" * 10)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = share_identity_with_apps(apps=["testapp"], force=True, backup=True)
            assert len(results) == 1
            assert results[0].success is True
            assert results[0].backed_up_to is not None
            # Backup should exist with original content
            assert results[0].backed_up_to.read_bytes() == b"original" * 10
            # New symlink should point to styrened
            assert app_identity.is_symlink()
            assert app_identity.resolve() == styrened_identity

    def test_reports_already_symlinked(self, tmp_path):
        """Should report success when already correctly symlinked."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(styrened_identity)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = share_identity_with_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is True
            assert "Already symlinked" in results[0].message

    def test_unknown_app_returns_error(self, tmp_path):
        """Should return error for unknown application name."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        with (
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = share_identity_with_apps(apps=["unknownapp"])
            assert len(results) == 1
            assert results[0].success is False
            assert "Unknown application" in results[0].message


class TestUnshareIdentityFromApps:
    """Tests for unshare_identity_from_apps()."""

    def test_removes_symlink(self, tmp_path):
        """Should remove symlink pointing to styrened."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(styrened_identity)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = unshare_identity_from_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is True
            assert not app_identity.exists()

    def test_restores_backup(self, tmp_path):
        """Should restore backup file when unsharing."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(styrened_identity)

        # Create backup file
        backup_file = app_identity.with_suffix(".key.bak")
        backup_file.write_bytes(b"original" * 10)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = unshare_identity_from_apps(apps=["testapp"], restore_backup=True)
            assert len(results) == 1
            assert results[0].success is True
            # Original identity should be restored
            assert app_identity.exists()
            assert not app_identity.is_symlink()
            assert app_identity.read_bytes() == b"original" * 10
            # Backup should be gone (renamed to identity)
            assert not backup_file.exists()

    def test_leaves_non_styrened_symlink_alone(self, tmp_path):
        """Should not remove symlinks that don't point to styrened."""
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        other_identity = tmp_path / "other" / "identity"
        other_identity.parent.mkdir(parents=True)
        other_identity.write_bytes(b"other" * 10)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(other_identity)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = unshare_identity_from_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is False
            assert "doesn't point to styrened" in results[0].message
            # Symlink should still exist
            assert app_identity.is_symlink()

    def test_leaves_regular_file_alone(self, tmp_path):
        """Should not touch regular files (not symlinks)."""
        styrened_identity = tmp_path / "styrene" / "operator.key"

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.write_bytes(b"regular" * 10)

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = unshare_identity_from_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is False
            assert "Not a symlink" in results[0].message
            # File should be unchanged
            assert app_identity.read_bytes() == b"regular" * 10

    def test_removes_broken_symlink_to_deleted_identity(self, tmp_path):
        """Should remove symlink even if the target identity was deleted."""
        # Create identity, symlink to it, then delete the identity
        styrened_identity = tmp_path / "styrene" / "operator.key"
        styrened_identity.parent.mkdir(parents=True)
        styrened_identity.write_bytes(b"x" * 64)

        app_identity = tmp_path / "app" / "identity"
        app_identity.parent.mkdir(parents=True)
        app_identity.symlink_to(styrened_identity)

        # Now delete the identity — symlink becomes broken
        styrened_identity.unlink()

        fake_targets = {"testapp": app_identity}
        with (
            patch("styrened.services.reticulum.LXMF_SYMLINK_TARGETS", fake_targets),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=styrened_identity),
        ):
            results = unshare_identity_from_apps(apps=["testapp"])
            assert len(results) == 1
            assert results[0].success is True
            assert not app_identity.is_symlink()


class TestSystemIdentityPath:
    """Tests for OS-level identity path resolution (/etc/styrene/identity)."""

    @pytest.fixture
    def mock_rns(self):
        """Mock RNS module."""
        mock = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "b" * 32
        mock.Identity.return_value = mock_identity
        mock.Identity.from_file.return_value = mock_identity
        return mock

    def test_system_path_takes_priority_over_user_path(self, tmp_path, mock_rns):
        """Should load from system path when both system and user paths exist."""
        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"s" * 64)

        user_identity = tmp_path / "user" / "operator.key"
        user_identity.parent.mkdir(parents=True)
        user_identity.write_bytes(b"u" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=user_identity),
        ):
            result = ensure_operator_identity()
            assert result == "b" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(system_identity))

    def test_falls_back_to_user_path_when_no_system(self, tmp_path, mock_rns):
        """Should fall back to user path when system path doesn't exist."""
        user_identity = tmp_path / "user" / "operator.key"
        user_identity.parent.mkdir(parents=True)
        user_identity.write_bytes(b"u" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=user_identity),
        ):
            result = ensure_operator_identity()
            assert result == "b" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(user_identity))

    def test_config_path_overrides_system_path(self, tmp_path, mock_rns):
        """Config override should take priority over system path."""
        config_identity = tmp_path / "config" / "custom.key"
        config_identity.parent.mkdir(parents=True)
        config_identity.write_bytes(b"c" * 64)

        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"s" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = ensure_operator_identity(config_path=config_identity)
            assert result == "b" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(config_identity))


class TestGetOperatorIdentity:
    """Tests for get_operator_identity() including fallback behavior."""

    @pytest.fixture
    def mock_rns(self):
        """Mock RNS module."""
        mock = MagicMock()
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "c" * 32
        mock.Identity.from_file.return_value = mock_identity
        return mock

    def test_returns_hash_from_system_identity(self, tmp_path, mock_rns):
        """Should return identity hash when system identity exists and RNS works."""
        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"s" * 64)

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = get_operator_identity()
            assert result == "c" * 32
            mock_rns.Identity.from_file.assert_called_once_with(str(system_identity))

    def test_returns_none_when_rns_unavailable(self, tmp_path):
        """Should return None when RNS library is not available."""
        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"s" * 64)

        with (
            patch("styrened.services.reticulum.RNS", None),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = get_operator_identity()
            assert result is None

    def test_returns_none_when_from_file_returns_none(self, tmp_path, mock_rns):
        """Should return None when RNS can't parse the identity file."""
        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"bad" * 5)

        mock_rns.Identity.from_file.return_value = None

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = get_operator_identity()
            assert result is None

    def test_returns_none_when_no_identity_exists(self):
        """Should return None when no identity file exists anywhere."""
        with (
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", _NO_SYSTEM_IDENTITY),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = get_operator_identity()
            assert result is None

    def test_returns_none_when_from_file_raises(self, tmp_path, mock_rns):
        """Should return None when RNS.Identity.from_file raises an exception."""
        system_identity = tmp_path / "etc" / "styrene" / "identity"
        system_identity.parent.mkdir(parents=True)
        system_identity.write_bytes(b"s" * 64)

        mock_rns.Identity.from_file.side_effect = Exception("corrupt key")

        with (
            patch("styrened.services.reticulum.RNS", mock_rns),
            patch("styrened.services.reticulum.SYSTEM_IDENTITY_PATH", system_identity),
            patch("styrened.paths.identity_file", return_value=_NO_SYSTEM_IDENTITY),
        ):
            result = get_operator_identity()
            assert result is None


class TestLifecycleIdentityWiring:
    """Tests that CoreLifecycle wires config override to ensure_operator_identity."""

    def _patch_lifecycle(self):
        """Patch lifecycle dependencies to isolate identity wiring.

        Mocks ensure_operator_identity, get_rns_service, and
        get_operator_identity_object so the test only exercises the
        config_path plumbing without touching real singletons.
        """
        from contextlib import ExitStack

        stack = ExitStack()
        mock_ensure = stack.enter_context(
            patch(
                "styrened.services.lifecycle.ensure_operator_identity",
                return_value="a" * 32,
            )
        )
        mock_rns_svc = MagicMock()
        mock_rns_svc.initialize.return_value = True
        mock_rns_svc.create_operator_destination.return_value = None
        stack.enter_context(
            patch("styrened.services.lifecycle.get_rns_service", return_value=mock_rns_svc)
        )
        stack.enter_context(
            patch("styrened.services.lifecycle.get_operator_identity_object", return_value=None)
        )
        return stack, mock_ensure

    def test_lifecycle_passes_config_override(self, tmp_path):
        """Config operator_identity_path should reach ensure_operator_identity as config_path."""
        from styrened.models.config import CoreConfig, ReticulumConfig
        from styrened.services.lifecycle import CoreLifecycle

        custom_path = tmp_path / "custom" / "identity"
        config = CoreConfig(
            reticulum=ReticulumConfig(operator_identity_path=custom_path),
        )

        stack, mock_ensure = self._patch_lifecycle()
        with stack:
            lifecycle = CoreLifecycle(config)
            lifecycle._initialize_reticulum()
            mock_ensure.assert_called_once_with(
                config_path=custom_path,
                identity_config=config.identity,
            )

    def test_lifecycle_passes_none_when_no_override(self):
        """No config override should pass None, letting _resolve_identity_path decide."""
        from styrened.models.config import CoreConfig
        from styrened.services.lifecycle import CoreLifecycle

        config = CoreConfig()  # No operator_identity_path set

        stack, mock_ensure = self._patch_lifecycle()
        with stack:
            lifecycle = CoreLifecycle(config)
            lifecycle._initialize_reticulum()
            mock_ensure.assert_called_once_with(
                config_path=None,
                identity_config=config.identity,
            )

    def test_lifecycle_passes_yubikey_identity_config(self, tmp_path):
        """YubiKey identity config should reach ensure_operator_identity."""
        from styrened.models.config import (
            CoreConfig,
            IdentityConfig,
            YubiKeyConfig,
        )
        from styrened.services.lifecycle import CoreLifecycle

        identity_config = IdentityConfig(
            provider="yubikey",
            yubikey=YubiKeyConfig(credential_id="dGVzdA==", rp_id="test.mesh"),
        )
        config = CoreConfig(identity=identity_config)

        stack, mock_ensure = self._patch_lifecycle()
        with stack:
            lifecycle = CoreLifecycle(config)
            lifecycle._initialize_reticulum()
            mock_ensure.assert_called_once_with(
                config_path=None,
                identity_config=identity_config,
            )
