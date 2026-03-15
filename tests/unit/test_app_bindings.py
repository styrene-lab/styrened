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
    """Power-user / legacy bindings must exist but stay hidden (show=False)."""

    @pytest.mark.parametrize("key,description", [
        ("p", "Provision"),
        ("x", "Exchange"),  # legacy alias for e
        ("i", "Mail"),       # legacy alias for m
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
        ("g", "Global"),
        ("n", "Nodes"),
        ("e", "Exchange"),
        ("m", "Mail"),
        ("c", "Comms"),
        ("b", "Contacts"),
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
        # 9 visible: ?, `, g, n, e, m, c, b, a
        assert len(visible) <= 10, f"Too many visible bindings: {len(visible)}"
