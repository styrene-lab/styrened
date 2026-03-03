"""Unit tests for PageServerService.

Tests service lifecycle, static page serving, dynamic handler dispatch,
configuration, and destination conflict detection.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.models.config import PageServerConfig
from styrened.services.page_server import (
    DestinationConflictError,
    PageServerService,
)


@pytest.fixture
def config(tmp_path: Path) -> PageServerConfig:
    """Create a test config with temporary pages directory."""
    return PageServerConfig(
        enabled=True,
        pages_dir=tmp_path / "pages",
        node_name="test-node",
    )


@pytest.fixture
def service(config: PageServerConfig) -> PageServerService:
    """Create a PageServerService with test config."""
    return PageServerService(config)


class TestServiceLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_creates_pages_dir(self, service, config):
        """Start should create the pages directory if it doesn't exist."""
        assert not config.pages_dir.exists()
        # Patch out RNS destination creation since RNS isn't available in tests
        with patch.object(service, "_create_destination"):
            service.start()
        assert config.pages_dir.exists()
        assert service.is_started

    def test_start_is_idempotent(self, service):
        """Calling start twice should not error."""
        with patch.object(service, "_create_destination"):
            service.start()
            service.start()
        assert service.is_started

    def test_stop_clears_state(self, service):
        """Stop should clear started flag and handlers."""
        with patch.object(service, "_create_destination"):
            service.start()
        service.stop()
        assert not service.is_started

    def test_stop_before_start(self, service):
        """Stop before start should be a no-op."""
        service.stop()
        assert not service.is_started

    def test_default_pages_dir(self, tmp_path):
        """When pages_dir is None, should use default path."""
        config = PageServerConfig(enabled=True, pages_dir=None)
        svc = PageServerService(config)
        with patch.object(svc, "_create_destination"), \
             patch("styrened.paths.data_dir", return_value=tmp_path):
            svc.start()
        assert svc.pages_dir == tmp_path / "pages"


class TestStaticPageServing:
    """Tests for static .mu file serving."""

    @pytest.mark.asyncio
    async def test_serve_static_page(self, service, config):
        """Should serve content from .mu files in pages directory."""
        with patch.object(service, "_create_destination"):
            service.start()
        # Create a test page
        page_file = config.pages_dir / "test.mu"
        page_file.write_text(">Test Page\nHello World\n")

        result = await service.serve_page(
            "/page/test.mu", None, "deadbeef12345678"
        )
        assert result == b">Test Page\nHello World\n"

    @pytest.mark.asyncio
    async def test_serve_nonexistent_page_returns_404(self, service):
        """Should return a not-found page for missing files."""
        with patch.object(service, "_create_destination"):
            service.start()

        result = await service.serve_page(
            "/page/missing.mu", None, "deadbeef12345678"
        )
        content = result.decode("utf-8")
        assert "Not Found" in content

    @pytest.mark.asyncio
    async def test_serve_non_mu_file_rejected(self, service, config):
        """Should not serve non-.mu files."""
        with patch.object(service, "_create_destination"):
            service.start()
        # Create a non-.mu file
        (config.pages_dir / "secret.txt").write_text("secret data")

        result = await service.serve_page(
            "/page/secret.txt", None, "deadbeef12345678"
        )
        content = result.decode("utf-8")
        assert "Not Found" in content

    def test_static_pages_lists_mu_files(self, service, config):
        """static_pages should list .mu files in pages directory."""
        with patch.object(service, "_create_destination"):
            service.start()
        (config.pages_dir / "alpha.mu").write_text(">Alpha")
        (config.pages_dir / "beta.mu").write_text(">Beta")
        (config.pages_dir / "notes.txt").write_text("not a page")

        pages = service.static_pages
        assert "alpha.mu" in pages
        assert "beta.mu" in pages
        assert "notes.txt" not in pages


