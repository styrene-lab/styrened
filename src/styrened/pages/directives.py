"""Styrene page directive protocol — constants, dataclasses, and patterns.

Defines the directive vocabulary embedded in NomadNet micron pages via ``#!``
lines. All ``#!`` lines are invisible to standard NomadNet browsers (confirmed
by NomadNet's parser and styrened's micron_parser.py).

Directive categories:

**Single-line metadata** (``#!s.<key>=<value>``):
    ``#!s.v=<int>``           Protocol version (currently 1)
    ``#!s.type=<str>``        Page type (status, fleet, config, exec_result, ...)
    ``#!s.caps=<csv>``        Node capabilities (rpc,terminal,pages,fleet)
    ``#!s.ts=<unix_float>``   Generation timestamp
    ``#!s.etag=<hex>``        Conditional fetch token
    ``#!s.refresh=<csv>``     Section:interval pairs (status:30,fleet:60)

**Block data** (delimited by begin/end markers):
    ``#!sd:b85:begin`` / ``#!sd:b85:end``   base85-encoded msgpack (production)
    ``#!sd:json:begin`` / ``#!sd:json:end`` JSON (debug/development)
"""

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Protocol version
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: int = 1

# ---------------------------------------------------------------------------
# Directive prefixes
# ---------------------------------------------------------------------------

#: Prefix for all Styrene metadata directives.
STYRENE_DIRECTIVE_PREFIX: str = "s."

#: Prefix for structured data block markers.
STRUCTURED_DATA_PREFIX: str = "sd:"

# ---------------------------------------------------------------------------
# Metadata directive keys (after ``#!s.``)
# ---------------------------------------------------------------------------

META_KEY_VERSION: str = "s.v"
META_KEY_TYPE: str = "s.type"
META_KEY_CAPABILITIES: str = "s.caps"
META_KEY_TIMESTAMP: str = "s.ts"
META_KEY_ETAG: str = "s.etag"
META_KEY_REFRESH: str = "s.refresh"

#: Set of all recognised metadata keys for fast lookup.
KNOWN_META_KEYS: frozenset[str] = frozenset(
    {
        META_KEY_VERSION,
        META_KEY_TYPE,
        META_KEY_CAPABILITIES,
        META_KEY_TIMESTAMP,
        META_KEY_ETAG,
        META_KEY_REFRESH,
    }
)

# ---------------------------------------------------------------------------
# Structured data block markers
# ---------------------------------------------------------------------------

#: Supported block encodings.
SUPPORTED_ENCODINGS: frozenset[str] = frozenset({"b85", "json"})

#: Default encoding for production use.
DEFAULT_ENCODING: str = "b85"


def block_begin_marker(encoding: str) -> str:
    """Return the begin marker for a structured data block.

    Args:
        encoding: Encoding name (``"b85"`` or ``"json"``).

    Returns:
        Marker string, e.g. ``"#!sd:b85:begin"``.

    Raises:
        ValueError: If encoding is not supported.
    """
    if encoding not in SUPPORTED_ENCODINGS:
        raise ValueError(
            f"Unsupported encoding {encoding!r}, expected one of {sorted(SUPPORTED_ENCODINGS)}"
        )
    return f"#!sd:{encoding}:begin"


def block_end_marker(encoding: str) -> str:
    """Return the end marker for a structured data block.

    Args:
        encoding: Encoding name (``"b85"`` or ``"json"``).

    Returns:
        Marker string, e.g. ``"#!sd:b85:end"``.

    Raises:
        ValueError: If encoding is not supported.
    """
    if encoding not in SUPPORTED_ENCODINGS:
        raise ValueError(
            f"Unsupported encoding {encoding!r}, expected one of {sorted(SUPPORTED_ENCODINGS)}"
        )
    return f"#!sd:{encoding}:end"


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

#: Matches any ``#!s.<key>=<value>`` directive line (stripped).
RE_META_DIRECTIVE = re.compile(r"^#!s\.(\w+)=(.*)$")

#: Matches a structured-data block begin marker.
RE_BLOCK_BEGIN = re.compile(r"^#!sd:(\w+):begin$")

#: Matches a structured-data block end marker.
RE_BLOCK_END = re.compile(r"^#!sd:(\w+):end$")

# ---------------------------------------------------------------------------
# Validation limits
# ---------------------------------------------------------------------------

#: Maximum encoded block size (256 KB, matching wire protocol limits).
MAX_BLOCK_SIZE: int = 262144

#: Maximum number of metadata directives per page.
MAX_META_DIRECTIVES: int = 64

#: Maximum page type string length.
MAX_PAGE_TYPE_LENGTH: int = 64

#: Maximum capability name length.
MAX_CAPABILITY_LENGTH: int = 32

#: Maximum number of capabilities.
MAX_CAPABILITIES: int = 32

#: Maximum number of refresh entries.
MAX_REFRESH_ENTRIES: int = 32

#: Maximum etag length.
MAX_ETAG_LENGTH: int = 128

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PageMetadata:
    """Metadata extracted from ``#!s.*`` directives in a micron page.

    Attributes:
        version: Protocol version (currently 1).
        page_type: Page type identifier (e.g. ``"status"``, ``"fleet"``).
        capabilities: Node capabilities advertised in this page.
        timestamp: Unix timestamp of page generation (0.0 if absent).
        etag: Conditional fetch token for cache validation.
        refresh: Mapping of section name to refresh interval in seconds.
    """

    version: int = PROTOCOL_VERSION
    page_type: str = ""
    capabilities: list[str] = field(default_factory=list)
    timestamp: float = 0.0
    etag: str | None = None
    refresh: dict[str, int] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return a list of validation error messages (empty if valid)."""
        errors: list[str] = []
        if self.version < 1:
            errors.append(f"Invalid version: {self.version}")
        if len(self.page_type) > MAX_PAGE_TYPE_LENGTH:
            errors.append(
                f"page_type too long: {len(self.page_type)} > {MAX_PAGE_TYPE_LENGTH}"
            )
        if len(self.capabilities) > MAX_CAPABILITIES:
            errors.append(
                f"Too many capabilities: {len(self.capabilities)} > {MAX_CAPABILITIES}"
            )
        for cap in self.capabilities:
            if len(cap) > MAX_CAPABILITY_LENGTH:
                errors.append(f"Capability name too long: {cap!r}")
        if self.etag is not None and len(self.etag) > MAX_ETAG_LENGTH:
            errors.append(f"etag too long: {len(self.etag)} > {MAX_ETAG_LENGTH}")
        if len(self.refresh) > MAX_REFRESH_ENTRIES:
            errors.append(
                f"Too many refresh entries: {len(self.refresh)} > {MAX_REFRESH_ENTRIES}"
            )
        return errors


@dataclass
class StructuredPageData:
    """Parsed result containing both metadata and the decoded data payload.

    Attributes:
        metadata: Extracted page metadata from ``#!s.*`` directives.
        data: Decoded structured payload from the ``#!sd:*`` block.
        encoding: Encoding used for the block (``"b85"`` or ``"json"``).
    """

    metadata: PageMetadata
    data: dict[str, Any] = field(default_factory=dict)
    encoding: str = DEFAULT_ENCODING
