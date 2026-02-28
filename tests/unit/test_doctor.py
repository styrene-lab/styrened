"""Tests for the doctor diagnostic service.

Tests each check function with mocked dependencies, report properties,
and the setup wizard flow.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.services.doctor import (
    CheckCategory,
    DoctorReport,
    Finding,
    Severity,
    apply_fixes,
    check_config,
    check_daemon,
    check_identity,
    check_paths,
    check_reticulum,
    check_version,
    run_doctor,
)

# -----------------------------------------------------------------------------
# Finding and DoctorReport model tests
# -----------------------------------------------------------------------------


class TestFinding:
    """Test Finding dataclass."""

    def test_finding_creation(self):
        """Finding should store category, severity, message, and optional fix_hint."""
        f = Finding(
            category=CheckCategory.VERSION,
            severity=Severity.OK,
            message="test message",
        )
        assert f.category == CheckCategory.VERSION
        assert f.severity == Severity.OK
        assert f.message == "test message"
        assert f.fix_hint is None

    def test_finding_with_fix_hint(self):
        """Finding should store fix_hint when provided."""
        f = Finding(
            category=CheckCategory.IDENTITY,
            severity=Severity.ERROR,
            message="missing",
            fix_hint="run setup",
        )
        assert f.fix_hint == "run setup"

    def test_finding_is_frozen(self):
        """Finding should be immutable (frozen dataclass)."""
        f = Finding(
            category=CheckCategory.VERSION,
            severity=Severity.OK,
            message="test",
        )
        with pytest.raises(AttributeError):
            f.message = "changed"


class TestDoctorReport:
    """Test DoctorReport dataclass."""

    def test_empty_report_no_errors(self):
        """Empty report should have no errors or warnings."""
        report = DoctorReport()
        assert not report.has_errors
        assert not report.has_warnings
        assert report.exit_code == 0

    def test_report_with_error(self):
        """Report with an ERROR finding should have exit_code 2."""
        report = DoctorReport(
            findings=[
                Finding(CheckCategory.VERSION, Severity.ERROR, "bad"),
            ]
        )
        assert report.has_errors
        assert report.exit_code == 2

    def test_report_with_warning_only(self):
        """Report with only WARN findings should have exit_code 1."""
        report = DoctorReport(
            findings=[
                Finding(CheckCategory.VERSION, Severity.OK, "ok"),
                Finding(CheckCategory.CONFIG, Severity.WARN, "hmm"),
            ]
        )
        assert not report.has_errors
        assert report.has_warnings
        assert report.exit_code == 1

    def test_report_to_dict(self):
        """to_dict should serialize all fields."""
        report = DoctorReport(
            findings=[
                Finding(CheckCategory.VERSION, Severity.OK, "good"),
            ],
            version_info={"installed": "1.0.0"},
            identity_info={"identity_hash": "abc123"},
            checked_at="2026-02-23T00:00:00+00:00",
        )
        d = report.to_dict()
        assert len(d["findings"]) == 1
        assert d["findings"][0]["category"] == "version"
        assert d["findings"][0]["severity"] == "OK"
        assert d["version_info"]["installed"] == "1.0.0"
        assert d["has_errors"] is False
        assert d["exit_code"] == 0


# -----------------------------------------------------------------------------
# check_version tests
# -----------------------------------------------------------------------------


class TestCheckVersion:
    """Test version check function."""

    @patch("styrened.services.doctor.__version__", "0.10.4")
    def test_offline_returns_installed_version(self):
        """Offline mode should return only the installed version."""
        findings = check_version(offline=True)
        assert len(findings) == 1
        assert findings[0].severity == Severity.OK
        assert "0.10.4" in findings[0].message

    @patch("urllib.request.urlopen")
    @patch("styrened.services.doctor.__version__", "0.10.4")
    def test_up_to_date(self, mock_urlopen):
        """Should report up to date when installed == latest."""
        import json

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(
            {"info": {"version": "0.10.4"}}
        ).encode()
        mock_urlopen.return_value = mock_resp

        findings = check_version(offline=False)
        assert len(findings) == 2
        assert findings[1].severity == Severity.OK
        assert "Up to date" in findings[1].message

    @patch("urllib.request.urlopen")
    @patch("styrened.services.doctor.__version__", "0.10.4")
    def test_newer_available(self, mock_urlopen):
        """Should warn when a newer version is available on PyPI."""
        import json

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(
            {"info": {"version": "0.11.0"}}
        ).encode()
        mock_urlopen.return_value = mock_resp

        findings = check_version(offline=False)
        assert len(findings) == 2
        assert findings[1].severity == Severity.WARN
        assert "0.11.0" in findings[1].message

    @patch("urllib.request.urlopen", side_effect=Exception("network error"))
    @patch("styrened.services.doctor.__version__", "0.10.4")
    def test_network_error_graceful(self, mock_urlopen):
        """Should gracefully handle network errors."""
        findings = check_version(offline=False)
        assert len(findings) == 2
        assert findings[1].severity == Severity.WARN
        assert "Could not check" in findings[1].message


# -----------------------------------------------------------------------------
# check_identity tests
# -----------------------------------------------------------------------------


class TestCheckIdentity:
    """Test identity check function."""

    @patch("styrened.services.doctor.get_identity_sharing_status", return_value={})
    @patch("styrened.services.doctor.detect_existing_lxmf_identity", return_value=None)
    @patch("styrened.services.doctor._resolve_identity_path")
    @patch("styrened.services.doctor.get_operator_identity")
    def test_identity_exists(self, mock_get_id, mock_resolve, mock_detect, mock_sharing):
        """Should report OK when identity exists."""
        mock_get_id.return_value = "a1b2c3d4e5f6a7b8" * 2
        mock_path = MagicMock(spec=Path)
        mock_resolve.return_value = mock_path

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_mode=0o600)
            findings = check_identity()

        ok_findings = [f for f in findings if f.severity == Severity.OK]
        assert len(ok_findings) >= 1
        assert "a1b2c3d4e5f6a7b8" in ok_findings[0].message

    @patch("styrened.services.doctor.get_identity_sharing_status", return_value={})
    @patch("styrened.services.doctor.detect_existing_lxmf_identity", return_value=None)
    @patch("styrened.services.doctor._resolve_identity_path", return_value=None)
    @patch("styrened.services.doctor.get_operator_identity", return_value=None)
    def test_no_identity(self, mock_get_id, mock_resolve, mock_detect, mock_sharing):
        """Should report ERROR when no identity exists."""
        findings = check_identity()
        error_findings = [f for f in findings if f.severity == Severity.ERROR]
        assert len(error_findings) == 1
        assert "No operator identity" in error_findings[0].message

    @patch("styrened.services.doctor.get_identity_sharing_status", return_value={})
    @patch("styrened.services.doctor.detect_existing_lxmf_identity")
    @patch("styrened.services.doctor._resolve_identity_path", return_value=None)
    @patch("styrened.services.doctor.get_operator_identity", return_value=None)
    def test_existing_lxmf_identity_detected(self, mock_get_id, mock_resolve, mock_detect, mock_sharing):
        """Should note when an adoptable LXMF identity is found."""
        mock_detect.return_value = ("NomadNet", Path("/home/user/.nomadnetwork/storage/identity"))
        findings = check_identity()
        found = [f for f in findings if "NomadNet" in f.message]
        assert len(found) == 1

    @patch("styrened.services.doctor.get_identity_sharing_status", return_value={})
    @patch("styrened.services.doctor.detect_existing_lxmf_identity", return_value=None)
    @patch("styrened.services.doctor._resolve_identity_path")
    @patch("styrened.services.doctor.get_operator_identity")
    def test_world_readable_identity_warns(self, mock_get_id, mock_resolve, mock_detect, mock_sharing):
        """Should warn if identity file is world-readable."""
        mock_get_id.return_value = "abcdef1234567890" * 2
        mock_path = MagicMock(spec=Path)
        mock_resolve.return_value = mock_path

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_mode=0o644)
            findings = check_identity()

        warn_findings = [f for f in findings if f.severity == Severity.WARN]
        assert any("world-readable" in f.message for f in warn_findings)


# -----------------------------------------------------------------------------
# check_config tests
# -----------------------------------------------------------------------------


class TestCheckConfig:
    """Test config check function."""

    @patch("styrened.services.doctor.load_core_config")
    @patch("styrened.services.doctor.paths")
    def test_config_exists_and_valid(self, mock_paths, mock_load):
        """Should report OK when config loads successfully."""
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = True
        mock_paths.config_file.return_value = mock_config_path

        mock_config = MagicMock()
        mock_config.identity.display_name = "my-node"
        mock_load.return_value = mock_config

        findings = check_config()
        ok_findings = [f for f in findings if f.severity == Severity.OK]
        assert len(ok_findings) >= 1

    @patch("styrened.services.doctor.paths")
    def test_config_missing(self, mock_paths):
        """Should warn when config file is missing."""
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = False
        mock_paths.config_file.return_value = mock_config_path

        findings = check_config()
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARN
        assert "not found" in findings[0].message

    @patch("styrened.services.doctor.load_core_config")
    @patch("styrened.services.doctor.paths")
    def test_config_parse_error(self, mock_paths, mock_load):
        """Should report ERROR when config fails to parse."""
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = True
        mock_paths.config_file.return_value = mock_config_path
        mock_load.side_effect = Exception("invalid yaml")

        findings = check_config()
        error_findings = [f for f in findings if f.severity == Severity.ERROR]
        assert len(error_findings) == 1
        assert "parse error" in error_findings[0].message.lower()

    @patch("styrened.services.doctor.load_core_config")
    @patch("styrened.services.doctor.paths")
    def test_default_display_name_warns(self, mock_paths, mock_load):
        """Should warn when display_name is still the default."""
        mock_config_path = MagicMock()
        mock_config_path.exists.return_value = True
        mock_paths.config_file.return_value = mock_config_path

        mock_config = MagicMock()
        mock_config.identity.display_name = "Anonymous Styrene"
        mock_load.return_value = mock_config

        findings = check_config()
        warn_findings = [f for f in findings if f.severity == Severity.WARN]
        assert any("not customized" in f.message for f in warn_findings)


# -----------------------------------------------------------------------------
# check_reticulum tests
# -----------------------------------------------------------------------------


class TestCheckReticulum:
    """Test Reticulum check function."""

    @patch("styrened.services.doctor.get_reticulum_config_state")
    @patch("styrened.services.doctor.is_reticulum_configured", return_value=True)
    @patch("styrened.services.doctor.find_reticulum_config")
    def test_reticulum_configured(self, mock_find, mock_is_conf, mock_state):
        """Should report OK when Reticulum is properly configured."""
        mock_find.return_value = Path("/home/user/.reticulum")
        mock_state_obj = MagicMock()
        mock_state_obj.interface_count = 2
        mock_state.return_value = mock_state_obj

        findings = check_reticulum()
        ok_findings = [f for f in findings if f.severity == Severity.OK]
        assert len(ok_findings) >= 2
        assert any("2 interface" in f.message for f in ok_findings)

    @patch("styrened.services.doctor.find_reticulum_config", return_value=None)
    def test_no_reticulum_config(self, mock_find):
        """Should warn when no Reticulum config directory found."""
        findings = check_reticulum()
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARN
        assert "No Reticulum config" in findings[0].message


# -----------------------------------------------------------------------------
# check_daemon tests
# -----------------------------------------------------------------------------


class TestCheckDaemon:
    """Test daemon check function."""

    @pytest.mark.asyncio
    @patch("styrened.services.doctor.paths")
    async def test_no_socket(self, mock_paths):
        """Should warn when control socket doesn't exist."""
        mock_socket = MagicMock()
        mock_socket.exists.return_value = False
        mock_paths.control_socket.return_value = mock_socket

        findings = await check_daemon()
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARN
        assert "not running" in findings[0].message.lower()

    @pytest.mark.asyncio
    @patch("styrened.ipc.get_daemon_client")
    @patch("styrened.services.doctor.paths")
    async def test_daemon_responsive(self, mock_paths, mock_get_client):
        """Should report OK when daemon responds to ping."""
        mock_socket = MagicMock()
        mock_socket.exists.return_value = True
        mock_paths.control_socket.return_value = mock_socket

        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        mock_get_client.return_value = mock_client

        findings = await check_daemon()
        ok_findings = [f for f in findings if f.severity == Severity.OK]
        assert len(ok_findings) == 1
        assert "responsive" in ok_findings[0].message.lower()


