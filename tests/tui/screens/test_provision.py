"""Tests for provisioning screen."""

from styrened.tui.screens.provision import ProvisionScreen


def test_provision_screen_instantiation():
    """Test provision screen can be instantiated."""
    screen = ProvisionScreen()
    assert screen is not None


def test_provision_screen_initial_state():
    """Test provision screen initial state."""
    screen = ProvisionScreen()

    # Initially no selections
    assert screen._selected_profile is None
    assert screen._selected_hardware is None
    assert screen._selected_storage is None
    assert screen._config == {}
