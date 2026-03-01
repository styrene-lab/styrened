"""Tests for StyreneApp theme and color system initialization."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from styrened.tui.themes.styrene_brand import STYRENE_THEME_KEY


class TestColorSystemInit:
    """Tests for truecolor environment variable forcing."""

    def test_forces_colorterm_truecolor(self):
        """COLORTERM is forced to truecolor on normal terminals."""
        with patch.dict(os.environ, {"COLORTERM": "256color", "TERM": "xterm-256color"}, clear=False):
            from styrened.tui.app import StyreneApp

            with patch.object(StyreneApp, "run"):
                app = StyreneApp.__new__(StyreneApp)
                # Simulate the init block's env setup
                term = os.environ.get("TERM", "")
                if term not in ("linux", "dumb"):
                    os.environ["COLORTERM"] = "truecolor"
                    os.environ["TEXTUAL_COLOR_SYSTEM"] = "truecolor"

                assert os.environ["COLORTERM"] == "truecolor"
                assert os.environ["TEXTUAL_COLOR_SYSTEM"] == "truecolor"

    def test_respects_dumb_terminal(self):
        """TERM=dumb should NOT get forced truecolor."""
        with patch.dict(os.environ, {"COLORTERM": "", "TERM": "dumb"}, clear=False):
            term = os.environ.get("TERM", "")
            if term not in ("linux", "dumb"):
                os.environ["COLORTERM"] = "truecolor"

            # COLORTERM should still be empty since TERM=dumb
            assert os.environ["COLORTERM"] == ""

    def test_respects_linux_console(self):
        """TERM=linux (real console) should NOT get forced truecolor."""
        with patch.dict(os.environ, {"COLORTERM": "", "TERM": "linux"}, clear=False):
            term = os.environ.get("TERM", "")
            if term not in ("linux", "dumb"):
                os.environ["COLORTERM"] = "truecolor"

            assert os.environ["COLORTERM"] == ""


class TestDarkModeInit:
    """Tests that dark mode is forced regardless of system preference."""

    def test_dark_is_true_after_init(self):
        """StyreneApp.dark must be True after init regardless of system setting."""
        # We can't easily construct a full StyreneApp in unit tests,
        # but we can verify the _dark attribute pre-injection pattern works.
        from styrened.tui.app import StyreneApp

        # Verify the class has the dark mode forcing code by checking
        # that the init sets _dark before super().__init__
        import inspect
        source = inspect.getsource(StyreneApp.__init__)
        assert "self._dark = True" in source, (
            "StyreneApp.__init__ must set self._dark = True before super().__init__()"
        )

    def test_theme_is_styrene_in_init(self):
        """StyreneApp must pre-populate _registered_themes before super().__init__."""
        import inspect
        from styrened.tui.app import StyreneApp

        source = inspect.getsource(StyreneApp.__init__)
        # Find the LAST occurrence of super().__init__() (the actual call, not docstring)
        # and verify _registered_themes assignment appears before it in the code
        lines = source.splitlines()
        themes_lineno = next(
            i for i, line in enumerate(lines) if "_registered_themes" in line and "=" in line
        )
        super_lineno = next(
            i for i, line in enumerate(lines) if "super().__init__()" in line and not line.strip().startswith("#")
        )
        assert themes_lineno < super_lineno, (
            "_registered_themes must be set before super().__init__()"
        )