# -----------------------------------------------------------------------------
# check_paths tests
# -----------------------------------------------------------------------------


class TestCheckPaths:
    """Test paths check function."""

    @patch("styrened.services.doctor.paths")
    def test_all_dirs_exist_writable(self, mock_paths):
        """Should report OK when all directories exist and are writable."""
        for attr in ("config_dir", "data_dir", "state_dir", "runtime_dir"):
            mock_dir = MagicMock(spec=Path)
            mock_dir.exists.return_value = True
            getattr(mock_paths, attr).return_value = mock_dir

        with patch("os.access", return_value=True):
            findings = check_paths()

        assert all(f.severity == Severity.OK for f in findings)
        assert len(findings) == 4

    @patch("styrened.services.doctor.paths")
    def test_missing_dir(self, mock_paths):
        """Should warn when a directory is missing."""
        for attr in ("config_dir", "data_dir", "state_dir", "runtime_dir"):
            mock_dir = MagicMock(spec=Path)
            mock_dir.exists.return_value = False
            getattr(mock_paths, attr).return_value = mock_dir

        findings = check_paths()
        assert all(f.severity == Severity.WARN for f in findings)
        assert all("missing" in f.message.lower() for f in findings)

    @patch("styrened.services.doctor.paths")
    def test_not_writable_dir(self, mock_paths):
        """Should report ERROR when a directory is not writable."""
        for attr in ("config_dir", "data_dir", "state_dir", "runtime_dir"):
            mock_dir = MagicMock(spec=Path)
            mock_dir.exists.return_value = True
            getattr(mock_paths, attr).return_value = mock_dir

        with patch("os.access", return_value=False):
            findings = check_paths()

        assert all(f.severity == Severity.ERROR for f in findings)
        assert all("not writable" in f.message.lower() for f in findings)


