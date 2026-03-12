"""Unit tests for doctor binary checks (tasks 3.1–3.4).

Tests binary presence, integrity (SHA-256), version checking,
and --fix provisioning for adapter binaries (yggdrasil, i2pd).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.daemon_mode import DaemonMode
from styrened.services.doctor import (
    CheckCategory,
    Finding,
    Severity,
    check_adapter_binaries,
    fix_adapter_binaries,
)

_DOCTOR = "styrened.services.doctor"


def _make_config(ygg_mode=DaemonMode.DISABLED, i2p_mode=DaemonMode.DISABLED):
    """Build a minimal config-like object for testing."""
    config = MagicMock()
    config.yggdrasil.mode = ygg_mode
    config.yggdrasil.binary_path = "yggdrasil"
    config.i2p.mode = i2p_mode
    config.i2p.binary_path = "i2pd"
    return config


def _mock_adapter(binary_path=None):
    adapter = MagicMock()
    adapter._find_binary.return_value = binary_path
    return adapter


# ── Skipping disabled adapters ──────────────────────────────────────────────


class TestSkipsDisabledAdapters:
    @pytest.mark.asyncio
    async def test_disabled_yggdrasil_produces_no_findings(self):
        config = _make_config(ygg_mode=DaemonMode.DISABLED)
        findings = await check_adapter_binaries(config)
        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        assert ygg == []

    @pytest.mark.asyncio
    async def test_disabled_i2p_produces_no_findings(self):
        config = _make_config(i2p_mode=DaemonMode.DISABLED)
        findings = await check_adapter_binaries(config)
        i2p = [f for f in findings if f.category == CheckCategory.I2P]
        assert i2p == []


# ── Binary not found ────────────────────────────────────────────────────────


class TestBinaryNotFound:
    @pytest.mark.asyncio
    async def test_yggdrasil_not_found(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path=None)
        with patch(f"{_DOCTOR}._make_adapter", return_value=adapter):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        not_found = [f for f in ygg if "not found" in f.message]
        assert len(not_found) == 1
        assert not_found[0].severity == Severity.ERROR
        assert "✗" in not_found[0].message

    @pytest.mark.asyncio
    async def test_i2p_not_found(self):
        config = _make_config(i2p_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path=None)
        with patch(f"{_DOCTOR}._make_adapter", return_value=adapter):
            findings = await check_adapter_binaries(config)

        i2p = [f for f in findings if f.category == CheckCategory.I2P]
        not_found = [f for f in i2p if "not found" in f.message]
        assert len(not_found) == 1
        assert not_found[0].severity == Severity.ERROR
        assert "✗" in not_found[0].message


# ── Binary found, hash matches ──────────────────────────────────────────────


class TestBinaryHashMatches:
    @pytest.mark.asyncio
    async def test_yggdrasil_found_and_hash_matches(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        fake_hash = "abc123def456" * 4
        adapter = _mock_adapter(binary_path="/usr/bin/yggdrasil")

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._hash_file", return_value=fake_hash),
            patch(f"{_DOCTOR}._get_manifest_entry", return_value={"binary_sha256": fake_hash}),
            patch(f"{_DOCTOR}._check_binary_version", return_value="0.5.13"),
            patch(f"{_DOCTOR}._get_manifest_version", return_value="0.5.13"),
        ):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        ok = [f for f in ygg if f.severity == Severity.OK]
        assert len(ok) >= 1
        assert any("✓" in f.message and "found" in f.message for f in ok)


# ── Binary found, hash mismatch ─────────────────────────────────────────────


class TestBinaryHashMismatch:
    @pytest.mark.asyncio
    async def test_yggdrasil_hash_mismatch(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path="/usr/bin/yggdrasil")

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._hash_file", return_value="actual_hash_aaa_full_length_pad"),
            patch(f"{_DOCTOR}._get_manifest_entry", return_value={"binary_sha256": "expected_hash_bbb_full_length"}),
            patch(f"{_DOCTOR}._check_binary_version", return_value=None),
            patch(f"{_DOCTOR}._get_manifest_version", return_value=None),
        ):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        warn = [f for f in ygg if f.severity == Severity.WARN]
        mismatch = [f for f in warn if "mismatch" in f.message]
        assert len(mismatch) == 1
        assert "⚠" in mismatch[0].message
        # Message includes truncated hashes (first 12 chars)
        assert "expected_has" in mismatch[0].message


# ── Version check ────────────────────────────────────────────────────────────


class TestVersionCheck:
    @pytest.mark.asyncio
    async def test_version_matches_manifest(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path="/usr/bin/yggdrasil")

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._hash_file", return_value="good_hash"),
            patch(f"{_DOCTOR}._get_manifest_entry", return_value={"binary_sha256": "good_hash"}),
            patch(f"{_DOCTOR}._check_binary_version", return_value="0.5.13"),
            patch(f"{_DOCTOR}._get_manifest_version", return_value="0.5.13"),
        ):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        assert any("0.5.13" in f.message for f in ygg)

    @pytest.mark.asyncio
    async def test_version_mismatch(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path="/usr/bin/yggdrasil")

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._hash_file", return_value="good_hash"),
            patch(f"{_DOCTOR}._get_manifest_entry", return_value={"binary_sha256": "good_hash"}),
            patch(f"{_DOCTOR}._check_binary_version", return_value="0.4.0"),
            patch(f"{_DOCTOR}._get_manifest_version", return_value="0.5.13"),
        ):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        warn = [f for f in ygg if f.severity == Severity.WARN and "version" in f.message.lower()]
        assert len(warn) >= 1


# ── --fix mode ───────────────────────────────────────────────────────────────


class TestFixMode:
    @pytest.mark.asyncio
    async def test_fix_provisions_missing_binary(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path=None)

        mock_provisioner = MagicMock()
        mock_provisioner.provision = AsyncMock(return_value=True)

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._get_provisioner", return_value=mock_provisioner),
        ):
            findings = await fix_adapter_binaries(config)

        mock_provisioner.provision.assert_called_once_with("yggdrasil")
        ok = [f for f in findings if f.severity == Severity.OK]
        assert any("✓" in f.message and "installed" in f.message for f in ok)

    @pytest.mark.asyncio
    async def test_fix_reports_error_on_provision_failure(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path=None)

        mock_provisioner = MagicMock()
        mock_provisioner.provision = AsyncMock(side_effect=RuntimeError("download failed"))

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._get_provisioner", return_value=mock_provisioner),
        ):
            findings = await fix_adapter_binaries(config)

        err = [f for f in findings if f.severity == Severity.ERROR]
        assert len(err) >= 1
        assert any("failed" in f.message.lower() for f in err)

    @pytest.mark.asyncio
    async def test_fix_skips_already_present_binary(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path="/usr/bin/yggdrasil")

        mock_provisioner = MagicMock()
        mock_provisioner.provision = AsyncMock()

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._hash_file", return_value="good"),
            patch(f"{_DOCTOR}._get_manifest_entry", return_value={"binary_sha256": "good"}),
            patch(f"{_DOCTOR}._check_binary_version", return_value="0.5.13"),
            patch(f"{_DOCTOR}._get_provisioner", return_value=mock_provisioner),
        ):
            findings = await fix_adapter_binaries(config)

        mock_provisioner.provision.assert_not_called()


# ── ADOPT mode also checked ──────────────────────────────────────────────────


class TestAdoptMode:
    @pytest.mark.asyncio
    async def test_adopt_mode_checks_binary_warn(self):
        """ADOPT mode with missing binary reports WARN (not ERROR)."""
        config = _make_config(ygg_mode=DaemonMode.ADOPT)
        adapter = _mock_adapter(binary_path=None)

        with patch(f"{_DOCTOR}._make_adapter", return_value=adapter):
            findings = await check_adapter_binaries(config)

        ygg = [f for f in findings if f.category == CheckCategory.YGGDRASIL]
        assert len(ygg) >= 1
        assert any("not found" in f.message for f in ygg)
        # ADOPT → WARN, not ERROR
        assert all(f.severity == Severity.WARN for f in ygg if "not found" in f.message)


# ── No provisioner available ─────────────────────────────────────────────────


class TestNoProvisioner:
    @pytest.mark.asyncio
    async def test_fix_without_provisioner_reports_error(self):
        config = _make_config(ygg_mode=DaemonMode.MANAGED)
        adapter = _mock_adapter(binary_path=None)

        with (
            patch(f"{_DOCTOR}._make_adapter", return_value=adapter),
            patch(f"{_DOCTOR}._get_provisioner", return_value=None),
        ):
            findings = await fix_adapter_binaries(config)

        err = [f for f in findings if f.severity == Severity.ERROR]
        assert len(err) >= 1
        assert any("not available" in f.message for f in err)
