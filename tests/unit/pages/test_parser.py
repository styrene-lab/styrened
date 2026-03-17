"""Unit tests for the Styrene page directive parser.

Tests extraction of PageMetadata and structured data blocks from
raw micron page source, including edge cases and malformed input.
"""
from __future__ import annotations

import base64
import json

import msgpack

from styrened.pages.directives import (
    PROTOCOL_VERSION,
)
from styrened.pages.parser import (
    _decode_block,
    _parse_capabilities,
    _parse_refresh,
    parse_page_directives,
)


class TestParseCapabilities:
    """Test capability string parsing."""

    def test_empty_string(self):
        assert _parse_capabilities("") == []

    def test_single_capability(self):
        assert _parse_capabilities("rpc") == ["rpc"]

    def test_multiple_capabilities(self):
        assert _parse_capabilities("rpc,terminal,pages") == ["rpc", "terminal", "pages"]

    def test_strips_whitespace(self):
        assert _parse_capabilities("rpc , terminal , pages") == ["rpc", "terminal", "pages"]

    def test_ignores_empty_entries(self):
        assert _parse_capabilities("rpc,,terminal") == ["rpc", "terminal"]


class TestParseRefresh:
    """Test refresh pair parsing."""

    def test_empty_string(self):
        assert _parse_refresh("") == {}

    def test_single_pair(self):
        assert _parse_refresh("status:30") == {"status": 30}

    def test_multiple_pairs(self):
        assert _parse_refresh("status:30,fleet:60") == {"status": 30, "fleet": 60}

    def test_strips_whitespace(self):
        assert _parse_refresh("status : 30 , fleet : 60") == {"status": 30, "fleet": 60}

    def test_ignores_malformed_pairs(self):
        result = _parse_refresh("status:30,bad,fleet:60")
        assert result == {"status": 30, "fleet": 60}

    def test_ignores_non_integer_intervals(self):
        result = _parse_refresh("status:abc,fleet:60")
        assert result == {"fleet": 60}


class TestDecodeBlock:
    """Test block decoding for b85 and json encodings."""

    def test_json_decode_valid(self):
        lines = ['{"key": "value", "count": 42}']
        result = _decode_block(lines, "json")
        assert result == {"key": "value", "count": 42}

    def test_json_decode_non_dict_returns_none(self):
        lines = ['[1, 2, 3]']
        result = _decode_block(lines, "json")
        assert result is None

    def test_json_decode_invalid_returns_none(self):
        lines = ["{invalid json}"]
        result = _decode_block(lines, "json")
        assert result is None

    def test_b85_decode_valid(self):
        data = {"status": "online", "uptime": 3600}
        binary = msgpack.packb(data, use_bin_type=True)
        encoded = base64.b85encode(binary).decode("ascii")
        result = _decode_block([encoded], "b85")
        assert result == data

    def test_b85_decode_invalid_base85_returns_none(self):
        result = _decode_block(["not-valid-base85!!!"], "b85")
        assert result is None

    def test_b85_decode_invalid_msgpack_returns_none(self):
        # Valid base85 of random bytes that aren't valid msgpack
        encoded = base64.b85encode(b"\xff\xfe\xfd").decode("ascii")
        result = _decode_block([encoded], "b85")
        assert result is None

    def test_empty_lines_returns_none(self):
        result = _decode_block([], "json")
        assert result is None

    def test_unsupported_encoding_returns_none(self):
        result = _decode_block(["data"], "protobuf")
        assert result is None


