"""Generate dual-layer NomadNet page responses with embedded Styrene directives.

Produces a page string with:
1. NomadNet cache directive (``#!c=<ttl>``) if specified
2. Styrene metadata directives (``#!s.*``)
3. Structured data block (``#!sd:<enc>:begin`` … ``#!sd:<enc>:end``)
4. Blank separator line
5. Micron markup content (visible to all NomadNet browsers)

The result is a valid NomadNet page that standard browsers render normally
(all ``#!`` lines are invisible), while Styrene-aware clients can extract
the embedded structured data via :func:`~styrened.pages.parser.parse_page_directives`.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from styrened.pages.directives import (
    DEFAULT_ENCODING,
    PROTOCOL_VERSION,
    SUPPORTED_ENCODINGS,
    block_begin_marker,
    block_end_marker,
)

logger = logging.getLogger(__name__)


def _encode_data_block(data: dict[str, Any], encoding: str) -> str:
    """Encode structured data as a directive block.

    Args:
        data: Dict payload to encode.
        encoding: ``"b85"`` or ``"json"``.

    Returns:
        Multi-line string with begin/end markers and encoded content.

    Raises:
        ValueError: If encoding is unsupported.
    """
    if encoding not in SUPPORTED_ENCODINGS:
        raise ValueError(
            f"Unsupported encoding {encoding!r}, expected one of {sorted(SUPPORTED_ENCODINGS)}"
        )

    begin = block_begin_marker(encoding)
    end = block_end_marker(encoding)

    if encoding == "json":
        encoded = json.dumps(data, separators=(",", ":"), sort_keys=True)
        return f"{begin}\n{encoded}\n{end}"

    # b85: msgpack → base85
    from styrened.models.styrene_wire import encode_payload

    binary = encode_payload(data)
    encoded = base64.b85encode(binary).decode("ascii")
    return f"{begin}\n{encoded}\n{end}"


def build_page(
    micron: str,
    data: dict[str, Any],
    page_type: str,
    encoding: str = DEFAULT_ENCODING,
    capabilities: list[str] | None = None,
    cache_ttl: int | None = None,
    timestamp: float | None = None,
    etag: str | None = None,
    refresh: dict[str, int] | None = None,
) -> str:
    """Build a dual-layer NomadNet page with embedded Styrene directives.

    Standard NomadNet browsers see only the micron content; Styrene clients
    additionally extract metadata and structured data.

    Args:
        micron: Visible micron markup content.
        data: Structured payload dict to embed.
        page_type: Page type identifier (e.g. ``"status"``, ``"fleet"``).
        encoding: Block encoding — ``"b85"`` (default) or ``"json"``.
        capabilities: Node capabilities to advertise (e.g. ``["rpc", "terminal"]``).
        cache_ttl: NomadNet cache TTL in seconds (``#!c=<N>``).
        timestamp: Generation timestamp (defaults to ``time.time()``).
        etag: Conditional fetch token.
        refresh: Section refresh intervals (e.g. ``{"status": 30}``).

    Returns:
        Complete page string ready to serve.
    """
    parts: list[str] = []

    # NomadNet cache directive (standard, not Styrene-specific)
    if cache_ttl is not None:
        parts.append(f"#!c={cache_ttl}")

    # Styrene metadata directives
    parts.append(f"#!s.v={PROTOCOL_VERSION}")
    parts.append(f"#!s.type={page_type}")

    if capabilities:
        parts.append(f"#!s.caps={','.join(capabilities)}")

    ts = timestamp if timestamp is not None else time.time()
    parts.append(f"#!s.ts={ts}")

    if etag is not None:
        parts.append(f"#!s.etag={etag}")

    if refresh:
        pairs = ",".join(f"{k}:{v}" for k, v in refresh.items())
        parts.append(f"#!s.refresh={pairs}")

    # Structured data block
    if data:
        parts.append(_encode_data_block(data, encoding))

    # Blank line separating directives from visible content
    parts.append("")

    # Micron content
    parts.append(micron)

    return "\n".join(parts)
