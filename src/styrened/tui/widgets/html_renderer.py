"""HTML-to-Rich rendering pipeline for TUI page browser.

Converts HTML content (from I2P eepsites, HTTPS pages) into Rich renderables
suitable for display in PageBrowserWidget's _PageBody static widget.

The pipeline:
    1. html2text converts HTML → Markdown (preserving links, headings, emphasis)
    2. Post-processing converts Markdown [text](url) links into
       [@click="navigate_link('url')"] Rich markup for internal TUI navigation
    3. Rich.Markdown renders the final markup

This reuses the existing link navigation infrastructure in PageBrowserWidget:
    _PageBody.action_navigate_link → _LinkClicked message → re-fetch through pipeline

Content-type detection is also provided for cases where the daemon doesn't
return an explicit content_type (NomadNet pages without HTTP headers).
"""
from __future__ import annotations

import re
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import RenderableType

# Link style matching micron_parser.py convention
_LINK_STYLE = "underline #5ac8fa"

# Regex to find markdown links: [text](url)
# Handles nested brackets in text, non-greedy url match
_MD_LINK_RE = re.compile(
    r"\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]"  # [text] with possible nested []
    r"\(([^)]+)\)"  # (url)
)

# Content-type detection patterns
_HTML_SIGNATURES = (b"<!doctype", b"<html", b"<head", b"<body")

# Definitive micron markers: any single occurrence → MICRON
_DEFINITIVE_MARKERS = ("#!c=", "#!md", "-=-")

# Ambiguous markers: require ≥2 distinct types in first 20 lines → MICRON
_AMBIGUOUS_MARKERS = (">", "`", "-=")


class ContentKind(Enum):
    """Detected content type for renderer dispatch."""

    MICRON = auto()
    HTML = auto()
    PLAIN = auto()


def detect_content_type(
    content: str,
    content_type_header: str | None = None,
) -> ContentKind:
    """Detect content type from HTTP header or content heuristic.

    Args:
        content: Page content string.
        content_type_header: HTTP Content-Type header value from daemon
            (e.g. "text/html", "text/html; charset=utf-8", "text/x-micron").
            When provided, this is authoritative — heuristic is not used.

    Returns:
        ContentKind indicating which renderer to use.
    """
    # Explicit content-type from daemon is authoritative
    if content_type_header:
        ct = content_type_header.lower().split(";")[0].strip()
        if ct == "text/html" or ct == "application/xhtml+xml":
            return ContentKind.HTML
        if ct == "text/x-micron" or ct == "text/plain":
            # text/plain could be micron — check heuristically
            if ct == "text/x-micron":
                return ContentKind.MICRON
            # Fall through to heuristic for text/plain
        elif ct.startswith("text/"):
            return ContentKind.PLAIN

    # Heuristic: check first 512 bytes for HTML signatures
    sample = content[:512].lower().encode("utf-8", errors="replace")
    for sig in _HTML_SIGNATURES:
        if sig in sample:
            return ContentKind.HTML

    # Heuristic: check for micron markers in first 20 lines
    lines = content.split("\n", 20)
    ambiguous_found: set[str] = set()
    for line in lines[:20]:
        stripped = line.strip()
        # Definitive markers → MICRON immediately
        for marker in _DEFINITIVE_MARKERS:
            if stripped.startswith(marker):
                return ContentKind.MICRON
        # Ambiguous markers: collect distinct types
        for marker in _AMBIGUOUS_MARKERS:
            if stripped.startswith(marker):
                ambiguous_found.add(marker)

    # Two or more distinct ambiguous marker types → MICRON
    if len(ambiguous_found) >= 2:
        return ContentKind.MICRON

    # Default: treat as plain text
    return ContentKind.PLAIN


def _postprocess_links(markdown: str) -> str:
    """Convert Markdown links to Rich @click markup for TUI navigation.

    Transforms ``[text](url)`` into:
        ``[@click="navigate_link('url')"][underline #5ac8fa]▸ text[/][/]``

    This plugs into PageBrowserWidget's existing link navigation:
    _PageBody handles action_navigate_link → posts _LinkClicked → re-fetch.

    Args:
        markdown: Markdown string from html2text.

    Returns:
        String with links converted to Rich @click markup.
    """

    def _replace_link(match: re.Match) -> str:
        text = match.group(1).strip()
        url = match.group(2).strip()
        # Escape for Rich markup safety
        url_safe = url.replace("\\", "\\\\").replace("'", "\\'")
        # Match micron_parser.py link format exactly
        return (
            f'[@click="navigate_link(\'{url_safe}\')"]'
            f"[{_LINK_STYLE}]▸ {text}[/{_LINK_STYLE}]"
            f"[/]"
        )

    return _MD_LINK_RE.sub(_replace_link, markdown)


def render_html_to_rich(html_content: str) -> "RenderableType":
    """Convert HTML to a Rich renderable for display in TUI.

    Pipeline: html2text → link post-processing → Rich Text

    If html2text is not installed, returns a message directing the user
    to install styrened[tui] or use the O key to open in browser.

    Args:
        html_content: Raw HTML string.

    Returns:
        Rich renderable (Text with markup) suitable for Static.update().
    """
    try:
        import html2text as _h2t
    except ImportError:
        from rich.text import Text

        return Text.from_markup(
            "[dim]HTML content detected but html2text is not installed.\n"
            "Install with: [bold]pip install styrened[tui][/bold]\n"
            "Or press [bold]O[/bold] to open in your browser.[/dim]"
        )

    converter = _h2t.HTML2Text()
    converter.body_width = 0  # Let Rich/Textual handle wrapping
    converter.ignore_images = True
    converter.protect_links = True
    converter.unicode_snob = True
    converter.skip_internal_links = False
    converter.ignore_emphasis = False
    converter.single_line_break = False

    # Convert HTML → Markdown
    markdown = converter.handle(html_content)

    # Post-process links for TUI navigation
    markup = _postprocess_links(markdown)

    # Render as Rich Text with markup
    from rich.text import Text

    return Text.from_markup(markup)
