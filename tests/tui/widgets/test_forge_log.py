"""Tests for ForgeLog widget."""

from styrened.tui.forge.models import MediaEvent, StageKey
from styrened.tui.widgets.forge_log import ForgeLog


def test_forge_log_instantiation():
    """ForgeLog can be instantiated."""
    widget = ForgeLog()
    assert widget is not None
    assert not widget.is_complete
    assert not widget.is_error


def test_forge_log_initial_state():
    """ForgeLog starts with clean state."""
    widget = ForgeLog()
    assert widget._current_stage is None
    assert len(widget._completed_stages) == 0
    assert len(widget._log_lines) == 0


def test_forge_log_stage_event_updates_current_stage():
    """Stage events update the current stage tracker."""
    widget = ForgeLog()

    event = MediaEvent(kind="stage", message="Checking deps", stage=StageKey.DEPS)
    widget.handle_event(event)

    assert widget._current_stage == StageKey.DEPS


def test_forge_log_stage_progression_completes_previous():
    """Moving to a new stage marks the previous as completed."""
    widget = ForgeLog()

    widget.handle_event(MediaEvent(kind="stage", message="Deps", stage=StageKey.DEPS))
    assert widget._current_stage == StageKey.DEPS
    assert StageKey.DEPS not in widget._completed_stages

    widget.handle_event(MediaEvent(kind="stage", message="Download", stage=StageKey.DOWNLOAD))
    assert widget._current_stage == StageKey.DOWNLOAD
    assert StageKey.DEPS in widget._completed_stages


def test_forge_log_log_event_accumulates():
    """Log events append to the log lines list."""
    widget = ForgeLog()

    widget.handle_event(MediaEvent(kind="log", message="Line 1"))
    widget.handle_event(MediaEvent(kind="log", message="Line 2"))
    widget.handle_event(MediaEvent(kind="log", message="Line 3"))

    assert len(widget._log_lines) == 3
    assert widget._log_lines[0] == "Line 1"
    assert widget._log_lines[2] == "Line 3"


def test_forge_log_error_event_sets_error_state():
    """Error events set the is_error flag."""
    widget = ForgeLog()

    assert not widget.is_error
    widget.handle_event(MediaEvent(kind="error", message="Missing dependency"))
    assert widget.is_error


def test_forge_log_error_event_adds_to_log():
    """Error events are added to the log lines."""
    widget = ForgeLog()

    widget.handle_event(MediaEvent(kind="error", message="Something broke"))
    assert len(widget._log_lines) == 1
    assert "Something broke" in widget._log_lines[0]


def test_forge_log_complete_event_sets_complete_state():
    """Complete events set the is_complete flag."""
    widget = ForgeLog()

    assert not widget.is_complete
    widget.handle_event(MediaEvent(kind="complete", message="Done"))
    assert widget.is_complete


def test_forge_log_complete_completes_final_stage():
    """Complete event marks the current stage as completed."""
    widget = ForgeLog()

    widget.handle_event(MediaEvent(kind="stage", message="Finish", stage=StageKey.FINISH))
    assert widget._current_stage == StageKey.FINISH

    widget.handle_event(MediaEvent(kind="complete", message="Done"))
    assert StageKey.FINISH in widget._completed_stages
    assert widget._current_stage is None


def test_forge_log_set_hostname():
    """set_hostname stores the hostname for mesh watch."""
    widget = ForgeLog()
    widget.set_hostname("rpi4-01")
    assert widget._hostname == "rpi4-01"


def test_forge_log_reset_clears_state():
    """reset() returns the widget to initial state."""
    widget = ForgeLog()

    # Populate some state
    widget.handle_event(MediaEvent(kind="stage", message="Deps", stage=StageKey.DEPS))
    widget.handle_event(MediaEvent(kind="log", message="Test log"))
    widget.handle_event(MediaEvent(kind="stage", message="Download", stage=StageKey.DOWNLOAD))
    widget.set_hostname("test-host")

    # Reset
    widget.reset()

    assert widget._current_stage is None
    assert len(widget._completed_stages) == 0
    assert len(widget._log_lines) == 0
    assert not widget.is_complete
    assert not widget.is_error


def test_forge_log_full_pipeline_simulation():
    """Simulate a complete forge pipeline event sequence."""
    widget = ForgeLog()

    # Stage progression
    stages = [
        (StageKey.DEPS, "Checking dependencies"),
        (StageKey.DOWNLOAD, "Downloading image"),
        (StageKey.EXTRACT, "Extracting"),
        (StageKey.PARTITION, "Partitioning"),
        (StageKey.COPY, "Copying files"),
        (StageKey.STYRENE_FILES, "Adding automation"),
        (StageKey.FINISH, "Finalizing"),
    ]

    for stage_key, msg in stages:
        widget.handle_event(MediaEvent(kind="stage", message=msg, stage=stage_key))
        widget.handle_event(MediaEvent(kind="log", message=f"  {msg} detail"))

    widget.handle_event(MediaEvent(kind="complete", message="Media creation complete"))

    # All stages completed
    assert widget.is_complete
    assert not widget.is_error
    assert len(widget._completed_stages) == 7
    # 7 stage messages + 7 log messages + 1 complete message = 15
    assert len(widget._log_lines) == 15
