"""Unit tests for the hub bridge helper module.

Tests environment variable reading, page generation, and the
serve_dynamic_page entry point.
"""

import os
from io import StringIO
from unittest.mock import patch

from styrened.pages.hub_bridge import (
    get_form_data,
    get_remote_identity,
    serve_dynamic_page,
)
from styrened.pages.parser import parse_page_directives


class TestGetRemoteIdentity:
    """Test reading remote identity from environment."""

    def test_reads_from_env(self):
        """Should read remote_identity env var."""
        with patch.dict(os.environ, {"remote_identity": "abcdef1234567890"}):
            assert get_remote_identity() == "abcdef1234567890"

    def test_returns_empty_when_missing(self):
        """Should return empty string when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_remote_identity() == ""


class TestGetFormData:
    """Test reading form data from environment."""

    def test_reads_field_prefixed_vars(self):
        """Should extract field_ prefixed env vars."""
        env = {
            "field_action": "refresh",
            "field_name": "test",
            "remote_identity": "abc123",  # Not a field
            "PATH": "/usr/bin",  # Not a field
        }
        with patch.dict(os.environ, env, clear=True):
            result = get_form_data()
        assert result == {"action": "refresh", "name": "test"}

    def test_empty_when_no_fields(self):
        """Should return empty dict when no field_ vars present."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            assert get_form_data() == {}


class TestServeDynamicPage:
    """Test the serve_dynamic_page entry point."""

    def test_generates_dual_layer_page(self):
        """Should produce a page parseable by parse_page_directives."""
        def generator(remote_identity, form_data):
            micron = ">Fleet Status\n- edge-03: ACTIVE\n"
            data = {"nodes": [{"name": "edge-03", "status": "active"}]}
            return micron, data

        output = StringIO()
        env = {"remote_identity": "deadbeef12345678"}
        with patch.dict(os.environ, env, clear=True), \
             patch("sys.stdout", output):
            serve_dynamic_page(
                generator,
                page_type="fleet",
                encoding="json",
                cache_ttl=60,
            )

        page = output.getvalue()
        assert ">Fleet Status" in page

        # Verify structured data can be parsed back
        result = parse_page_directives(page)
        assert result is not None
        assert result.metadata.page_type == "fleet"
        assert result.data["nodes"][0]["name"] == "edge-03"

    def test_generator_error_produces_error_page(self):
        """Generator exceptions should produce an error page, not crash."""
        def bad_generator(remote_identity, form_data):
            raise RuntimeError("database down")

        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), \
             patch("sys.stdout", output):
            serve_dynamic_page(bad_generator, page_type="error_test")

        page = output.getvalue()
        assert "Error" in page
        assert "database down" in page

    def test_passes_form_data_to_generator(self):
        """Should pass parsed form data to generator."""
        received = {}

        def generator(remote_identity, form_data):
            received["identity"] = remote_identity
            received["form_data"] = form_data
            return ">OK", {}

        env = {
            "remote_identity": "abc123",
            "field_action": "submit",
            "field_value": "42",
        }
        with patch.dict(os.environ, env, clear=True), \
             patch("sys.stdout", StringIO()):
            serve_dynamic_page(generator, page_type="test")

        assert received["identity"] == "abc123"
        assert received["form_data"] == {"action": "submit", "value": "42"}

    def test_b85_encoding(self):
        """Should produce b85-encoded blocks by default."""
        def generator(remote_identity, form_data):
            return ">Test", {"key": "value"}

        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), \
             patch("sys.stdout", output):
            serve_dynamic_page(generator, page_type="test")

        page = output.getvalue()
        assert "#!sd:b85:begin" in page
        assert "#!sd:b85:end" in page

        result = parse_page_directives(page)
        assert result is not None
        assert result.data == {"key": "value"}
