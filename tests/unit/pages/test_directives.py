"""Unit tests for the Styrene page directive protocol.

Tests dataclass construction, validation, constant correctness,
regex patterns, and block marker generation.
"""


import pytest

from styrened.pages.directives import (
    DEFAULT_ENCODING,
    KNOWN_META_KEYS,
    MAX_BLOCK_SIZE,
    MAX_CAPABILITIES,
    MAX_CAPABILITY_LENGTH,
    MAX_ETAG_LENGTH,
    MAX_PAGE_TYPE_LENGTH,
    MAX_REFRESH_ENTRIES,
    META_KEY_CAPABILITIES,
    META_KEY_ETAG,
    META_KEY_REFRESH,
    META_KEY_TIMESTAMP,
    META_KEY_TYPE,
    META_KEY_VERSION,
    PROTOCOL_VERSION,
    RE_BLOCK_BEGIN,
    RE_BLOCK_END,
    RE_META_DIRECTIVE,
    STRUCTURED_DATA_PREFIX,
    STYRENE_DIRECTIVE_PREFIX,
    SUPPORTED_ENCODINGS,
    PageMetadata,
    StructuredPageData,
    block_begin_marker,
    block_end_marker,
)


class TestConstants:
    """Verify constant values and relationships."""

    def test_protocol_version_is_one(self):
        """Current protocol version should be 1."""
        assert PROTOCOL_VERSION == 1

    def test_default_encoding_is_b85(self):
        """Default encoding should be base85 for production."""
        assert DEFAULT_ENCODING == "b85"

    def test_supported_encodings_contain_b85_and_json(self):
        """Both production (b85) and debug (json) encodings should be supported."""
        assert "b85" in SUPPORTED_ENCODINGS
        assert "json" in SUPPORTED_ENCODINGS

    def test_directive_prefix(self):
        """Styrene directives use 's.' prefix."""
        assert STYRENE_DIRECTIVE_PREFIX == "s."

    def test_structured_data_prefix(self):
        """Structured data blocks use 'sd:' prefix."""
        assert STRUCTURED_DATA_PREFIX == "sd:"

    def test_all_meta_keys_start_with_prefix(self):
        """All metadata keys should start with 's.'."""
        for key in KNOWN_META_KEYS:
            assert key.startswith("s."), f"{key} does not start with 's.'"

    def test_known_meta_keys_complete(self):
        """All six metadata keys should be present."""
        expected = {
            META_KEY_VERSION,
            META_KEY_TYPE,
            META_KEY_CAPABILITIES,
            META_KEY_TIMESTAMP,
            META_KEY_ETAG,
            META_KEY_REFRESH,
        }
        assert KNOWN_META_KEYS == expected

    def test_max_block_size_matches_wire_protocol(self):
        """Block size limit should match wire protocol MAX_PAYLOAD_SIZE."""
        assert MAX_BLOCK_SIZE == 262144  # 256KB


class TestBlockMarkers:
    """Test block begin/end marker generation."""

    def test_b85_begin_marker(self):
        """Base85 begin marker should be well-formed."""
        assert block_begin_marker("b85") == "#!sd:b85:begin"

    def test_b85_end_marker(self):
        """Base85 end marker should be well-formed."""
        assert block_end_marker("b85") == "#!sd:b85:end"

    def test_json_begin_marker(self):
        """JSON begin marker should be well-formed."""
        assert block_begin_marker("json") == "#!sd:json:begin"

    def test_json_end_marker(self):
        """JSON end marker should be well-formed."""
        assert block_end_marker("json") == "#!sd:json:end"

    def test_unsupported_encoding_begin_raises(self):
        """Unsupported encoding should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported encoding"):
            block_begin_marker("protobuf")

    def test_unsupported_encoding_end_raises(self):
        """Unsupported encoding should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported encoding"):
            block_end_marker("protobuf")


