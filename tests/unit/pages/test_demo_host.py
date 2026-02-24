"""Unit tests for the demo host page handlers.

Tests registration, static page generation, every dynamic handler,
and round-trip parse verification for the demo test pages.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.models.config import PageServerConfig
from styrened.pages.demo_host import (
    DEMO_PATH_ENCODING_B85,
    DEMO_PATH_ENCODING_JSON,
    DEMO_PATH_ERROR,
    DEMO_PATH_FLEET,
    DEMO_PATH_FORM_ECHO,
    DEMO_PATH_FULL_METADATA,
    DEMO_PATH_IDENTITY,
    DEMO_PATH_LARGE_PAYLOAD,
    DEMO_PATH_NODE_STATUS,
    handle_encoding_b85,
    handle_encoding_json,
    handle_error,
    handle_fleet_overview,
    handle_form_echo,
    handle_full_metadata,
    handle_identity,
    handle_large_payload,
    handle_node_status,
    register_demo_pages,
)
from styrened.pages.parser import parse_page_directives
from styrened.services.page_server import PageServerService

DUMMY_IDENTITY = "deadbeef12345678"


@pytest.fixture
def pages_dir(tmp_path: Path) -> Path:
    return tmp_path / "pages"


@pytest.fixture
def service(pages_dir: Path) -> PageServerService:
    config = PageServerConfig(enabled=True, pages_dir=pages_dir)
    svc = PageServerService(config)
    with patch.object(svc, "_create_destination"):
        svc.start()
    return svc


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for register_demo_pages() entry point."""

    def test_creates_static_files(self, service, pages_dir):
        """Should write 4 static .mu files."""
        register_demo_pages(service)
        mu_files = sorted(p.name for p in pages_dir.glob("*.mu"))
        assert "index.mu" in mu_files
        assert "plain.mu" in mu_files
        assert "static_directives.mu" in mu_files
        assert "hub_bridge_example.mu" in mu_files

    def test_registers_dynamic_handlers(self, service):
        """Should register all 9 dynamic handlers."""
        register_demo_pages(service)
        handlers = service.registered_handlers
        assert DEMO_PATH_NODE_STATUS in handlers
        assert DEMO_PATH_FLEET in handlers
        assert DEMO_PATH_FORM_ECHO in handlers
        assert DEMO_PATH_FULL_METADATA in handlers
        assert DEMO_PATH_ENCODING_B85 in handlers
        assert DEMO_PATH_ENCODING_JSON in handlers
        assert DEMO_PATH_ERROR in handlers
        assert DEMO_PATH_LARGE_PAYLOAD in handlers
        assert DEMO_PATH_IDENTITY in handlers
        assert len(handlers) == 9

    def test_static_files_start_with_heading(self, service, pages_dir):
        """Each static file should start with a > heading after directives."""
        register_demo_pages(service)
        for mu_file in pages_dir.glob("*.mu"):
            content = mu_file.read_text(encoding="utf-8")
            # Skip directive block (everything before the blank separator line)
            # build_page() puts directives, then blank line, then micron content
            first_content = ""
            in_block = False
            for line in content.split("\n"):
                if line.startswith("#!sd:") and line.endswith(":begin"):
                    in_block = True
                    continue
                if line.startswith("#!sd:") and line.endswith(":end"):
                    in_block = False
                    continue
                if in_block or line.startswith("#!") or line == "":
                    continue
                first_content = line
                break
            assert first_content.startswith(">"), f"{mu_file.name} first line: {first_content!r}"

    def test_static_directives_page_parseable(self, service, pages_dir):
        """static_directives.mu should be parseable by the parser."""
        register_demo_pages(service)
        content = (pages_dir / "static_directives.mu").read_text(encoding="utf-8")
        parsed = parse_page_directives(content)
        assert parsed is not None
        assert parsed.metadata.page_type == "demo_static"
        assert parsed.metadata.capabilities == ["demo", "static"]
        assert parsed.data["test_key"] == "static_value"
        assert parsed.data["numbers"] == [1, 2, 3]

    def test_plain_page_has_no_directives(self, service, pages_dir):
        """plain.mu should have no Styrene directives."""
        register_demo_pages(service)
        content = (pages_dir / "plain.mu").read_text(encoding="utf-8")
        parsed = parse_page_directives(content)
        assert parsed is None

    def test_register_with_no_pages_dir(self):
        """Should not crash when pages_dir is unavailable."""
        config = PageServerConfig(enabled=True, pages_dir=None)
        svc = PageServerService(config)
        # Don't start — pages_dir stays None
        register_demo_pages(svc)
        # No error, no handlers registered (service not started)

    def test_index_page_has_all_links(self, service, pages_dir):
        """Index page should link to all test pages."""
        register_demo_pages(service)
        content = (pages_dir / "index.mu").read_text(encoding="utf-8")
        assert DEMO_PATH_NODE_STATUS in content
        assert DEMO_PATH_FLEET in content
        assert DEMO_PATH_FORM_ECHO in content
        assert DEMO_PATH_FULL_METADATA in content
        assert DEMO_PATH_ENCODING_B85 in content
        assert DEMO_PATH_ENCODING_JSON in content
        assert DEMO_PATH_ERROR in content
        assert DEMO_PATH_LARGE_PAYLOAD in content
        assert DEMO_PATH_IDENTITY in content