# -----------------------------------------------------------------------------
# run_doctor tests
# -----------------------------------------------------------------------------


class TestRunDoctor:
    """Test the run_doctor orchestrator."""

    @pytest.mark.asyncio
    @patch("styrened.services.doctor.check_daemon")
    @patch("styrened.services.doctor.check_paths")
    @patch("styrened.services.doctor.check_reticulum")
    @patch("styrened.services.doctor.check_config")
    @patch("styrened.services.doctor.check_identity")
    @patch("styrened.services.doctor.check_version")
    @patch("styrened.services.doctor._resolve_identity_path", return_value=None)
    @patch("styrened.services.doctor.get_operator_identity", return_value=None)
    async def test_run_doctor_aggregates_findings(
        self,
        mock_get_id,
        mock_resolve,
        mock_version,
        mock_identity,
        mock_config,
        mock_retic,
        mock_paths_check,
        mock_daemon,
    ):
        """run_doctor should aggregate findings from all check functions."""
        mock_version.return_value = [
            Finding(CheckCategory.VERSION, Severity.OK, "v ok")
        ]
        mock_identity.return_value = [
            Finding(CheckCategory.IDENTITY, Severity.ERROR, "no id")
        ]
        mock_config.return_value = [
            Finding(CheckCategory.CONFIG, Severity.OK, "config ok")
        ]
        mock_retic.return_value = [
            Finding(CheckCategory.RETICULUM, Severity.OK, "rns ok")
        ]
        mock_paths_check.return_value = [
            Finding(CheckCategory.PATHS, Severity.OK, "paths ok")
        ]

        # check_daemon is async
        async def mock_check_daemon():
            return [Finding(CheckCategory.DAEMON, Severity.WARN, "no daemon")]

        mock_daemon.side_effect = mock_check_daemon

        report = await run_doctor(offline=True)

        assert len(report.findings) == 6
        assert report.has_errors  # from identity check
        assert report.has_warnings  # from daemon check
        assert report.exit_code == 2
        assert report.checked_at != ""


# -----------------------------------------------------------------------------
# apply_fixes tests
# -----------------------------------------------------------------------------


class TestApplyFixes:
    """Test the apply_fixes function."""

    @patch("styrened.services.doctor.paths")
    def test_fix_missing_directories(self, mock_paths):
        """Should create missing directories."""
        mock_paths.ensure_directories = MagicMock()

        report = DoctorReport(
            findings=[
                Finding(
                    CheckCategory.PATHS,
                    Severity.WARN,
                    "Cache directory missing: /tmp/cache",
                    fix_hint="mkdir -p /tmp/cache",
                ),
            ]
        )

        fixed = apply_fixes(report)
        assert len(fixed) == 1
        assert fixed[0].severity == Severity.OK
        mock_paths.ensure_directories.assert_called_once()

    def test_no_fixes_needed(self):
        """Should return empty list when no fixes are needed."""
        report = DoctorReport(
            findings=[
                Finding(CheckCategory.VERSION, Severity.OK, "all good"),
            ]
        )

        fixed = apply_fixes(report)
        assert len(fixed) == 0
