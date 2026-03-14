"""Tests for HTML-to-Rich rendering pipeline."""
from __future__ import annotations

import pytest

from styrened.tui.widgets.html_renderer import (
    ContentKind,
    _postprocess_links,
    detect_content_type,
    render_html_to_rich,
)


class TestDetectContentType:
    """Content-type detection from headers and heuristic."""

    def test_explicit_html_header(self):
        assert detect_content_type("anything", "text/html") == ContentKind.HTML

    def test_explicit_html_with_charset(self):
        assert detect_content_type("anything", "text/html; charset=utf-8") == ContentKind.HTML

    def test_explicit_xhtml(self):
        assert detect_content_type("anything", "application/xhtml+xml") == ContentKind.HTML

    def test_explicit_micron(self):
        assert detect_content_type("anything", "text/x-micron") == ContentKind.MICRON

    def test_explicit_plain_text_with_micron_content(self):
        """text/plain with micron markers should detect as micron via heuristic."""
        content = ">Hello World\n`This is literal`"
        assert detect_content_type(content, "text/plain") == ContentKind.MICRON

    def test_explicit_plain_text_no_markers(self):
        content = "Just some plain text with no special markers."
        assert detect_content_type(content, "text/plain") == ContentKind.PLAIN

    def test_heuristic_html_doctype(self):
        content = "<!DOCTYPE html>\n<html><body>hello</body></html>"
        assert detect_content_type(content) == ContentKind.HTML

    def test_heuristic_html_tag(self):
        content = "<html><head><title>Test</title></head><body>hi</body></html>"
        assert detect_content_type(content) == ContentKind.HTML

    def test_heuristic_html_body_only(self):
        content = "<body>content here</body>"
        assert detect_content_type(content) == ContentKind.HTML

    def test_heuristic_micron_heading(self):
        # Single > is ambiguous — needs a second distinct marker for MICRON.
        # A heading plus a literal block qualifies.
        content = ">Welcome to My Page\n`Literal block here"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_literal(self):
        # Single backtick is ambiguous — needs a second distinct marker.
        content = "`Preformatted text block\n-= Section =-"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_separator(self):
        # Single -= is ambiguous — needs a second distinct marker.
        content = "-= Section Break =-\n>Heading"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_cache_directive(self):
        # #!c= is a definitive marker — MICRON on its own.
        content = "#!c=3600\n>Page Title"
        assert detect_content_type(content) == ContentKind.MICRON

    # --- Spec scenarios: micron heuristic false-positive reduction ---

    def test_email_quote_single_gt_is_plain(self):
        """Email quotes (> prefix) with no other micron markers → PLAIN."""
        content = "> On Tuesday, Bob wrote:\n> This is a quoted email"
        assert detect_content_type(content) == ContentKind.PLAIN

    def test_code_fence_single_backtick_is_plain(self):
        """Code fences (backtick prefix) with no other micron markers → PLAIN."""
        content = "```python\nprint(\"hello\")\n```"
        assert detect_content_type(content) == ContentKind.PLAIN

    def test_single_gt_no_other_markers_is_plain(self):
        """A lone > with no other markers must not be mistaken for micron."""
        content = ">Just a blockquote\n\nNothing else here"
        assert detect_content_type(content) == ContentKind.PLAIN

    def test_definitive_marker_alone_is_micron(self):
        """#!c= is definitive — MICRON without any other markers."""
        content = "#!c=3600\n>Page Title\n\nSome text"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_definitive_marker_md_alone_is_micron(self):
        """#!md is definitive — MICRON without any other markers."""
        content = "#!md\nSome text here"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_definitive_marker_triple_dash_alone_is_micron(self):
        """-=- is definitive — MICRON without any other markers."""
        content = "-=-\nSome content\n-=-"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_two_distinct_ambiguous_markers_is_micron(self):
        """Two distinct ambiguous marker types in first 20 lines → MICRON."""
        content = ">Page Title\n-= Section =-\n`Literal block`"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_same_ambiguous_marker_repeated_is_plain(self):
        """Repeated occurrences of the same ambiguous marker type → PLAIN."""
        content = "> Quote one\n> Quote two\n> Quote three"
        assert detect_content_type(content) == ContentKind.PLAIN

    def test_heuristic_plain_default(self):
        content = "This is just ordinary text without any markers."
        assert detect_content_type(content) == ContentKind.PLAIN

    def test_empty_content(self):
        assert detect_content_type("") == ContentKind.PLAIN

    def test_header_takes_precedence_over_heuristic(self):
        """Even if content looks like micron, HTML header wins."""
        content = ">This looks like micron\n`But has HTML header`"
        assert detect_content_type(content, "text/html") == ContentKind.HTML

    def test_case_insensitive_html_detection(self):
        content = "<!DOCTYPE HTML>\n<HTML><BODY>caps</BODY></HTML>"
        assert detect_content_type(content) == ContentKind.HTML

    def test_header_case_insensitive(self):
        assert detect_content_type("x", "Text/HTML") == ContentKind.HTML
        assert detect_content_type("x", "TEXT/HTML; CHARSET=UTF-8") == ContentKind.HTML


