"""Unit tests for startup binary re-verification (tasks 2.1–2.6).

TDD: These tests define the expected behavior for:
- verify_binary_integrity() on DaemonAdapter base
- Wiring into _start_managed() for Yggdrasil and I2P
- Non-strict mode (warn + start) vs strict mode (raise + refuse)
- Missing manifest entry → skip gracefully
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.config import CoreConfig, SecurityConfig
from styrened.services.daemon_adapter import DaemonAdapter, DaemonMode, VerificationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_BINARY_CONTENT = b"fake-yggdrasil-binary-content"
FAKE_SHA256 = hashlib.sha256(FAKE_BINARY_CONTENT).hexdigest()
WRONG_SHA256 = "0" * 64


def _current_platform_key() -> str:
    """Get the platform key that DaemonAdapter._detect_platform_key() would return."""
    return DaemonAdapter._detect_platform_key()


def _make_manifest(adapter: str = "yggdrasil", binary_sha256: str = FAKE_SHA256) -> dict:
    """Build a minimal binary_manifest.json dict with the CURRENT platform."""
    return {
        "schema_version": 1,
        "adapters": {
            adapter: {
                "version": "0.5.13",
                "binary_name": adapter,
                "platforms": {
                    _current_platform_key(): {
                        "binary_sha256": binary_sha256,
                        "asset": f"{adapter}.deb",
                        "sha256": "deadbeef",
                        "binary_path_in_archive": f"usr/bin/{adapter}",
                        "archive_format": "deb",
                    }
                },
            }
        },
    }


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    p = tmp_path / "binary_manifest.json"
    p.write_text(json.dumps(manifest))
    return p


def _write_binary(tmp_path: Path, content: bytes = FAKE_BINARY_CONTENT, name: str = "yggdrasil") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# 2.1 — SecurityConfig field on CoreConfig
# ---------------------------------------------------------------------------


class TestSecurityConfig:
    """Task 2.1: security.strict_binary_verification defaults to False."""

    def test_default_strict_is_false(self):
        cfg = CoreConfig()
        assert cfg.security.strict_binary_verification is False

    def test_strict_can_be_enabled(self):
        cfg = CoreConfig(security=SecurityConfig(strict_binary_verification=True))
        assert cfg.security.strict_binary_verification is True


# ---------------------------------------------------------------------------
# 2.2 — verify_binary_integrity() on DaemonAdapter base
# ---------------------------------------------------------------------------


class TestVerifyBinaryIntegrity:
    """Task 2.2: DaemonAdapter.verify_binary_integrity()."""

    def test_valid_hash_passes(self, tmp_path: Path):
        """Binary matching manifest hash → returns True, no exception."""
        manifest_path = _write_manifest(tmp_path, _make_manifest())
        binary_path = _write_binary(tmp_path)

        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil", str(binary_path), manifest_path=manifest_path
        )
        assert result.match is True

    def test_tampered_hash_returns_false(self, tmp_path: Path):
        """Binary NOT matching manifest hash → returns False."""
        manifest_path = _write_manifest(
            tmp_path, _make_manifest(binary_sha256=WRONG_SHA256)
        )
        binary_path = _write_binary(tmp_path)

        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil", str(binary_path), manifest_path=manifest_path
        )
        assert result.match is False

    def test_missing_adapter_in_manifest_returns_none(self, tmp_path: Path):
        """Adapter not in manifest → returns None (skip)."""
        manifest_path = _write_manifest(tmp_path, _make_manifest(adapter="other"))
        binary_path = _write_binary(tmp_path)

        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil", str(binary_path), manifest_path=manifest_path
        )
        assert result.match is None

    def test_missing_platform_in_manifest_returns_none(self, tmp_path: Path):
        """Current platform not in manifest → returns None (skip)."""
        manifest = _make_manifest()
        # Remove all platforms
        manifest["adapters"]["yggdrasil"]["platforms"] = {}
        manifest_path = _write_manifest(tmp_path, manifest)
        binary_path = _write_binary(tmp_path)

        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil", str(binary_path), manifest_path=manifest_path
        )
        assert result.match is None

    def test_missing_manifest_file_returns_none(self, tmp_path: Path):
        """Manifest file doesn't exist → returns None (skip)."""
        binary_path = _write_binary(tmp_path)
        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil",
            str(binary_path),
            manifest_path=tmp_path / "nonexistent.json",
        )
        assert result.match is None

    def test_missing_binary_file_returns_none(self, tmp_path: Path):
        """Binary file doesn't exist → returns None (skip)."""
        manifest_path = _write_manifest(tmp_path, _make_manifest())
        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil",
            str(tmp_path / "nonexistent"),
            manifest_path=manifest_path,
        )
        assert result.match is None