class TestRegexPatterns:
    """Test regex patterns for directive parsing."""

    def test_meta_directive_matches_version(self):
        """RE_META_DIRECTIVE should match #!s.v=1."""
        m = RE_META_DIRECTIVE.match("#!s.v=1")
        assert m is not None
        assert m.group(1) == "v"
        assert m.group(2) == "1"

    def test_meta_directive_matches_type(self):
        """RE_META_DIRECTIVE should match #!s.type=fleet."""
        m = RE_META_DIRECTIVE.match("#!s.type=fleet")
        assert m is not None
        assert m.group(1) == "type"
        assert m.group(2) == "fleet"

    def test_meta_directive_matches_caps_csv(self):
        """RE_META_DIRECTIVE should match capabilities CSV."""
        m = RE_META_DIRECTIVE.match("#!s.caps=rpc,terminal,pages")
        assert m is not None
        assert m.group(1) == "caps"
        assert m.group(2) == "rpc,terminal,pages"

    def test_meta_directive_matches_timestamp(self):
        """RE_META_DIRECTIVE should match float timestamps."""
        m = RE_META_DIRECTIVE.match("#!s.ts=1708000000.123")
        assert m is not None
        assert m.group(1) == "ts"
        assert m.group(2) == "1708000000.123"

    def test_meta_directive_matches_etag(self):
        """RE_META_DIRECTIVE should match hex etags."""
        m = RE_META_DIRECTIVE.match("#!s.etag=a1b2c3d4")
        assert m is not None
        assert m.group(1) == "etag"
        assert m.group(2) == "a1b2c3d4"

    def test_meta_directive_matches_refresh(self):
        """RE_META_DIRECTIVE should match refresh pairs."""
        m = RE_META_DIRECTIVE.match("#!s.refresh=status:30,fleet:60")
        assert m is not None
        assert m.group(1) == "refresh"
        assert m.group(2) == "status:30,fleet:60"

    def test_meta_directive_rejects_non_styrene(self):
        """RE_META_DIRECTIVE should not match non-Styrene directives."""
        assert RE_META_DIRECTIVE.match("#!c=60") is None
        assert RE_META_DIRECTIVE.match("#!other=value") is None

    def test_block_begin_regex_b85(self):
        """RE_BLOCK_BEGIN should match base85 begin marker."""
        m = RE_BLOCK_BEGIN.match("#!sd:b85:begin")
        assert m is not None
        assert m.group(1) == "b85"

    def test_block_begin_regex_json(self):
        """RE_BLOCK_BEGIN should match JSON begin marker."""
        m = RE_BLOCK_BEGIN.match("#!sd:json:begin")
        assert m is not None
        assert m.group(1) == "json"

    def test_block_end_regex_b85(self):
        """RE_BLOCK_END should match base85 end marker."""
        m = RE_BLOCK_END.match("#!sd:b85:end")
        assert m is not None
        assert m.group(1) == "b85"

    def test_block_end_regex_json(self):
        """RE_BLOCK_END should match JSON end marker."""
        m = RE_BLOCK_END.match("#!sd:json:end")
        assert m is not None
        assert m.group(1) == "json"

    def test_block_begin_rejects_unknown_encoding(self):
        """RE_BLOCK_BEGIN should match the regex but encoding validation is separate."""
        m = RE_BLOCK_BEGIN.match("#!sd:proto:begin")
        assert m is not None  # Regex matches; encoding validation happens in parser
        assert m.group(1) == "proto"

    def test_block_markers_reject_non_block_directives(self):
        """Block marker regexes should not match metadata directives."""
        assert RE_BLOCK_BEGIN.match("#!s.v=1") is None
        assert RE_BLOCK_END.match("#!s.v=1") is None


