from __future__ import annotations

"""Tests for StyreneApp footer binding visibility."""

import pytest
from textual.binding import Binding

from styrened.tui.app import StyreneApp


def _binding_map() -> dict[str, Binding]:
    """Return StyreneApp BINDINGS keyed by key string."""
    return {
        b.key if isinstance(b, Binding) else b[0]: b
        for b in StyreneApp.BINDINGS
        if isinstance(b, Binding)
    }


class TestHiddenBindings:
    """Bindings for c, b, p must exist but be hidden (show=False)."""

    @pytest.mark.parametrize("key,description", [
        ("c", "Comms"),
        ("b", "Contacts"),
        ("p", "Provision"),
    ])
    def test_binding_exists_and_hidden(self, key: str, description: str) -> None:
        bmap = _binding_map()
        assert key in bmap, f"Binding for '{key}' not found"
        binding = bmap[key]
        assert binding.show is False, f"Binding '{key}' ({description}) should have show=False"
        assert binding.description == description


class TestVisibleBindings:
    """Core navigation bindings must be visible (show=True)."""

    @pytest.mark.parametrize("key,description", [
        ("n", "Nodes"),
        ("m", "Mail"),
        ("a", "Announce"),
    ])
    def test_binding_exists_and_visible(self, key: str, description: str) -> None:
        bmap = _binding_map()
        assert key in bmap, f"Binding for '{key}' not found"
        binding = bmap[key]
        assert binding.show is True, f"Binding '{key}' ({description}) should have show=True"
        assert binding.description == description


class TestVisibleBindingCount:
    """Footer should not be cluttered — visible bindings should be manageable."""

    def test_visible_binding_count_reasonable(self) -> None:
        visible = [
            b for b in StyreneApp.BINDINGS
            if isinstance(b, Binding) and b.show
        ]
        # Should be <= 8 visible bindings to fit in 80-col footer
        assert len(visible) <= 8, f"Too many visible bindings: {len(visible)}"