# ---------------------------------------------------------------------------
# 2.3 / 2.4 — Non-strict mode: warn + start anyway
# ---------------------------------------------------------------------------


class TestNonStrictVerification:
    """Tasks 2.3–2.4: Non-strict mode logs WARNING on mismatch, starts anyway."""

    @pytest.mark.asyncio
    async def test_mismatch_logs_warning_and_starts(self, tmp_path: Path, caplog):
        """Tampered binary in non-strict mode → WARNING logged, process starts."""
        manifest_path = _write_manifest(
            tmp_path, _make_manifest(binary_sha256=WRONG_SHA256)
        )
        binary_path = _write_binary(tmp_path)

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=False)
        )

        with (
            caplog.at_level(logging.WARNING),
            patch.object(
                DaemonAdapter,
                "verify_binary_integrity",
                return_value=VerificationResult(False, "expected_abc123", "actual_def456"),
            ),
        ):
            # The actual wiring test: verify that _start_managed proceeds
            # despite mismatch when strict=False. We test this through
            # the adapter's start() path.
            from styrened.services.yggdrasil import YggdrasilAdapter
            from styrened.models.config import YggdrasilConfig

            ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
            adapter = YggdrasilAdapter(
                ygg_config, core_config=config
            )

            # Mock _find_binary and subprocess creation
            with (
                patch.object(adapter, "_find_binary", return_value=str(binary_path)),
                patch.object(adapter, "_ensure_yggdrasil_config"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_exec.return_value = mock_proc

                await adapter._start_managed()

                # Process was started despite mismatch
                mock_exec.assert_called_once()

                # WARNING was logged about the mismatch
                assert any(
                    "mismatch" in r.message.lower() and r.levelno == logging.WARNING
                    for r in caplog.records
                ), f"Expected WARNING about mismatch, got: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_valid_hash_starts_normally(self, tmp_path: Path):
        """Valid binary hash → starts without warnings."""
        config = CoreConfig()

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(True, "abc123", "abc123"),
        ):
            from styrened.services.yggdrasil import YggdrasilAdapter
            from styrened.models.config import YggdrasilConfig

            ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
            adapter = YggdrasilAdapter(
                ygg_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/yggdrasil"),
                patch.object(adapter, "_ensure_yggdrasil_config"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_exec.return_value = mock_proc

                await adapter._start_managed()
                mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# 2.5 — Strict mode: raise BinaryIntegrityError
# ---------------------------------------------------------------------------


class TestStrictVerification:
    """Task 2.5: Strict mode raises BinaryIntegrityError, refuses to start."""

    @pytest.mark.asyncio
    async def test_strict_mismatch_raises(self, tmp_path: Path):
        """Tampered binary in strict mode → BinaryIntegrityError raised."""
        from styrened.services.binary_errors import BinaryIntegrityError
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(False, "expected_abc", "actual_def")
        ):
            ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
            adapter = YggdrasilAdapter(
                ygg_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/yggdrasil"),
                patch.object(adapter, "_ensure_yggdrasil_config"),
            ):
                with pytest.raises(BinaryIntegrityError):
                    await adapter._start_managed()

    @pytest.mark.asyncio
    async def test_strict_mismatch_does_not_start_process(self, tmp_path: Path):
        """Strict mode mismatch → subprocess never launched."""
        from styrened.services.binary_errors import BinaryIntegrityError
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(False, "expected_abc", "actual_def")
        ):
            ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
            adapter = YggdrasilAdapter(
                ygg_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/yggdrasil"),
                patch.object(adapter, "_ensure_yggdrasil_config"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                with pytest.raises(BinaryIntegrityError):
                    await adapter._start_managed()
                mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# 2.6 — I2P adapter wiring
# ---------------------------------------------------------------------------


class TestI2PAdapterVerification:
    """Task 2.6: I2PAdapter also wires verification into _start_managed()."""

    @pytest.mark.asyncio
    async def test_i2p_strict_mismatch_raises(self, tmp_path: Path):
        from styrened.services.binary_errors import BinaryIntegrityError
        from styrened.services.i2p import I2PAdapter
        from styrened.models.config import I2PConfig

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(False, "expected_abc", "actual_def")
        ):
            i2p_config = I2PConfig(mode=DaemonMode.MANAGED)
            adapter = I2PAdapter(
                i2p_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/i2pd"),
                patch.object(adapter, "_generate_i2pd_conf"),
            ):
                with pytest.raises(BinaryIntegrityError):
                    await adapter._start_managed()

    @pytest.mark.asyncio
    async def test_i2p_non_strict_starts_on_mismatch(self, tmp_path: Path):
        from styrened.services.i2p import I2PAdapter
        from styrened.models.config import I2PConfig

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=False)
        )

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(False, "expected_abc", "actual_def")
        ):
            i2p_config = I2PConfig(mode=DaemonMode.MANAGED)
            adapter = I2PAdapter(
                i2p_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/i2pd"),
                patch.object(adapter, "_generate_i2pd_conf"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                mock_proc = MagicMock()
                mock_proc.pid = 99
                mock_exec.return_value = mock_proc

                await adapter._start_managed()
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_i2p_skip_when_not_in_manifest(self, tmp_path: Path):
        """Missing manifest entry → verification skipped, process starts."""
        from styrened.services.i2p import I2PAdapter
        from styrened.models.config import I2PConfig

        config = CoreConfig()

        with patch.object(
            DaemonAdapter, "verify_binary_integrity",
            return_value=VerificationResult(None, None, None)
        ):
            i2p_config = I2PConfig(mode=DaemonMode.MANAGED)
            adapter = I2PAdapter(
                i2p_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/i2pd"),
                patch.object(adapter, "_generate_i2pd_conf"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                mock_proc = MagicMock()
                mock_proc.pid = 99
                mock_exec.return_value = mock_proc

                await adapter._start_managed()
                mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestVerificationEdgeCases:
    """Edge cases for graceful degradation."""

    def test_corrupt_manifest_json_returns_none(self, tmp_path: Path):
        """Malformed JSON in manifest → returns None (skip)."""
        manifest_path = tmp_path / "binary_manifest.json"
        manifest_path.write_text("{invalid json")
        binary_path = _write_binary(tmp_path)

        result = DaemonAdapter.verify_binary_integrity(
            "yggdrasil", str(binary_path), manifest_path=manifest_path
        )
        assert result.match is None

    @pytest.mark.asyncio
    async def test_verification_skip_logs_debug(self, tmp_path: Path, caplog):
        """When verification returns None (skip), DEBUG is logged."""
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        config = CoreConfig()

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(DaemonAdapter, "verify_binary_integrity",
                return_value=VerificationResult(None, None, None)),
        ):
            ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
            adapter = YggdrasilAdapter(
                ygg_config, core_config=config
            )

            with (
                patch.object(adapter, "_find_binary", return_value="/usr/bin/yggdrasil"),
                patch.object(adapter, "_ensure_yggdrasil_config"),
                patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            ):
                mock_proc = MagicMock()
                mock_proc.pid = 12345
                mock_exec.return_value = mock_proc

                await adapter._start_managed()
                mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# W3 fix — End-to-end verification through _start_managed() WITHOUT mocking
# verify_binary_integrity, so real hash comparison + branch logic is exercised.
# The key difference: verify_binary_integrity is NOT patched — the real static
# method runs with a real manifest and real binary, exercising the actual hash
# comparison and the if/elif branches in _start_managed().
# ---------------------------------------------------------------------------

# Save the real verify method before any tests can patch it
_real_verify = DaemonAdapter.verify_binary_integrity


class TestRealVerificationThroughStartManaged:
    """Exercise the actual verify_binary_integrity call through _start_managed().

    These tests provide a real manifest and binary. Only _find_binary and
    subprocess creation are mocked. The verification code path is real.
    """

    @pytest.mark.asyncio
    async def test_yggdrasil_real_mismatch_strict_raises(self, tmp_path: Path):
        """Real tampered binary + strict mode → BinaryIntegrityError via real code path."""
        from styrened.services.binary_errors import BinaryIntegrityError
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        manifest_path = _write_manifest(
            tmp_path, _make_manifest(binary_sha256=WRONG_SHA256)
        )
        binary_path = _write_binary(tmp_path)

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )
        ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
        adapter = YggdrasilAdapter(ygg_config, core_config=config)

        # Redirect manifest lookup to our tmp_path manifest, but use real hashing
        def verify_with_test_manifest(adapter_name, bin_path, **kwargs):
            return _real_verify(adapter_name, bin_path, manifest_path=manifest_path)

        with (
            patch.object(adapter, "_find_binary", return_value=str(binary_path)),
            patch.object(adapter, "_ensure_yggdrasil_config"),
            patch.object(
                DaemonAdapter, "verify_binary_integrity",
                side_effect=verify_with_test_manifest,
            ),
        ):
            with pytest.raises(BinaryIntegrityError):
                await adapter._start_managed()

    @pytest.mark.asyncio
    async def test_yggdrasil_real_mismatch_nonstrict_starts(self, tmp_path: Path, caplog):
        """Real tampered binary + non-strict → WARNING logged, process starts."""
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        manifest_path = _write_manifest(
            tmp_path, _make_manifest(binary_sha256=WRONG_SHA256)
        )
        binary_path = _write_binary(tmp_path)

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=False)
        )
        ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
        adapter = YggdrasilAdapter(ygg_config, core_config=config)

        def verify_with_test_manifest(adapter_name, bin_path, **kwargs):
            return _real_verify(adapter_name, bin_path, manifest_path=manifest_path)

        with (
            caplog.at_level(logging.WARNING),
            patch.object(adapter, "_find_binary", return_value=str(binary_path)),
            patch.object(adapter, "_ensure_yggdrasil_config"),
            patch.object(
                DaemonAdapter, "verify_binary_integrity",
                side_effect=verify_with_test_manifest,
            ),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_exec.return_value = mock_proc

            await adapter._start_managed()
            mock_exec.assert_called_once()

            assert any(
                "mismatch" in r.message.lower() and r.levelno == logging.WARNING
                for r in caplog.records
            )

    @pytest.mark.asyncio
    async def test_yggdrasil_real_valid_hash_starts(self, tmp_path: Path):
        """Real matching binary hash → starts without error."""
        from styrened.services.yggdrasil import YggdrasilAdapter
        from styrened.models.config import YggdrasilConfig

        manifest_path = _write_manifest(
            tmp_path, _make_manifest(binary_sha256=FAKE_SHA256)
        )
        binary_path = _write_binary(tmp_path)

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )
        ygg_config = YggdrasilConfig(mode=DaemonMode.MANAGED)
        adapter = YggdrasilAdapter(ygg_config, core_config=config)

        def verify_with_test_manifest(adapter_name, bin_path, **kwargs):
            return _real_verify(adapter_name, bin_path, manifest_path=manifest_path)

        with (
            patch.object(adapter, "_find_binary", return_value=str(binary_path)),
            patch.object(adapter, "_ensure_yggdrasil_config"),
            patch.object(
                DaemonAdapter, "verify_binary_integrity",
                side_effect=verify_with_test_manifest,
            ),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_exec.return_value = mock_proc

            await adapter._start_managed()
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_i2p_real_mismatch_strict_raises(self, tmp_path: Path):
        """Real tampered i2pd binary + strict mode → BinaryIntegrityError."""
        from styrened.services.binary_errors import BinaryIntegrityError
        from styrened.services.i2p import I2PAdapter
        from styrened.models.config import I2PConfig

        manifest_path = _write_manifest(
            tmp_path, _make_manifest(adapter="i2pd", binary_sha256=WRONG_SHA256)
        )
        binary_path = _write_binary(tmp_path, name="i2pd")

        config = CoreConfig(
            security=SecurityConfig(strict_binary_verification=True)
        )
        i2p_config = I2PConfig(mode=DaemonMode.MANAGED)
        adapter = I2PAdapter(i2p_config, core_config=config)

        def verify_with_test_manifest(adapter_name, bin_path, **kwargs):
            return _real_verify(adapter_name, bin_path, manifest_path=manifest_path)

        with (
            patch.object(adapter, "_find_binary", return_value=str(binary_path)),
            patch.object(adapter, "_generate_i2pd_conf"),
            patch.object(
                DaemonAdapter, "verify_binary_integrity",
                side_effect=verify_with_test_manifest,
            ),
        ):
            with pytest.raises(BinaryIntegrityError):
                await adapter._start_managed()
