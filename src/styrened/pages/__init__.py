"""Styrene NomadNet page extension protocol.

Embeds structured data and metadata directives into NomadNet micron pages
using a dual-layer pattern: standard NomadNet browsers render the micron
markup while Styrene-aware clients additionally extract embedded structured
data from invisible ``#!`` directive lines.

Modules:
    directives: Constants, dataclasses, and patterns for the directive protocol.
    parser: Extract PageMetadata and structured data from raw micron.
    builder: Generate dual-layer page responses with embedded directives.
"""
from __future__ import annotations