class TestParsePageDirectives:
    """Test the main parse_page_directives function."""

    def test_empty_source_returns_none(self):
        """Empty string should return None."""
        assert parse_page_directives("") is None

    def test_no_directives_returns_none(self):
        """Plain micron with no Styrene directives returns None."""
        source = ">Fleet Status\n- edge-03: ACTIVE\n- edge-07: ACTIVE\n"
        assert parse_page_directives(source) is None

    def test_nomadnet_cache_only_returns_none(self):
        """Standard NomadNet #!c= directive alone is not a Styrene directive."""
        source = "#!c=60\n>Status\nOnline\n"
        assert parse_page_directives(source) is None

    def test_metadata_only(self):
        """Page with Styrene metadata but no data block."""
        source = "#!s.v=1\n#!s.type=status\n>Status\nOnline\n"
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.version == 1
        assert result.metadata.page_type == "status"
        assert result.data == {}

    def test_all_metadata_fields(self):
        """All metadata directive keys should be parsed."""
        source = (
            "#!s.v=1\n"
            "#!s.type=fleet\n"
            "#!s.caps=rpc,terminal,pages\n"
            "#!s.ts=1708000000.5\n"
            "#!s.etag=a1b2c3d4\n"
            "#!s.refresh=status:30,fleet:60\n"
            "\n"
            ">Fleet\nOK\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        meta = result.metadata
        assert meta.version == 1
        assert meta.page_type == "fleet"
        assert meta.capabilities == ["rpc", "terminal", "pages"]
        assert meta.timestamp == 1708000000.5
        assert meta.etag == "a1b2c3d4"
        assert meta.refresh == {"status": 30, "fleet": 60}

    def test_metadata_with_b85_block(self):
        """Parse metadata and base85-encoded msgpack data block."""
        data = {"nodes": [{"name": "edge-03", "status": "active"}]}
        binary = msgpack.packb(data, use_bin_type=True)
        encoded = base64.b85encode(binary).decode("ascii")

        source = (
            "#!s.v=1\n"
            "#!s.type=fleet\n"
            "#!sd:b85:begin\n"
            f"{encoded}\n"
            "#!sd:b85:end\n"
            "\n"
            ">Fleet\nOK\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.page_type == "fleet"
        assert result.encoding == "b85"
        assert result.data == data

    def test_metadata_with_json_block(self):
        """Parse metadata and JSON data block."""
        data = {"nodes": [{"name": "edge-03", "status": "active"}]}
        json_str = json.dumps(data, separators=(",", ":"))

        source = (
            "#!s.v=1\n"
            "#!s.type=fleet\n"
            "#!sd:json:begin\n"
            f"{json_str}\n"
            "#!sd:json:end\n"
            "\n"
            ">Fleet\nOK\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.encoding == "json"
        assert result.data == data

    def test_malformed_block_returns_empty_data(self):
        """Malformed data block should produce empty data dict."""
        source = (
            "#!s.v=1\n"
            "#!s.type=test\n"
            "#!sd:b85:begin\n"
            "not-valid-base85-garbage!!!\n"
            "#!sd:b85:end\n"
            "\n"
            ">Test\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.page_type == "test"
        assert result.data == {}

    def test_unclosed_block_is_ignored(self):
        """Block without end marker should be treated as partial/ignored."""
        source = (
            "#!s.v=1\n"
            "#!s.type=test\n"
            "#!sd:b85:begin\n"
            "somecontent\n"
            ">Visible\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        # No decoded data since block was never closed
        assert result.data == {}

    def test_mixed_with_nomadnet_directives(self):
        """Standard NomadNet directives should coexist with Styrene directives."""
        source = (
            "#!c=60\n"
            "#!s.v=1\n"
            "#!s.type=status\n"
            "\n"
            ">Status\nOnline\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.page_type == "status"

    def test_directives_interspersed_with_content(self):
        """Directives can appear anywhere in the page, not just at the top."""
        source = (
            ">Title\n"
            "#!s.v=1\n"
            "Some text\n"
            "#!s.type=test\n"
            "More text\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.version == 1
        assert result.metadata.page_type == "test"

    def test_non_integer_version_ignored(self):
        """Non-integer version value should be silently ignored."""
        source = "#!s.v=abc\n#!s.type=test\n"
        result = parse_page_directives(source)
        assert result is not None
        # Version stays at default since "abc" was ignored
        assert result.metadata.version == PROTOCOL_VERSION

    def test_non_float_timestamp_ignored(self):
        """Non-float timestamp should be silently ignored."""
        source = "#!s.v=1\n#!s.ts=notanumber\n"
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.timestamp == 0.0

    def test_unknown_metadata_key_ignored(self):
        """Unknown s.* keys should be silently ignored."""
        source = "#!s.v=1\n#!s.unknown=whatever\n"
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.version == 1

    def test_unsupported_block_encoding_ignored(self):
        """Block with unsupported encoding should be ignored."""
        source = (
            "#!s.v=1\n"
            "#!sd:protobuf:begin\n"
            "data\n"
            "#!sd:protobuf:end\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.data == {}

    def test_realistic_fleet_page(self):
        """Full realistic fleet status page should parse correctly."""
        data = {
            "nodes": [
                {"name": "edge-03", "status": "active", "uptime_hours": 24},
                {"name": "edge-07", "status": "active", "uptime_hours": 72},
            ],
            "total": 2,
            "healthy": 2,
        }
        binary = msgpack.packb(data, use_bin_type=True)
        encoded = base64.b85encode(binary).decode("ascii")

        source = (
            "#!c=60\n"
            "#!s.v=1\n"
            "#!s.type=fleet\n"
            "#!s.caps=rpc,terminal,pages,fleet\n"
            "#!s.ts=1708000000.0\n"
            "#!s.refresh=status:30,fleet:60\n"
            "#!sd:b85:begin\n"
            f"{encoded}\n"
            "#!sd:b85:end\n"
            "\n"
            ">Fleet Status\n"
            "- edge-03: ACTIVE, 1d uptime\n"
            "- edge-07: ACTIVE, 3d uptime\n"
            "`[Refresh`:/page/styrene/fleet.mu]\n"
        )
        result = parse_page_directives(source)
        assert result is not None
        assert result.metadata.version == 1
        assert result.metadata.page_type == "fleet"
        assert result.metadata.capabilities == ["rpc", "terminal", "pages", "fleet"]
        assert result.metadata.timestamp == 1708000000.0
        assert result.metadata.refresh == {"status": 30, "fleet": 60}
        assert result.data == data
        assert result.encoding == "b85"
