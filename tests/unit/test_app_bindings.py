from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Requires tui-home-cop features not yet on main")

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
    """Bindings for n, x, m, a must be visible (show=True)."""

    @pytest.mark.parametrize("key,description", [
        ("n", "Nodes"),
        ("x", "Exchange"),
        ("m", "Mail"),
        ("a", "Announce"),
    ])
    def test_binding_exists_and_visible(self, key: str, description: str) -> None:
        bmap = _binding_map()
        assert key in bmap, f"Binding for '{key}' not found"
        binding = bmap[key]
        assert binding.show is True, f"Binding '{key}' ({description}) should have show=True"
        assert binding.description == description


class TestVisibleBindingSet:
    """The expected visible bindings appear in the footer."""

    def test_expected_visible_bindings_present(self) -> None:
        visible = {
            b.key: b.description
            for b in StyreneApp.BINDINGS
            if isinstance(b, Binding) and b.show
        }
        expected = {
            "?": "Help",
            "grave_accent": "Admin",
            "n": "Nodes",
            "x": "Exchange",
            "m": "Mail",
            "a": "Announce",
        }
        for key, desc in expected.items():
            assert key in visible, f"Expected visible binding '{key}' ({desc}) not found"
            assert visible[key] == desc
