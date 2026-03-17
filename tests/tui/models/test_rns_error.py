"""Tests for RNS error state model."""
from __future__ import annotations

from styrened.models.rns_error import (
    RNS_ERROR_INFO,
    RNSErrorCategory,
    RNSErrorState,
)


class TestRNSErrorCategory:
    """Tests for RNSErrorCategory enum."""

    def test_all_categories_have_info(self) -> None:
        """Verify every category has user-facing info defined."""
        for category in RNSErrorCategory:
            assert category in RNS_ERROR_INFO, f"Missing info for {category}"
            info = RNS_ERROR_INFO[category]
            assert "title" in info
            assert "description" in info
            assert "recovery" in info

    def test_none_category_is_not_error(self) -> None:
        """Verify NONE category represents healthy state."""
        state = RNSErrorState(category=RNSErrorCategory.NONE)
        assert not state.is_error

    def test_all_other_categories_are_errors(self) -> None:
        """Verify all categories except NONE are errors."""
        for category in RNSErrorCategory:
            if category != RNSErrorCategory.NONE:
                state = RNSErrorState(category=category)
                assert state.is_error, f"{category} should be an error"


class TestRNSErrorState:
    """Tests for RNSErrorState dataclass."""

    def test_none_factory(self) -> None:
        """Verify none() factory creates healthy state."""
        state = RNSErrorState.none()
        assert state.category == RNSErrorCategory.NONE
        assert not state.is_error
        assert state.title == "Online"

    def test_state_exposes_info_properties(self) -> None:
        """Verify state exposes title, description, recovery."""
        state = RNSErrorState(category=RNSErrorCategory.IDENTITY_CORRUPT)
        assert state.title == "Identity Corrupt"
        assert "invalid" in state.description.lower()
        assert "identity" in state.recovery

    def test_state_stores_exception_details(self) -> None:
        """Verify state stores exception type and message."""
        state = RNSErrorState(
            category=RNSErrorCategory.UNKNOWN,
            exception_type="ValueError",
            message="Something went wrong",
        )
        assert state.exception_type == "ValueError"
        assert state.message == "Something went wrong"


class TestRNSErrorStateFromException:
    """Tests for exception categorization."""

    def test_ed25519_error_categorized_as_identity_corrupt(self) -> None:
        """Verify Ed25519 key errors are categorized correctly."""
        exc = ValueError("An Ed25519 private key is 32 bytes long")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.IDENTITY_CORRUPT
        assert state.exception_type == "ValueError"

    def test_private_key_error_categorized_as_identity_corrupt(self) -> None:
        """Verify private key errors are categorized correctly."""
        exc = Exception("Error loading identity: Invalid private key format")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.IDENTITY_CORRUPT

    def test_permission_error_on_styrene_categorized_as_identity_permission(self) -> None:
        """Verify permission errors on .styrene are categorized correctly."""
        exc = PermissionError("Permission denied: ~/.styrene/operator.key")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.IDENTITY_PERMISSION

    def test_permission_error_on_reticulum_categorized_as_config_permission(self) -> None:
        """Verify permission errors on .reticulum are categorized correctly."""
        exc = PermissionError("Permission denied: ~/.reticulum/config")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.CONFIG_PERMISSION

    def test_general_permission_error_categorized_as_config_permission(self) -> None:
        """Verify general permission errors default to config permission."""
        exc = PermissionError("Cannot read file")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.CONFIG_PERMISSION

    def test_config_parse_error_categorized_correctly(self) -> None:
        """Verify config parsing errors are categorized correctly."""
        exc = Exception("Config parse error: invalid syntax at line 5")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.CONFIG_PARSE_ERROR

    def test_address_in_use_categorized_as_port_conflict(self) -> None:
        """Verify address binding errors are categorized correctly."""
        exc = OSError("Address already in use")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.PORT_CONFLICT

    def test_bind_error_categorized_as_port_conflict(self) -> None:
        """Verify bind errors are categorized correctly."""
        exc = Exception("Cannot bind to port 4242")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.PORT_CONFLICT

    def test_interface_error_categorized_correctly(self) -> None:
        """Verify interface errors are categorized correctly."""
        exc = Exception("TCPClientInterface failed to start")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.INTERFACE_FAILURE

    def test_file_not_found_for_reticulum_categorized_as_not_configured(self) -> None:
        """Verify missing config errors are categorized correctly."""
        exc = FileNotFoundError("~/.reticulum/config not found")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.NOT_CONFIGURED

    def test_unknown_error_categorized_as_unknown(self) -> None:
        """Verify unrecognized errors fall through to unknown."""
        exc = RuntimeError("Something completely unexpected")
        state = RNSErrorState.from_exception(exc)
        assert state.category == RNSErrorCategory.UNKNOWN
        assert state.exception_type == "RuntimeError"
        assert "unexpected" in state.message


class TestRNSErrorRecoveryGuidance:
    """Tests for recovery guidance content."""

    def test_identity_corrupt_recovery_mentions_delete(self) -> None:
        """Verify identity corrupt recovery tells user to delete key."""
        state = RNSErrorState(category=RNSErrorCategory.IDENTITY_CORRUPT)
        assert "Delete" in state.recovery or "delete" in state.recovery.lower()
        assert "identity" in state.recovery

    def test_not_configured_recovery_mentions_wizard(self) -> None:
        """Verify not configured recovery mentions setup wizard."""
        state = RNSErrorState(category=RNSErrorCategory.NOT_CONFIGURED)
        assert "wizard" in state.recovery.lower() or "setup" in state.recovery.lower()

    def test_config_parse_error_recovery_mentions_check_or_delete(self) -> None:
        """Verify config parse error recovery gives actionable advice."""
        state = RNSErrorState(category=RNSErrorCategory.CONFIG_PARSE_ERROR)
        recovery_lower = state.recovery.lower()
        assert "check" in recovery_lower or "delete" in recovery_lower

    def test_unknown_error_recovery_mentions_logs(self) -> None:
        """Verify unknown error recovery points to logs."""
        state = RNSErrorState(category=RNSErrorCategory.UNKNOWN)
        assert "log" in state.recovery.lower()