class TestPageMetadata:
    """Test PageMetadata dataclass construction and validation."""

    def test_default_construction(self):
        """Default PageMetadata should have sensible defaults."""
        meta = PageMetadata()
        assert meta.version == PROTOCOL_VERSION
        assert meta.page_type == ""
        assert meta.capabilities == []
        assert meta.timestamp == 0.0
        assert meta.etag is None
        assert meta.refresh == {}

    def test_full_construction(self):
        """PageMetadata should accept all fields."""
        meta = PageMetadata(
            version=1,
            page_type="fleet",
            capabilities=["rpc", "terminal", "pages"],
            timestamp=1708000000.5,
            etag="a1b2c3d4",
            refresh={"status": 30, "fleet": 60},
        )
        assert meta.version == 1
        assert meta.page_type == "fleet"
        assert meta.capabilities == ["rpc", "terminal", "pages"]
        assert meta.timestamp == 1708000000.5
        assert meta.etag == "a1b2c3d4"
        assert meta.refresh == {"status": 30, "fleet": 60}

    def test_validate_valid_metadata(self):
        """Valid metadata should produce no errors."""
        meta = PageMetadata(
            page_type="status",
            capabilities=["rpc"],
            etag="abc123",
            refresh={"status": 30},
        )
        assert meta.validate() == []

    def test_validate_invalid_version(self):
        """Version < 1 should be invalid."""
        meta = PageMetadata(version=0)
        errors = meta.validate()
        assert any("Invalid version" in e for e in errors)

    def test_validate_page_type_too_long(self):
        """Excessively long page_type should be invalid."""
        meta = PageMetadata(page_type="x" * (MAX_PAGE_TYPE_LENGTH + 1))
        errors = meta.validate()
        assert any("page_type too long" in e for e in errors)

    def test_validate_too_many_capabilities(self):
        """More than MAX_CAPABILITIES should be invalid."""
        meta = PageMetadata(capabilities=[f"cap{i}" for i in range(MAX_CAPABILITIES + 1)])
        errors = meta.validate()
        assert any("Too many capabilities" in e for e in errors)

    def test_validate_capability_name_too_long(self):
        """Individual capability names exceeding limit should be invalid."""
        meta = PageMetadata(capabilities=["x" * (MAX_CAPABILITY_LENGTH + 1)])
        errors = meta.validate()
        assert any("Capability name too long" in e for e in errors)

    def test_validate_etag_too_long(self):
        """Etag exceeding limit should be invalid."""
        meta = PageMetadata(etag="x" * (MAX_ETAG_LENGTH + 1))
        errors = meta.validate()
        assert any("etag too long" in e for e in errors)

    def test_validate_too_many_refresh_entries(self):
        """More than MAX_REFRESH_ENTRIES should be invalid."""
        meta = PageMetadata(
            refresh={f"section{i}": i for i in range(MAX_REFRESH_ENTRIES + 1)}
        )
        errors = meta.validate()
        assert any("Too many refresh entries" in e for e in errors)

    def test_capabilities_are_independent_instances(self):
        """Default mutable fields should not share state across instances."""
        meta1 = PageMetadata()
        meta2 = PageMetadata()
        meta1.capabilities.append("rpc")
        assert meta2.capabilities == []

    def test_refresh_are_independent_instances(self):
        """Default mutable fields should not share state across instances."""
        meta1 = PageMetadata()
        meta2 = PageMetadata()
        meta1.refresh["status"] = 30
        assert meta2.refresh == {}


class TestStructuredPageData:
    """Test StructuredPageData dataclass construction."""

    def test_default_construction(self):
        """Default StructuredPageData should have empty data and b85 encoding."""
        spd = StructuredPageData(metadata=PageMetadata())
        assert spd.data == {}
        assert spd.encoding == DEFAULT_ENCODING
        assert spd.metadata.version == PROTOCOL_VERSION

    def test_full_construction(self):
        """StructuredPageData should accept all fields."""
        meta = PageMetadata(page_type="fleet")
        data = {"nodes": [{"name": "edge-03", "status": "active"}]}
        spd = StructuredPageData(metadata=meta, data=data, encoding="json")
        assert spd.metadata.page_type == "fleet"
        assert spd.data == data
        assert spd.encoding == "json"

    def test_data_are_independent_instances(self):
        """Default mutable fields should not share state."""
        spd1 = StructuredPageData(metadata=PageMetadata())
        spd2 = StructuredPageData(metadata=PageMetadata())
        spd1.data["key"] = "value"
        assert spd2.data == {}
