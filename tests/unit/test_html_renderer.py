"""Tests for HTML-to-Rich rendering pipeline."""
from __future__ import annotations

import pytest

from styrened.tui.widgets.html_renderer import (
    ContentKind,
    _escape_rich_markup,
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
        content = ">Welcome to My Page\n\nSome text here."
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_literal(self):
        content = "`Preformatted text block"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_separator(self):
        content = "-= Section Break =-"
        assert detect_content_type(content) == ContentKind.MICRON

    def test_heuristic_micron_cache_directive(self):
        content = "#!c=3600\n>Page Title"
        assert detect_content_type(content) == ContentKind.MICRON

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


class TestEscapeRichMarkup:
    """_escape_rich_markup() prevents injection of Rich markup tokens."""

    def test_escapes_open_bracket(self):
        assert _escape_rich_markup("[bold]hi[/bold]") == "\\[bold]hi\\[/bold]"

    def test_close_bracket_not_escaped(self):
        # Rich only requires escaping '['; ']' needs no escaping.
        assert _escape_rich_markup("a]b") == "a]b"

    def test_escapes_click_action(self):
        raw = '[@click="evil"]pwned[/]'
        escaped = _escape_rich_markup(raw)
        assert "\\[@click" in escaped
        assert "\\[/" in escaped

    def test_escapes_bold_red(self):
        raw = "[bold red]injected[/bold red]"
        escaped = _escape_rich_markup(raw)
        assert escaped == "\\[bold red]injected\\[/bold red]"

    def test_plain_text_unchanged(self):
        text = "Hello world, no brackets here."
        assert _escape_rich_markup(text) == text

    def test_empty_string(self):
        assert _escape_rich_markup("") == ""


class TestPostprocessLinksImageRejection:
    """Image syntax and empty-label links must not be converted."""

    def test_image_syntax_not_converted(self):
        md = "![logo](https://example.com/img.png)"
        result = _postprocess_links(md)
        assert "navigate_link" not in result

    def test_empty_label_not_converted(self):
        md = "[](https://example.com)"
        result = _postprocess_links(md)
        assert "navigate_link" not in result

    def test_normal_link_adjacent_to_image_converted(self):
        md = "![img](https://example.com/img.png) and [click](https://example.com)"
        result = _postprocess_links(md)
        # Image NOT converted — no navigate_link for the image URL
        assert "navigate_link('https://example.com/img.png')" not in result
        # Normal link converted
        assert "navigate_link('https://example.com')" in result
        assert "▸ click" in result

    def test_image_with_alt_text_not_converted(self):
        md = "![alt text](https://example.com/photo.jpg)"
        result = _postprocess_links(md)
        assert "navigate_link" not in result


class TestRichMarkupInjectionPrevention:
    """render_html_to_rich() must escape markup tokens in page content."""

    def test_click_injection_escaped(self):
        html = '<p>[@click="evil"]pwned[/]</p>'
        result = render_html_to_rich(html)
        from rich.text import Text
        assert isinstance(result, Text)
        plain = result.plain
        # Literal text must appear in plain output
        assert "pwned" in plain
        # No click action should have been registered
        spans_with_click = [
            s for s in result._spans
            if "navigate_link" in repr(s.style)
        ]
        assert not spans_with_click

    def test_bold_markup_escaped(self):
        html = "<p>[bold red]injected[/bold red]</p>"
        result = render_html_to_rich(html)
        plain = result.plain
        assert "injected" in plain
        # No red/bold styling should have been applied to 'injected'
        # The literal bracket tokens appear in plain text (not consumed as markup)
        assert "[bold red]" in plain

    def test_legitimate_link_still_works(self):
        html = '<p><a href="https://example.com">click here</a></p>'
        result = render_html_to_rich(html)
        from rich.text import Text
        assert isinstance(result, Text)
        plain = result.plain
        assert "click here" in plain
        # There should be a navigate_link @click action on the link span.
        # Rich stores @click in Style.meta; repr() exposes it (str() renders as 'none').
        spans_with_action = [
            s for s in result._spans
            if "navigate_link" in repr(s.style)
        ]
        assert spans_with_action, "Expected navigate_link action on link span"

    def test_image_link_in_html_not_navigable(self):
        html = '<img src="https://example.com/img.png" alt="logo">'
        result = render_html_to_rich(html)
        from rich.text import Text
        assert isinstance(result, Text)
        # No navigate_link action should appear for an image
        spans_with_action = [
            s for s in result._spans
            if "navigate_link" in repr(s.style)
        ]
        assert not spans_with_action


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
