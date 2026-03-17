"""Extract Styrene directives and structured data from micron page source.

Scans raw micron markup for ``#!s.*`` metadata directives and
``#!sd:<enc>:begin``/``end`` data blocks, returning a
:class:`~styrened.pages.directives.StructuredPageData` when Styrene
directives are present, or ``None`` for plain NomadNet pages.

The parser reuses :func:`~styrened.models.styrene_wire.decode_payload`
for hardened msgpack deserialization (max lengths, strict keys).
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from styrened.pages.directives import (
    MAX_BLOCK_SIZE,
    MAX_META_DIRECTIVES,
    RE_BLOCK_BEGIN,
    RE_BLOCK_END,
    RE_META_DIRECTIVE,
    SUPPORTED_ENCODINGS,
    PageMetadata,
    StructuredPageData,
)

logger = logging.getLogger(__name__)


def _parse_capabilities(value: str) -> list[str]:
    """Parse comma-separated capabilities string."""
    if not value:
        return []
    return [c.strip() for c in value.split(",") if c.strip()]


def _parse_refresh(value: str) -> dict[str, int]:
    """Parse comma-separated section:interval pairs.

    Example: ``"status:30,fleet:60"`` → ``{"status": 30, "fleet": 60}``
    """
    result: dict[str, int] = {}
    if not value:
        return result
    for pair in value.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        section, _, interval_str = pair.partition(":")
        section = section.strip()
        interval_str = interval_str.strip()
        if not section or not interval_str:
            continue
        try:
            result[section] = int(interval_str)
        except ValueError:
            logger.debug("Ignoring malformed refresh pair: %r", pair)
    return result


def _decode_block(lines: list[str], encoding: str) -> dict[str, Any] | None:
    """Decode accumulated block lines into a dict.

    Args:
        lines: Raw lines between begin/end markers (markers excluded).
        encoding: ``"b85"`` or ``"json"``.

    Returns:
        Decoded dict, or ``None`` on decode failure.
    """
    raw = "".join(lines)
    if not raw:
        return None

    if encoding == "json":
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                logger.warning("Structured data JSON root is not a dict, got %s", type(result).__name__)
                return None
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to decode JSON structured data: %s", exc)
            return None

    if encoding == "b85":
        try:
            binary = base64.b85decode(raw)
        except Exception as exc:
            logger.warning("Failed to base85-decode structured data: %s", exc)
            return None

        if len(binary) > MAX_BLOCK_SIZE:
            logger.warning(
                "Decoded block size %d exceeds limit %d", len(binary), MAX_BLOCK_SIZE
            )
            return None

        try:
            from styrened.models.styrene_wire import decode_payload

            result = decode_payload(binary)
            if not isinstance(result, dict):
                logger.warning(
                    "Structured data msgpack root is not a dict, got %s",
                    type(result).__name__,
                )
                return None
            return result
        except Exception as exc:
            logger.warning("Failed to msgpack-decode structured data: %s", exc)
            return None

    logger.warning("Unsupported block encoding: %s", encoding)
    return None


def parse_page_directives(source: str) -> StructuredPageData | None:
    """Extract Styrene metadata and structured data from micron source.

    Scans the page line-by-line for:

    1. ``#!s.<key>=<value>`` metadata directives → :class:`PageMetadata`
    2. ``#!sd:<enc>:begin`` … ``#!sd:<enc>:end`` data block → decoded dict

    Lines that are not ``#!`` directives are ignored (they are the visible
    micron content rendered by NomadNet browsers).

    Args:
        source: Raw micron page source (UTF-8 string).

    Returns:
        :class:`StructuredPageData` if any Styrene directives were found,
        ``None`` otherwise.
    """
    if not source:
        return None

    metadata = PageMetadata()
    found_any_directive = False
    meta_count = 0

    # Block accumulation state
    in_block = False
    block_encoding: str = ""
    block_lines: list[str] = []
    decoded_data: dict[str, Any] | None = None
    data_encoding: str = "b85"

    for line in source.split("\n"):
        stripped = line.strip()

        # Not a directive line — skip
        if not stripped.startswith("#!"):
            if in_block:
                # Inside a data block, accumulate raw content lines
                block_lines.append(line)
            continue

        # --- Block end marker ---
        m_end = RE_BLOCK_END.match(stripped)
        if m_end and in_block and m_end.group(1) == block_encoding:
            decoded_data = _decode_block(block_lines, block_encoding)
            data_encoding = block_encoding
            in_block = False
            block_lines = []
            block_encoding = ""
            found_any_directive = True
            continue

        # Inside a block, directive lines are still block content
        if in_block:
            block_lines.append(line)
            continue

        # --- Block begin marker ---
        m_begin = RE_BLOCK_BEGIN.match(stripped)
        if m_begin:
            enc = m_begin.group(1)
            if enc in SUPPORTED_ENCODINGS:
                in_block = True
                block_encoding = enc
                block_lines = []
                found_any_directive = True
            else:
                logger.debug("Ignoring unsupported block encoding: %s", enc)
            continue

        # --- Metadata directive ---
        m_meta = RE_META_DIRECTIVE.match(stripped)
        if m_meta:
            meta_count += 1
            if meta_count > MAX_META_DIRECTIVES:
                logger.warning("Exceeded max meta directives (%d), ignoring rest", MAX_META_DIRECTIVES)
                continue

            key_suffix = m_meta.group(1)  # e.g. "v", "type", "caps"
            value = m_meta.group(2)
            found_any_directive = True

            if key_suffix == "v":
                try:
                    metadata.version = int(value)
                except ValueError:
                    logger.debug("Ignoring non-integer version: %r", value)
            elif key_suffix == "type":
                metadata.page_type = value
            elif key_suffix == "caps":
                metadata.capabilities = _parse_capabilities(value)
            elif key_suffix == "ts":
                try:
                    metadata.timestamp = float(value)
                except ValueError:
                    logger.debug("Ignoring non-float timestamp: %r", value)
            elif key_suffix == "etag":
                metadata.etag = value
            elif key_suffix == "refresh":
                metadata.refresh = _parse_refresh(value)
            else:
                logger.debug("Ignoring unknown metadata key suffix: %r", key_suffix)

    if not found_any_directive:
        return None

    return StructuredPageData(
        metadata=metadata,
        data=decoded_data if decoded_data is not None else {},
        encoding=data_encoding,
    )