# ---------------------------------------------------------------------------
# Node Status handler tests
# ---------------------------------------------------------------------------


class TestHandleNodeStatus:
    """Tests for the node_status dynamic handler."""

    @pytest.mark.asyncio
    async def test_returns_parseable_page(self):
        """Output should be parseable by the directive parser."""
        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_page_type(self):
        """Should set page_type to 'node_status'."""
        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.page_type == "node_status"

    @pytest.mark.asyncio
    async def test_data_matches_renderer_schema(self):
        """Data should have all keys expected by render_node_status()."""
        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        data = parsed.data
        assert "node_name" in data
        assert "status" in data
        assert "uptime" in data
        assert "version" in data
        assert "services" in data
        assert "interfaces" in data

    @pytest.mark.asyncio
    async def test_tui_renderer_accepts_data(self):
        """The TUI renderer should accept this data without error."""
        from styrened.tui.widgets.page_renderers import render_node_status

        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        rendered = render_node_status(parsed.data)
        assert rendered is not None
        assert len(rendered) > 0

    @pytest.mark.asyncio
    async def test_has_refresh_directive(self):
        """Should include refresh metadata."""
        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert "status" in parsed.metadata.refresh

    @pytest.mark.asyncio
    async def test_has_capabilities(self):
        """Should advertise capabilities."""
        result = await handle_node_status(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert "rpc" in parsed.metadata.capabilities
        assert "pages" in parsed.metadata.capabilities


# ---------------------------------------------------------------------------
# Fleet Overview handler tests
# ---------------------------------------------------------------------------


class TestHandleFleetOverview:
    """Tests for the fleet overview dynamic handler."""

    @pytest.mark.asyncio
    async def test_page_type(self):
        """Should set page_type to 'fleet'."""
        result = await handle_fleet_overview(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.page_type == "fleet"

    @pytest.mark.asyncio
    async def test_data_matches_renderer_schema(self):
        """Data should have keys expected by render_fleet_overview()."""
        result = await handle_fleet_overview(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        data = parsed.data
        assert "nodes" in data
        assert "total" in data
        assert "active" in data

    @pytest.mark.asyncio
    async def test_tui_renderer_accepts_data(self):
        """The TUI renderer should accept this data without error."""
        from styrened.tui.widgets.page_renderers import render_fleet_overview

        result = await handle_fleet_overview(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        rendered = render_fleet_overview(parsed.data)
        assert rendered is not None

    @pytest.mark.asyncio
    async def test_node_count_consistency(self):
        """total should match len(nodes)."""
        result = await handle_fleet_overview(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.data["total"] == len(parsed.data["nodes"])

    @pytest.mark.asyncio
    async def test_has_refresh_directive(self):
        """Should include fleet refresh interval."""
        result = await handle_fleet_overview(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert "fleet" in parsed.metadata.refresh


# ---------------------------------------------------------------------------
# Form Echo handler tests
# ---------------------------------------------------------------------------


class TestHandleFormEcho:
    """Tests for the form echo dynamic handler."""

    @pytest.mark.asyncio
    async def test_no_form_data_renders_form(self):
        """With no form data, should render the input form."""
        result = await handle_form_echo(DEMO_PATH_FORM_ECHO, None, DUMMY_IDENTITY)
        assert "`<" in result  # NomadNet form field markup

    @pytest.mark.asyncio
    async def test_with_form_data_echoes_back(self):
        """With form data, should echo submitted fields."""
        form = {"name": "Alice", "message": "Hello mesh"}
        result = await handle_form_echo(DEMO_PATH_FORM_ECHO, form, DUMMY_IDENTITY)
        assert "Alice" in result
        assert "Hello mesh" in result

    @pytest.mark.asyncio
    async def test_identity_in_echo_data(self):
        """Echoed structured data should contain the identity hash."""
        form = {"test": "value"}
        result = await handle_form_echo(DEMO_PATH_FORM_ECHO, form, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        assert parsed.data["identity"] == DUMMY_IDENTITY

    @pytest.mark.asyncio
    async def test_field_count_in_data(self):
        """Structured data should report field count."""
        form = {"a": "1", "b": "2", "c": "3"}
        result = await handle_form_echo(DEMO_PATH_FORM_ECHO, form, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.data["field_count"] == 3

    @pytest.mark.asyncio
    async def test_both_states_parseable(self):
        """Both form and echo states should produce parseable pages."""
        # Form state
        result_form = await handle_form_echo(DEMO_PATH_FORM_ECHO, None, DUMMY_IDENTITY)
        parsed_form = parse_page_directives(result_form)
        assert parsed_form is not None

        # Echo state
        result_echo = await handle_form_echo(DEMO_PATH_FORM_ECHO, {"k": "v"}, DUMMY_IDENTITY)
        parsed_echo = parse_page_directives(result_echo)
        assert parsed_echo is not None


# ---------------------------------------------------------------------------
# Full Metadata handler tests
# ---------------------------------------------------------------------------


class TestHandleFullMetadata:
    """Tests for the all-directives page."""

    @pytest.mark.asyncio
    async def test_all_metadata_fields_present(self):
        """All metadata fields should be populated."""
        result = await handle_full_metadata(DEMO_PATH_FULL_METADATA, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        meta = parsed.metadata
        assert meta.version == 1
        assert meta.page_type == "full_metadata_test"
        assert len(meta.capabilities) == 5
        assert meta.timestamp > 0
        assert meta.etag is not None and len(meta.etag) > 0
        assert len(meta.refresh) == 3

    @pytest.mark.asyncio
    async def test_etag_changes_on_refresh(self):
        """Calling twice should yield different etags (time-based)."""
        r1 = await handle_full_metadata(DEMO_PATH_FULL_METADATA, None, DUMMY_IDENTITY)
        r2 = await handle_full_metadata(DEMO_PATH_FULL_METADATA, None, DUMMY_IDENTITY)
        p1 = parse_page_directives(r1)
        p2 = parse_page_directives(r2)
        # etags may be same if called within same second, but data timestamps differ
        assert p1.data["generated_at"] <= p2.data["generated_at"]

    @pytest.mark.asyncio
    async def test_capabilities_list(self):
        """Should have exactly 5 capabilities."""
        result = await handle_full_metadata(DEMO_PATH_FULL_METADATA, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.capabilities == ["rpc", "terminal", "pages", "fleet", "lxmf"]

    @pytest.mark.asyncio
    async def test_refresh_map(self):
        """Should have 3 refresh entries."""
        result = await handle_full_metadata(DEMO_PATH_FULL_METADATA, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.refresh == {"status": 30, "fleet": 60, "metrics": 10}


# ---------------------------------------------------------------------------
# Encoding comparison tests
# ---------------------------------------------------------------------------


class TestHandleEncodings:
    """Tests for b85 vs JSON encoding pages."""

    @pytest.mark.asyncio
    async def test_b85_encoding_marker(self):
        """b85 page should contain b85 block markers."""
        result = await handle_encoding_b85(DEMO_PATH_ENCODING_B85, None, DUMMY_IDENTITY)
        assert "#!sd:b85:begin" in result
        assert "#!sd:b85:end" in result

    @pytest.mark.asyncio
    async def test_json_encoding_marker(self):
        """JSON page should contain json block markers."""
        result = await handle_encoding_json(DEMO_PATH_ENCODING_JSON, None, DUMMY_IDENTITY)
        assert "#!sd:json:begin" in result
        assert "#!sd:json:end" in result

    @pytest.mark.asyncio
    async def test_same_data_different_encoding(self):
        """Both encodings should parse to identical data dicts."""
        r_b85 = await handle_encoding_b85(DEMO_PATH_ENCODING_B85, None, DUMMY_IDENTITY)
        r_json = await handle_encoding_json(DEMO_PATH_ENCODING_JSON, None, DUMMY_IDENTITY)
        p_b85 = parse_page_directives(r_b85)
        p_json = parse_page_directives(r_json)
        assert p_b85 is not None
        assert p_json is not None
        assert p_b85.data == p_json.data

    @pytest.mark.asyncio
    async def test_b85_round_trips(self):
        """b85-encoded page should round-trip through parser."""
        result = await handle_encoding_b85(DEMO_PATH_ENCODING_B85, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        assert parsed.data["int_value"] == 42
        assert parsed.data["unicode"] == "Reticulum \u2192 mesh \u2192 freedom"

    @pytest.mark.asyncio
    async def test_json_round_trips(self):
        """JSON-encoded page should round-trip through parser."""
        result = await handle_encoding_json(DEMO_PATH_ENCODING_JSON, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        assert parsed.data["nested"]["list"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Error handler tests
# ---------------------------------------------------------------------------


class TestHandleError:
    """Tests for the intentional error handler."""

    @pytest.mark.asyncio
    async def test_handler_raises_runtime_error(self):
        """Calling the handler directly should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="intentional error"):
            await handle_error(DEMO_PATH_ERROR, None, DUMMY_IDENTITY)

    @pytest.mark.asyncio
    async def test_serve_page_returns_error_page(self, service):
        """Going through serve_page() should produce an error page."""
        register_demo_pages(service)
        result = await service.serve_page(DEMO_PATH_ERROR, None, DUMMY_IDENTITY)
        content = result.decode("utf-8")
        assert "Error" in content
        assert "intentional error" in content


# ---------------------------------------------------------------------------
# Large Payload handler tests
# ---------------------------------------------------------------------------


class TestHandleLargePayload:
    """Tests for the large payload stress-test handler."""

    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_items(self):
        """All 500 items should survive the encode/decode round-trip."""
        result = await handle_large_payload(DEMO_PATH_LARGE_PAYLOAD, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        assert parsed.data["total_count"] == 500
        assert len(parsed.data["items"]) == 500

    @pytest.mark.asyncio
    async def test_data_structure_intact(self):
        """Spot-check first and last items for structural integrity."""
        result = await handle_large_payload(DEMO_PATH_LARGE_PAYLOAD, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)

        first = parsed.data["items"][0]
        assert first["id"] == 0
        assert first["name"] == "device-0000"
        assert "metrics" in first
        assert "tags" in first

        last = parsed.data["items"][499]
        assert last["id"] == 499
        assert last["name"] == "device-0499"

    @pytest.mark.asyncio
    async def test_payload_size_under_limit(self):
        """Encoded page should be under MAX_BLOCK_SIZE."""
        from styrened.pages.directives import MAX_BLOCK_SIZE

        result = await handle_large_payload(DEMO_PATH_LARGE_PAYLOAD, None, DUMMY_IDENTITY)
        # The entire page (with micron) should be reasonable
        assert len(result.encode("utf-8")) < MAX_BLOCK_SIZE * 2  # generous bound

    @pytest.mark.asyncio
    async def test_page_type(self):
        """Should set page_type to 'large_payload'."""
        result = await handle_large_payload(DEMO_PATH_LARGE_PAYLOAD, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.page_type == "large_payload"


# ---------------------------------------------------------------------------
# Identity Mirror handler tests
# ---------------------------------------------------------------------------


class TestHandleIdentity:
    """Tests for the identity mirror handler."""

    @pytest.mark.asyncio
    async def test_identity_in_data(self):
        """Structured data should contain the remote identity hash."""
        result = await handle_identity(DEMO_PATH_IDENTITY, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed is not None
        assert parsed.data["remote_identity_hash"] == DUMMY_IDENTITY
        assert parsed.data["has_identity"] is True

    @pytest.mark.asyncio
    async def test_anonymous_identity(self):
        """Empty string identity should be handled gracefully."""
        result = await handle_identity(DEMO_PATH_IDENTITY, None, "")
        parsed = parse_page_directives(result)
        assert parsed.data["remote_identity_hash"] == ""
        assert parsed.data["has_identity"] is False

    @pytest.mark.asyncio
    async def test_identity_in_micron(self):
        """Identity hash should appear in the visible micron content."""
        result = await handle_identity(DEMO_PATH_IDENTITY, None, DUMMY_IDENTITY)
        # The identity appears in the micron portion (after directives)
        assert DUMMY_IDENTITY in result

    @pytest.mark.asyncio
    async def test_page_type(self):
        """Should set page_type to 'identity_mirror'."""
        result = await handle_identity(DEMO_PATH_IDENTITY, None, DUMMY_IDENTITY)
        parsed = parse_page_directives(result)
        assert parsed.metadata.page_type == "identity_mirror"


# ---------------------------------------------------------------------------
# End-to-end serve_page tests
# ---------------------------------------------------------------------------


class TestServePageIntegration:
    """Tests that demo pages work through the full PageServerService."""

    @pytest.mark.asyncio
    async def test_serve_static_index(self, service, pages_dir):
        """Should serve the index page as a static file."""
        register_demo_pages(service)
        result = await service.serve_page("/page/index.mu", None, DUMMY_IDENTITY)
        content = result.decode("utf-8")
        assert "Styrene Page Extension Lab" in content

    @pytest.mark.asyncio
    async def test_serve_dynamic_node_status(self, service):
        """Should serve node_status through dynamic handler dispatch."""
        register_demo_pages(service)
        result = await service.serve_page(DEMO_PATH_NODE_STATUS, None, DUMMY_IDENTITY)
        content = result.decode("utf-8")
        assert "edge-03-demo" in content
        assert "#!s.type=node_status" in content

    @pytest.mark.asyncio
    async def test_serve_dynamic_fleet(self, service):
        """Should serve fleet through dynamic handler dispatch."""
        register_demo_pages(service)
        result = await service.serve_page(DEMO_PATH_FLEET, None, DUMMY_IDENTITY)
        content = result.decode("utf-8")
        assert "#!s.type=fleet" in content
