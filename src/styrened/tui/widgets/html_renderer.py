"""HTML-to-Rich rendering pipeline for TUI page browser.

Converts HTML content (from I2P eepsites, HTTPS pages) into Rich renderables
suitable for display in PageBrowserWidget's _PageBody static widget.

The pipeline:
    1. html2text converts HTML → Markdown (preserving links, headings, emphasis)
    2. _escape_rich_markup() escapes ``[`` and ``]`` in the html2text output so
       that any Rich markup tokens embedded in the page content (e.g. ``[@click]``
       or ``[bold red]``) are treated as literal text rather than as markup.
    3. Post-processing converts Markdown ``[text](url)`` links into
       ``[@click="navigate_link('url')"]`` Rich markup for internal TUI navigation.
       Image syntax ``![alt](url)`` and empty-label links ``[](url)`` are skipped.
    4. Rich Text.from_markup renders the final string.

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
# Negative lookbehind (?<!!) rejects image syntax ![alt](url).
# Requires a non-empty label (text group cannot be empty).
_MD_LINK_RE = re.compile(
    r"(?<!!)"                                      # reject image syntax  ![alt](url)
    r"\[([^\[\]]+(?:\[[^\[\]]*\][^\[\]]*)*)\]"     # [text] — non-empty label
    r"\(([^)]+)\)"                                 # (url)
)

# Content-type detection patterns
_HTML_SIGNATURES = (b"<!doctype", b"<html", b"<head", b"<body")

# Definitive micron markers: any single occurrence → MICRON
_DEFINITIVE_MARKERS = ("#!c=", "#!md", "-=-")

# Ambiguous markers: require ≥2 distinct types in first 20 lines → MICRON
# Note: "-=" is intentionally excluded — its superset "-=-" is a definitive marker,
# and a bare "-=" is not a valid standalone micron syntax element.
_AMBIGUOUS_MARKERS = (">", "`")


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
        # Micron requires markers at column 0 — do NOT strip leading whitespace.
        # Indented content (e.g. "   #!c=3600") must not trigger false positives.
        for marker in _DEFINITIVE_MARKERS:
            if line.startswith(marker):
                return ContentKind.MICRON
        # Ambiguous markers: collect distinct types (also column-0 only)
        for marker in _AMBIGUOUS_MARKERS:
            if line.startswith(marker):
                ambiguous_found.add(marker)

    # Two or more distinct ambiguous marker types → MICRON
    if len(ambiguous_found) >= 2:
        return ContentKind.MICRON

    # Default: treat as plain text
    return ContentKind.PLAIN


def _escape_rich_markup(text: str) -> str:
    """Escape ``[`` in plain text so Rich does not interpret it as markup.

    Used internally by ``render_html_to_rich()`` — applied to non-link spans only
    via ``_postprocess_links()``'s split-and-escape strategy.  Exposed here for
    unit testing.

    Rich's convention: ``\\[`` renders as a literal ``[`` character.

    Args:
        text: Raw text fragment that must not contain Rich markup.

    Returns:
        String with all ``[`` → ``\\[``.
    """
    return text.replace("[", "\\[")


def _postprocess_links(markdown: str) -> str:
    """Convert Markdown links to Rich @click markup for TUI navigation.

    Scans *markdown* for ``[text](url)`` patterns.  For each match:

    * Image syntax ``![alt](url)`` is skipped (negative lookbehind in ``_MD_LINK_RE``).
    * Empty-label links ``[](url)`` are rejected by ``_MD_LINK_RE`` which requires
      ``[^\\[\\]]+`` (one or more non-bracket characters) in the label group.
    * Real links are converted to::

          [@click="navigate_link('url')"][underline #5ac8fa]▸ text[/][/]

    All *non-link* spans between matches are passed through
    ``_escape_rich_markup()`` so that any stray ``[…]`` tokens in the page
    content are rendered as literal characters rather than Rich markup.

    This plugs into PageBrowserWidget's existing link navigation:
    _PageBody handles action_navigate_link → posts _LinkClicked → re-fetch.

    Args:
        markdown: Raw Markdown string from html2text.

    Returns:
        String with real Markdown links converted to Rich @click markup and
        all other content safely escaped.
    """
    parts: list[str] = []
    last_end = 0

    for match in _MD_LINK_RE.finditer(markdown):
        # Escape the literal text between the previous match and this one
        parts.append(_escape_rich_markup(markdown[last_end:match.start()]))
        last_end = match.end()

        text = match.group(1).strip()
        url = match.group(2).strip()
        # Strip angle brackets added by html2text's protect_links=True.
        # html2text wraps URLs as <https://example.com> to prevent breakage;
        # _MD_LINK_RE captures them verbatim via [^)]+ — strip before use.
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        # Escape URL for Rich markup safety: backslash, single-quote, double-quote.
        # An unescaped `"` would terminate the [@click="..."] attribute early.
        url_safe = url.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
        # Match micron_parser.py link format exactly
        parts.append(
            f'[@click="navigate_link(\'{url_safe}\')"]'
            f"[{_LINK_STYLE}]▸ {text}[/{_LINK_STYLE}]"
            f"[/]"
        )

    # Escape any trailing literal text after the last match
    parts.append(_escape_rich_markup(markdown[last_end:]))
    return "".join(parts)


def render_html_to_rich(html_content: str) -> RenderableType:
    """Convert HTML to a Rich renderable for display in TUI.

    Pipeline: html2text → escape Rich markup → link post-processing → Rich Text

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

    # Post-process links for TUI navigation.
    # _postprocess_links() escapes all non-link spans via _escape_rich_markup()
    # before injecting Rich markup, preventing injection attacks from page content.
    markup = _postprocess_links(markdown)

    # Render as Rich Text with markup
    from rich.text import Text

    return Text.from_markup(markup)
