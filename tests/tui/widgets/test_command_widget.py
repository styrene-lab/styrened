"""Tests for CommandWidget and ExecResult model."""

from styrened.tui.models.rpc import ExecResult


def test_exec_result_success_property():
    """ExecResult.success property returns True for exit code 0."""
    result = ExecResult(exit_code=0, stdout="ok", stderr="")
    assert result.success is True
    assert result.failed is False


def test_exec_result_failed_property():
    """ExecResult.failed property returns True for non-zero exit code."""
    result = ExecResult(exit_code=1, stdout="", stderr="error")
    assert result.failed is True
    assert result.success is False


def test_exec_result_has_output():
    """ExecResult.has_output returns True if stdout or stderr present."""
    result1 = ExecResult(exit_code=0, stdout="output", stderr="")
    assert result1.has_output is True

    result2 = ExecResult(exit_code=0, stdout="", stderr="error")
    assert result2.has_output is True

    result3 = ExecResult(exit_code=0, stdout="", stderr="")
    assert result3.has_output is False


def test_exec_result_properties():
    """ExecResult properties work correctly."""
    result = ExecResult(
        exit_code=127,
        stdout="",
        stderr="command not found",
    )

    assert result.exit_code == 127
    assert result.stdout == ""
    assert result.stderr == "command not found"
    assert result.failed
    assert not result.success
    assert result.has_output  # stderr counts as output