class TestDynamicHandlers:
    """Tests for dynamic handler registration and dispatch."""

    @pytest.mark.asyncio
    async def test_register_and_serve_dynamic_handler(self, service):
        """Registered dynamic handler should be called for matching path."""
        with patch.object(service, "_create_destination"):
            service.start()

        async def handler(path, form_data, identity):
            return ">Dynamic\nGenerated content\n"

        service.register_dynamic_handler("/page/styrene/status.mu", handler)

        result = await service.serve_page(
            "/page/styrene/status.mu", None, "deadbeef12345678"
        )
        assert result == b">Dynamic\nGenerated content\n"

    @pytest.mark.asyncio
    async def test_dynamic_handler_receives_form_data(self, service):
        """Dynamic handler should receive form data."""
        with patch.object(service, "_create_destination"):
            service.start()

        received = {}

        async def handler(path, form_data, identity):
            received["form_data"] = form_data
            received["identity"] = identity
            return ">OK"

        service.register_dynamic_handler("/page/form.mu", handler)

        await service.serve_page(
            "/page/form.mu",
            {"action": "refresh"},
            "abc123",
        )
        assert received["form_data"] == {"action": "refresh"}
        assert received["identity"] == "abc123"

    @pytest.mark.asyncio
    async def test_dynamic_handler_error_returns_error_page(self, service):
        """Handler errors should produce an error page, not crash."""
        with patch.object(service, "_create_destination"):
            service.start()

        async def bad_handler(path, form_data, identity):
            raise RuntimeError("handler broke")

        service.register_dynamic_handler("/page/bad.mu", bad_handler)

        result = await service.serve_page(
            "/page/bad.mu", None, "deadbeef12345678"
        )
        content = result.decode("utf-8")
        assert "Error" in content

    @pytest.mark.asyncio
    async def test_dynamic_handler_takes_priority_over_static(self, service, config):
        """Dynamic handler should be preferred over static file with same name."""
        with patch.object(service, "_create_destination"):
            service.start()

        (config.pages_dir / "status.mu").write_text(">Static Version")

        async def handler(path, form_data, identity):
            return ">Dynamic Version"

        service.register_dynamic_handler("/page/status.mu", handler)

        result = await service.serve_page(
            "/page/status.mu", None, "deadbeef12345678"
        )
        assert result == b">Dynamic Version"

    def test_unregister_handler(self, service):
        """Unregistering a handler should remove it."""
        with patch.object(service, "_create_destination"):
            service.start()

        async def handler(path, form_data, identity):
            return ">OK"

        service.register_dynamic_handler("/page/test.mu", handler)
        assert "/page/test.mu" in service.registered_handlers

        assert service.unregister_dynamic_handler("/page/test.mu") is True
        assert "/page/test.mu" not in service.registered_handlers

    def test_unregister_nonexistent_handler(self, service):
        """Unregistering a non-existent handler should return False."""
        with patch.object(service, "_create_destination"):
            service.start()
        assert service.unregister_dynamic_handler("/page/nope.mu") is False

    def test_registered_handlers_list(self, service):
        """registered_handlers should list all registered paths."""
        with patch.object(service, "_create_destination"):
            service.start()

        async def h(p, f, i):
            return ""

        service.register_dynamic_handler("/page/a.mu", h)
        service.register_dynamic_handler("/page/b.mu", h)

        assert sorted(service.registered_handlers) == ["/page/a.mu", "/page/b.mu"]


class TestDestinationConflict:
    """Tests for hub coexistence destination guard."""

    def test_destination_conflict_sets_bridge_mode(self, service):
        """When destination creation raises, service should run in bridge mode."""
        with patch.object(
            service, "_create_destination", side_effect=DestinationConflictError("already registered")
        ):
            service.start()
        assert service.is_started
        assert not service.owns_destination


class TestConfig:
    """Tests for configuration handling."""

    def test_config_loaded(self, service, config):
        """Service should store config."""
        assert service._config is config

    def test_page_server_config_defaults(self):
        """Default PageServerConfig should have sane defaults."""
        config = PageServerConfig()
        assert config.enabled is False
        assert config.pages_dir is None
        assert config.node_name is None
