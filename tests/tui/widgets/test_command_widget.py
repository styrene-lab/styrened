"""Tests for CommandWidget and ExecResult model."""

from styrened.tui.models.rpc import ExecResult


def test_exec_result_success_property():
    """ExecResult.success property returns True for exit code 0."""
    result = ExecResult(exit_code=0, stdout="ok", stderr="")
    assert result.success is True
    assert result.success is not False


def test_exec_result_failed_property():
    """ExecResult.success returns False for non-zero exit code (failed)."""
    result = ExecResult(exit_code=1, stdout="", stderr="error")
    assert result.success is False


def test_exec_result_has_output():
    """ExecResult has stdout or stderr content."""
    result1 = ExecResult(exit_code=0, stdout="output", stderr="")
    assert bool(result1.stdout or result1.stderr) is True

    result2 = ExecResult(exit_code=0, stdout="", stderr="error")
    assert bool(result2.stdout or result2.stderr) is True

    result3 = ExecResult(exit_code=0, stdout="", stderr="")
    assert bool(result3.stdout or result3.stderr) is False


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
    assert not result.success
    assert bool(result.stdout or result.stderr)  # stderr counts as output
