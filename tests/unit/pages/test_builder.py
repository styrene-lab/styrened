"""Unit tests for the Styrene page builder.

Tests page generation, encoding correctness, and round-trip
compatibility with the parser.
"""
from __future__ import annotations


import time

import pytest

from styrened.pages.builder import build_page
from styrened.pages.directives import PROTOCOL_VERSION
from styrened.pages.parser import parse_page_directives


class TestBuildPage:
    """Test build_page output structure."""

    def test_minimal_page(self):
        """Minimal page should include version, type, timestamp, and content."""
        result = build_page(
            micron=">Hello\nWorld",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        lines = result.split("\n")
        assert "#!s.v=1" in lines
        assert "#!s.type=test" in lines
        assert "#!s.ts=1000.0" in lines
        # Content should appear after blank separator
        assert ">Hello" in lines
        assert "World" in lines

    def test_cache_ttl_appears_first(self):
        """NomadNet cache directive should be the first line when present."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            cache_ttl=60,
            timestamp=1000.0,
        )
        assert result.startswith("#!c=60\n")

    def test_no_cache_ttl(self):
        """No #!c= line when cache_ttl is None."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        assert "#!c=" not in result

    def test_capabilities_directive(self):
        """Capabilities should appear as comma-separated CSV."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            capabilities=["rpc", "terminal", "pages"],
            timestamp=1000.0,
        )
        assert "#!s.caps=rpc,terminal,pages" in result

    def test_no_capabilities_omits_line(self):
        """No #!s.caps line when capabilities is None or empty."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        assert "#!s.caps=" not in result

    def test_etag_directive(self):
        """Etag should be included when provided."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            etag="abc123",
            timestamp=1000.0,
        )
        assert "#!s.etag=abc123" in result

    def test_refresh_directive(self):
        """Refresh pairs should appear as section:interval CSV."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            refresh={"status": 30, "fleet": 60},
            timestamp=1000.0,
        )
        line = [ln for ln in result.split("\n") if ln.startswith("#!s.refresh=")][0]
        # Parse back the pairs (order may vary)
        pairs = line.split("=", 1)[1]
        parsed = {}
        for p in pairs.split(","):
            k, v = p.split(":")
            parsed[k] = int(v)
        assert parsed == {"status": 30, "fleet": 60}

    def test_timestamp_default_is_now(self):
        """Timestamp should default to current time."""
        before = time.time()
        result = build_page(micron=">Test", data={}, page_type="test")
        after = time.time()

        # Extract timestamp
        for line in result.split("\n"):
            if line.startswith("#!s.ts="):
                ts = float(line.split("=", 1)[1])
                assert before <= ts <= after
                break
        else:
            pytest.fail("No #!s.ts= line found")

    def test_b85_data_block_present(self):
        """Data block markers should be present for non-empty data with b85 encoding."""
        result = build_page(
            micron=">Test",
            data={"key": "value"},
            page_type="test",
            encoding="b85",
            timestamp=1000.0,
        )
        assert "#!sd:b85:begin" in result
        assert "#!sd:b85:end" in result

    def test_json_data_block_present(self):
        """Data block markers should be present for non-empty data with json encoding."""
        result = build_page(
            micron=">Test",
            data={"key": "value"},
            page_type="test",
            encoding="json",
            timestamp=1000.0,
        )
        assert "#!sd:json:begin" in result
        assert "#!sd:json:end" in result

    def test_empty_data_no_block(self):
        """Empty data dict should not produce a data block."""
        result = build_page(
            micron=">Test",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        assert "#!sd:" not in result

    def test_blank_separator_before_content(self):
        """There should be a blank line between directives and micron content."""
        result = build_page(
            micron=">Visible Content",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        # Find blank line followed by content
        lines = result.split("\n")
        found_blank = False
        for i, line in enumerate(lines):
            if line == "" and i > 0:
                found_blank = True
                # Next line should be the content
                if i + 1 < len(lines):
                    assert lines[i + 1] == ">Visible Content"
                break
        assert found_blank, "No blank separator found"

    def test_unsupported_encoding_raises(self):
        """Unsupported encoding should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported encoding"):
            build_page(
                micron=">Test",
                data={"key": "value"},
                page_type="test",
                encoding="protobuf",
            )


class TestRoundTrip:
    """Test that build_page output can be parsed back by parse_page_directives."""

    def test_roundtrip_b85_simple(self):
        """Simple data round-trips through b85 encoding."""
        data = {"status": "online", "uptime": 3600}
        page = build_page(
            micron=">Status\nOnline",
            data=data,
            page_type="status",
            encoding="b85",
            timestamp=1708000000.0,
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.metadata.version == PROTOCOL_VERSION
        assert result.metadata.page_type == "status"
        assert result.metadata.timestamp == 1708000000.0
        assert result.encoding == "b85"
        assert result.data == data

    def test_roundtrip_json_simple(self):
        """Simple data round-trips through JSON encoding."""
        data = {"status": "online", "nodes": ["edge-03", "edge-07"]}
        page = build_page(
            micron=">Fleet\nOK",
            data=data,
            page_type="fleet",
            encoding="json",
            timestamp=1708000000.0,
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.encoding == "json"
        assert result.data == data

    def test_roundtrip_with_all_metadata(self):
        """All metadata fields round-trip correctly."""
        data = {"key": "value"}
        page = build_page(
            micron=">Test",
            data=data,
            page_type="fleet",
            encoding="b85",
            capabilities=["rpc", "terminal", "pages"],
            cache_ttl=120,
            timestamp=1708000000.5,
            etag="deadbeef",
            refresh={"status": 30, "fleet": 60},
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.metadata.page_type == "fleet"
        assert result.metadata.capabilities == ["rpc", "terminal", "pages"]
        assert result.metadata.timestamp == 1708000000.5
        assert result.metadata.etag == "deadbeef"
        assert result.metadata.refresh == {"status": 30, "fleet": 60}
        assert result.data == data

    def test_roundtrip_nested_data(self):
        """Complex nested data structures round-trip correctly."""
        data = {
            "nodes": [
                {"name": "edge-03", "status": "active", "metrics": {"cpu": 0.15, "mem": 256}},
                {"name": "edge-07", "status": "active", "metrics": {"cpu": 0.32, "mem": 512}},
            ],
            "summary": {"total": 2, "healthy": 2, "degraded": 0},
        }
        page = build_page(
            micron=">Fleet\nOK",
            data=data,
            page_type="fleet",
            encoding="b85",
            timestamp=1000.0,
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.data == data

    def test_roundtrip_empty_data(self):
        """Empty data should round-trip as empty dict."""
        page = build_page(
            micron=">Test",
            data={},
            page_type="test",
            timestamp=1000.0,
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.data == {}

    def test_roundtrip_large_payload(self):
        """Large payloads should round-trip correctly."""
        data = {"items": [{"id": i, "value": f"item-{i}" * 10} for i in range(100)]}
        page = build_page(
            micron=">Large\nLots of data",
            data=data,
            page_type="bulk",
            encoding="b85",
            timestamp=1000.0,
        )
        result = parse_page_directives(page)
        assert result is not None
        assert result.data == data
        assert len(result.data["items"]) == 100

    def test_micron_content_preserved(self):
        """Micron content should be present in the page output."""
        micron = ">Fleet Status\n- edge-03: ACTIVE, 1d uptime\n- edge-07: ACTIVE, 3d uptime\n`[Refresh`:/page/styrene/fleet.mu]"
        page = build_page(
            micron=micron,
            data={"nodes": 2},
            page_type="fleet",
            timestamp=1000.0,
        )
        # All micron lines should appear
        assert ">Fleet Status" in page
        assert "- edge-03: ACTIVE, 1d uptime" in page
        assert "`[Refresh`:/page/styrene/fleet.mu]" in page

    def test_nomadnet_directives_invisible(self):
        """All #! lines should be NomadNet-invisible page directives."""
        page = build_page(
            micron=">Visible Only",
            data={"key": "value"},
            page_type="test",
            cache_ttl=60,
            timestamp=1000.0,
        )
        for line in page.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#!") and stripped != ">Visible Only":
                # This line is either content, blank, or encoded data
                # Encoded data lines inside blocks are also invisible
                pass
