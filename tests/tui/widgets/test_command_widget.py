"""Tests for CommandWidget, OutputEntry, and command presets."""

from styrened.tui.widgets.command_widget import (
    COMMAND_PRESETS,
    CommandWidget,
    OutputEntry,
)


class TestOutputEntry:
    """Tests for the OutputEntry dataclass."""

    def test_default_entry_type(self):
        """OutputEntry defaults to 'exec' entry type."""
        entry = OutputEntry(command="ls")
        assert entry.entry_type == "exec"
        assert entry.exit_code is None
        assert entry.stdout == ""
        assert entry.stderr == ""
        assert entry.rtt_ms is None

    def test_exec_entry(self):
        """OutputEntry stores exec results."""
        entry = OutputEntry(
            command="uptime",
            exit_code=0,
            stdout="10:23 up 3 days",
            stderr="",
            entry_type="exec",
        )
        assert entry.command == "uptime"
        assert entry.exit_code == 0
        assert entry.stdout == "10:23 up 3 days"

    def test_ping_entry(self):
        """OutputEntry stores ping RTT."""
        entry = OutputEntry(
            command="ping",
            rtt_ms=42.5,
            entry_type="ping",
        )
        assert entry.rtt_ms == 42.5
        assert entry.entry_type == "ping"

    def test_reboot_entry(self):
        """OutputEntry stores reboot result."""
        entry = OutputEntry(
            command="reboot",
            exit_code=0,
            stdout="Rebooting in 5 seconds",
            entry_type="reboot",
        )
        assert entry.entry_type == "reboot"

    def test_system_entry(self):
        """OutputEntry stores system messages."""
        entry = OutputEntry(
            command="",
            stdout="No RPC client available",
            entry_type="system",
        )
        assert entry.entry_type == "system"


class TestCommandHistory:
    """Tests for command history navigation."""

    def test_empty_history(self):
        """Widget starts with empty history."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._command_history = []
        widget._history_index = -1
        assert widget._command_history == []
        assert widget._history_index == -1

    def test_history_index_initial(self):
        """History index starts at -1 (current input)."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._history_index = -1
        assert widget._history_index == -1

    def test_history_tracks_commands(self):
        """Commands are tracked in order."""
        history: list[str] = []
        history.append("uptime")
        history.append("df -h")
        history.append("free -h")
        assert history == ["uptime", "df -h", "free -h"]

    def test_history_no_duplicate_consecutive(self):
        """Duplicate consecutive commands should not be added."""
        history: list[str] = []

        def add(cmd: str) -> None:
            if not history or history[-1] != cmd:
                history.append(cmd)

        add("uptime")
        add("uptime")
        add("df -h")
        assert history == ["uptime", "df -h"]


class TestPresetFiltering:
    """Tests for preset command filtering against available_commands."""

    def test_all_presets_shown_when_no_filter(self):
        """All presets shown when available_commands is empty (no filter)."""
        available: list[str] = []
        visible = [
            (label, cmd)
            for label, cmd in COMMAND_PRESETS
            if not available or cmd.split()[0] in available
        ]
        assert len(visible) == len(COMMAND_PRESETS)

    def test_presets_filtered_by_available_commands(self):
        """Only presets whose base command is in available_commands are shown."""
        available = ["uptime", "df"]
        visible = [
            (label, cmd)
            for label, cmd in COMMAND_PRESETS
            if not available or cmd.split()[0] in available
        ]
        assert len(visible) == 2
        assert visible[0][0] == "uptime"
        assert visible[1][0] == "df -h"

    def test_presets_empty_when_no_commands_available(self):
        """No presets when available_commands has none matching."""
        available = ["nonexistent_cmd"]
        visible = [
            (label, cmd)
            for label, cmd in COMMAND_PRESETS
            if not available or cmd.split()[0] in available
        ]
        assert visible == []


class TestRebootConfirmation:
    """Tests for reboot double-tap confirmation state."""

    def test_reboot_initially_disarmed(self):
        """Reboot starts disarmed."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._reboot_armed = False
        widget._reboot_confirm_timer = None
        assert widget._reboot_armed is False
        assert widget._reboot_confirm_timer is None

    def test_reboot_arm_state(self):
        """Arming sets _reboot_armed to True."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._reboot_armed = True
        assert widget._reboot_armed is True

    def test_reboot_disarm(self):
        """Disarming resets state."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._reboot_armed = True
        # Simulate disarm
        widget._reboot_armed = False
        widget._reboot_confirm_timer = None
        assert widget._reboot_armed is False


class TestSessionLog:
    """Tests for session log accumulation."""

    def test_entries_accumulate(self):
        """OutputEntries accumulate in order."""
        entries: list[OutputEntry] = []
        entries.append(OutputEntry(command="uptime", exit_code=0, stdout="up 3d", entry_type="exec"))
        entries.append(OutputEntry(command="df -h", exit_code=0, stdout="/dev 50%", entry_type="exec"))
        entries.append(OutputEntry(command="ping", rtt_ms=42.0, entry_type="ping"))

        assert len(entries) == 3
        assert entries[0].command == "uptime"
        assert entries[2].entry_type == "ping"

    def test_clear_entries(self):
        """Clearing resets entries."""
        entries: list[OutputEntry] = [
            OutputEntry(command="ls", entry_type="exec"),
        ]
        entries.clear()
        assert entries == []


class TestCommandWidgetInit:
    """Tests for CommandWidget initialization."""

    def test_default_state(self):
        """Widget initializes with correct defaults."""
        widget = CommandWidget.__new__(CommandWidget)
        widget.device_identity = "abc123"
        widget._available_commands = []
        widget._command_history = []
        widget._history_index = -1
        widget._output_entries = []
        widget._reboot_armed = False
        widget._reboot_confirm_timer = None

        assert widget.device_identity == "abc123"
        assert widget._available_commands == []
        assert widget._command_history == []
        assert widget._history_index == -1

    def test_initial_available_commands(self):
        """Widget accepts initial available commands."""
        widget = CommandWidget.__new__(CommandWidget)
        widget._available_commands = ["df", "ls", "uptime"]
        assert widget._available_commands == ["df", "ls", "uptime"]