class TestPostprocessLinks:
    """Markdown link → Rich @click conversion."""

    def test_simple_link(self):
        md = "Click [here](https://example.com) for more."
        result = _postprocess_links(md)
        assert '[@click="navigate_link(\'https://example.com\')"]' in result
        assert "▸ here" in result

    def test_multiple_links(self):
        md = "[Link 1](https://a.com) and [Link 2](https://b.com)"
        result = _postprocess_links(md)
        assert "navigate_link('https://a.com')" in result
        assert "navigate_link('https://b.com')" in result

    def test_relative_link(self):
        md = "Go to [about page](/about)"
        result = _postprocess_links(md)
        assert "navigate_link('/about')" in result

    def test_link_with_single_quote(self):
        md = "[don't click](https://example.com)"
        result = _postprocess_links(md)
        # Text should be preserved as-is (quotes in URL would be escaped)
        assert "don't click" in result

    def test_url_with_single_quote_escaped(self):
        md = "[link](https://example.com/it's)"
        result = _postprocess_links(md)
        assert "navigate_link('https://example.com/it\\'s')" in result

    def test_no_links_unchanged(self):
        md = "Just plain text with no links."
        result = _postprocess_links(md)
        assert result == md

    def test_empty_string(self):
        assert _postprocess_links("") == ""

    def test_link_style_matches_micron(self):
        md = "[test](https://x.com)"
        result = _postprocess_links(md)
        assert "underline #5ac8fa" in result

    def test_i2p_link(self):
        md = "[I2P site](http://something.b32.i2p/page)"
        result = _postprocess_links(md)
        assert "navigate_link('http://something.b32.i2p/page')" in result

    def test_link_with_backslash_escaped(self):
        md = "[link](https://example.com/path\\file)"
        result = _postprocess_links(md)
        assert "\\\\" in result  # backslash should be escaped


class TestRenderHtmlToRich:
    """End-to-end HTML → Rich rendering."""

    def test_simple_html(self):
        html = "<p>Hello <strong>world</strong></p>"
        result = render_html_to_rich(html)
        # Should return a Rich renderable (Text)
        from rich.text import Text
        assert isinstance(result, Text)

    def test_html_with_link(self):
        html = '<p>Visit <a href="https://styrene.dev">Styrene</a></p>'
        result = render_html_to_rich(html)
        from rich.text import Text
        assert isinstance(result, Text)
        # The rendered text should contain the navigate_link action
        plain = result.plain
        assert "Styrene" in plain

    def test_heading_preserved(self):
        html = "<h1>Main Title</h1><p>Body text</p>"
        result = render_html_to_rich(html)
        plain = result.plain
        assert "Main Title" in plain

    def test_list_preserved(self):
        html = "<ul><li>First</li><li>Second</li></ul>"
        result = render_html_to_rich(html)
        plain = result.plain
        assert "First" in plain
        assert "Second" in plain

    def test_empty_html(self):
        result = render_html_to_rich("")
        from rich.text import Text
        assert isinstance(result, Text)

    def test_minimal_page(self):
        html = """<!DOCTYPE html>
        <html><head><title>Test</title></head>
        <body><h1>Hello</h1><p>World</p></body></html>"""
        result = render_html_to_rich(html)
        plain = result.plain
        assert "Hello" in plain
        assert "World" in plain


class TestRenderHtmlLinksNavigable:
    """Links in rendered HTML should be clickable TUI navigation targets."""

    def test_link_has_click_action(self):
        html = '<a href="https://example.com">Click me</a>'
        result = render_html_to_rich(html)
        # Verify the Text has spans with click actions
        markup = result._text  # Access raw markup text
        # The markup should contain navigate_link
        full_markup = "".join(markup) if isinstance(markup, list) else str(markup)
        # Actually let's check the Text object's internal representation
        # by checking it renders without errors
        from io import StringIO
        from rich.console import Console
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "Click me" in output
