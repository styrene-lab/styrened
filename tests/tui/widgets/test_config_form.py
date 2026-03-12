"""Tests for configuration form widget."""
from __future__ import annotations


from styrened.tui.widgets.config_form import ConfigForm, HostnameValidator


def test_hostname_validator_valid():
    """Test hostname validator with valid hostnames."""
    validator = HostnameValidator()

    assert validator.validate("test-host").is_valid
    assert validator.validate("node01").is_valid
    assert validator.validate("a").is_valid
    assert validator.validate("test-123").is_valid


def test_hostname_validator_invalid():
    """Test hostname validator with invalid hostnames."""
    validator = HostnameValidator()

    # Empty
    assert not validator.validate("").is_valid

    # Uppercase
    assert not validator.validate("Test-Host").is_valid

    # Special characters
    assert not validator.validate("test_host").is_valid
    assert not validator.validate("test.host").is_valid

    # Starting/ending with hyphen
    assert not validator.validate("-test").is_valid
    assert not validator.validate("test-").is_valid


def test_config_form_instantiation():
    """Test config form can be instantiated."""
    form = ConfigForm()
    assert form is not None


def test_config_form_config_property():
    """Test config property returns current values."""
    form = ConfigForm()
    # Initially empty
    config = form.config
    assert isinstance(config, dict)
