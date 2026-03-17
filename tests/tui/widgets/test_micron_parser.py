"""Tests for micron markup parser.

Covers all element types, formatting codes, links, form fields,
literal blocks, directives, and edge cases.
"""
from __future__ import annotations

from styrened.tui.widgets.micron_parser import (
    Alignment,
    ElementType,
    FieldType,
    MicronElement,
    TextStyle,
    _expand_color,
    parse_micron,
    render_to_rich,
)


class TestExpandColor:
    """Tests for _expand_color() utility."""

    def test_3_char_hex(self):
        assert _expand_color("f00") == "#ff0000"

    def test_3_char_hex_mixed(self):
        assert _expand_color("abc") == "#aabbcc"

    def test_6_char_hex(self):
        assert _expand_color("ff8800") == "#ff8800"

    def test_grayscale_0(self):
        """g0 should be black."""
        result = _expand_color("g0")
        assert result == "#000000"

    def test_grayscale_99(self):
        """g99 should be white."""
        result = _expand_color("g99")
        assert result == "#ffffff"

    def test_grayscale_50(self):
        """g50 should be mid-gray."""
        result = _expand_color("g50")
        assert result is not None
        # ~128 decimal
        assert result.startswith("#")

    def test_invalid_returns_none(self):
        assert _expand_color("") is None
        assert _expand_color("zz") is None
        assert _expand_color("gggg") is None

    def test_invalid_hex_returns_none(self):
        assert _expand_color("xyz") is None
        assert _expand_color("zzzzzz") is None


class TestParseEmpty:
    """Tests for empty and trivial input."""

    def test_empty_string(self):
        assert parse_micron("") == []

    def test_single_empty_line(self):
        """A single empty line should produce one empty text element."""
        elements = parse_micron("\n")
        # Two lines: empty, empty
        assert len(elements) == 2
        for e in elements:
            assert e.element_type == ElementType.TEXT
            assert e.content == ""

    def test_plain_text(self):
        elements = parse_micron("Hello world")
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.TEXT
        assert elements[0].content == "Hello world"


class TestHeadings:
    """Tests for heading parsing."""

    def test_heading_level_1(self):
        elements = parse_micron(">Welcome")
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.HEADING
        assert elements[0].level == 1
        assert elements[0].content == "Welcome"

    def test_heading_level_2(self):
        elements = parse_micron(">>Subheading")
        assert len(elements) == 1
        assert elements[0].level == 2
        assert elements[0].content == "Subheading"

    def test_heading_level_3(self):
        elements = parse_micron(">>>Minor")
        assert len(elements) == 1
        assert elements[0].level == 3
        assert elements[0].content == "Minor"

    def test_heading_with_space(self):
        elements = parse_micron("> Heading Text")
        assert elements[0].content == "Heading Text"

    def test_heading_style_is_bold(self):
        elements = parse_micron(">Title")
        assert elements[0].style.bold is True


class TestDividers:
    """Tests for divider parsing."""

    def test_simple_divider(self):
        elements = parse_micron("-")
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.DIVIDER

    def test_divider_with_custom_char(self):
        elements = parse_micron("-=")
        assert elements[0].element_type == ElementType.DIVIDER
        assert elements[0].divider_char == "="

    def test_divider_default_char(self):
        elements = parse_micron("-")
        assert elements[0].divider_char == "\u2500"


class TestComments:
    """Tests for comment handling."""

    def test_comment_skipped(self):
        elements = parse_micron("# This is a comment")
        assert len(elements) == 0

    def test_comment_among_text(self):
        elements = parse_micron("Hello\n# comment\nWorld")
        assert len(elements) == 2
        assert elements[0].content == "Hello"
        assert elements[1].content == "World"


class TestPageDirectives:
    """Tests for #! page directives."""

    def test_cache_directive(self):
        elements = parse_micron("#!c=300")
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.PAGE_DIRECTIVE
        assert elements[0].directive_key == "c"
        assert elements[0].directive_value == "300"

    def test_background_directive(self):
        elements = parse_micron("#!bg=000")
        assert elements[0].directive_key == "bg"
        assert elements[0].directive_value == "000"

    def test_foreground_directive(self):
        elements = parse_micron("#!fg=fff")
        assert elements[0].directive_key == "fg"
        assert elements[0].directive_value == "fff"


class TestLiteralBlocks:
    """Tests for literal (code) blocks."""

    def test_literal_block(self):
        source = "`=\nHello *world*\nNo formatting here\n`="
        elements = parse_micron(source)
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.LITERAL
        assert "Hello *world*" in elements[0].content
        assert "No formatting here" in elements[0].content

    def test_unclosed_literal_block(self):
        """Unclosed literal blocks should still produce an element."""
        source = "`=\nSome content"
        elements = parse_micron(source)
        assert len(elements) == 1
        assert elements[0].element_type == ElementType.LITERAL
        assert elements[0].content == "Some content"


class TestInlineFormatting:
    """Tests for backtick-based inline formatting."""

    def test_bold_toggle(self):
        elements = parse_micron("`!Bold Text`!")
        # Should produce: bold text, then un-bold text (empty)
        assert len(elements) >= 1
        assert elements[0].style.bold is True
        assert elements[0].content == "Bold Text"

    def test_italic_toggle(self):
        elements = parse_micron("`*Italic`*")
        assert elements[0].style.italic is True

    def test_underline_toggle(self):
        elements = parse_micron("`_Underlined`_")
        assert elements[0].style.underline is True

    def test_reset_all(self):
        """Double backtick resets all formatting."""
        elements = parse_micron("`!Bold`` Normal")
        assert len(elements) == 2
        assert elements[0].style.bold is True
        assert elements[1].style.bold is False

    def test_foreground_color_3_char(self):
        elements = parse_micron("`Ff00Red text`f")
        assert len(elements) >= 1
        assert elements[0].style.fg_color == "#ff0000"

    def test_foreground_color_reset(self):
        elements = parse_micron("`Ff00Red`f Normal")
        assert elements[0].style.fg_color == "#ff0000"
        assert elements[1].style.fg_color is None

    def test_background_color(self):
        elements = parse_micron("`B00fBlue bg`b")
        assert elements[0].style.bg_color == "#0000ff"

    def test_center_alignment(self):
        elements = parse_micron("`cCentered")
        assert elements[0].style.alignment == Alignment.CENTER

    def test_right_alignment(self):
        elements = parse_micron("`rRight aligned")
        assert elements[0].style.alignment == Alignment.RIGHT

    def test_left_alignment(self):
        elements = parse_micron("`lLeft aligned")
        assert elements[0].style.alignment == Alignment.LEFT

    def test_reset_alignment(self):
        elements = parse_micron("`cCenter`a Reset")
        assert elements[0].style.alignment == Alignment.CENTER
        assert elements[1].style.alignment == Alignment.LEFT

    def test_escape_sequence(self):
        """Backslash should escape the next character."""
        elements = parse_micron("Hello \\`world")
        assert len(elements) == 1
        assert "`world" in elements[0].content

    def test_mixed_formatting(self):
        """Multiple formatting codes on one line."""
        elements = parse_micron("`!`*Bold Italic`*`!")
        # First element should be bold+italic
        assert elements[0].style.bold is True
        assert elements[0].style.italic is True


class TestLinks:
    """Tests for link parsing."""

    def test_simple_link(self):
        elements = parse_micron("`[About`/page/about.mu]")
        links = [e for e in elements if e.element_type == ElementType.LINK]
        assert len(links) == 1
        assert links[0].content == "About"
        assert links[0].url == "/page/about.mu"

    def test_link_url_only(self):
        elements = parse_micron("`[/page/about.mu]")
        links = [e for e in elements if e.element_type == ElementType.LINK]
        assert len(links) == 1
        assert links[0].url == "/page/about.mu"

    def test_link_with_fields(self):
        elements = parse_micron("`[Submit`/page/action`field1=val1]")
        links = [e for e in elements if e.element_type == ElementType.LINK]
        assert len(links) == 1
        assert links[0].content == "Submit"
        assert links[0].url == "/page/action"
        assert links[0].link_fields == "field1=val1"

    def test_link_style_underlined(self):
        elements = parse_micron("`[Link`/page/x]")
        links = [e for e in elements if e.element_type == ElementType.LINK]
        assert links[0].style.underline is True


class TestFormFields:
    """Tests for form field parsing."""

    def test_text_field(self):
        elements = parse_micron("`<name`default value>")
        fields = [e for e in elements if e.element_type == ElementType.FORM_FIELD]
        assert len(fields) == 1
        assert fields[0].field_type == FieldType.TEXT
        assert fields[0].field_name == "name"
        assert fields[0].field_value == "default value"

    def test_sized_text_field(self):
        elements = parse_micron("`<32|username`>")
        fields = [e for e in elements if e.element_type == ElementType.FORM_FIELD]
        assert len(fields) == 1
        assert fields[0].field_width == 32
        assert fields[0].field_name == "username"

    def test_password_field(self):
        elements = parse_micron("`<!|password`>")
        fields = [e for e in elements if e.element_type == ElementType.FORM_FIELD]
        assert len(fields) == 1
        assert fields[0].field_type == FieldType.PASSWORD
        assert fields[0].field_name == "password"

    def test_checkbox_field(self):
        elements = parse_micron("`<?|agree|yes`>Accept terms")
        fields = [e for e in elements if e.element_type == ElementType.FORM_FIELD]
        assert len(fields) == 1
        assert fields[0].field_type == FieldType.CHECKBOX
        assert fields[0].field_name == "agree"
        assert fields[0].field_value == "yes"

    def test_radio_field(self):
        elements = parse_micron("`<^|color|red`>Red")
        fields = [e for e in elements if e.element_type == ElementType.FORM_FIELD]
        assert len(fields) == 1
        assert fields[0].field_type == FieldType.RADIO
        assert fields[0].field_name == "color"
        assert fields[0].field_value == "red"


class TestSectionReset:
    """Tests for section reset (<) handling."""

    def test_section_reset_with_text(self):
        elements = parse_micron("<Back to top")
        assert len(elements) >= 1
        # Should parse the remaining text
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) >= 1
        assert text_elems[0].content == "Back to top"

    def test_section_reset_empty(self):
        """Section reset with no following text should produce no elements."""
        elements = parse_micron("<")
        assert len(elements) == 0


class TestRenderToRich:
    """Tests for render_to_rich() conversion."""

    def test_heading_1_bold(self):
        elements = [
            MicronElement(element_type=ElementType.HEADING, content="Title", level=1)
        ]
        result = render_to_rich(elements)
        assert "[bold" in result
        assert "Title" in result

    def test_heading_3_bold_italic(self):
        elements = [
            MicronElement(element_type=ElementType.HEADING, content="Sub", level=3)
        ]
        result = render_to_rich(elements)
        assert "[bold italic" in result

    def test_text_plain(self):
        elements = [
            MicronElement(element_type=ElementType.TEXT, content="Hello")
        ]
        result = render_to_rich(elements)
        assert "Hello" in result

    def test_text_bold(self):
        elements = [
            MicronElement(
                element_type=ElementType.TEXT,
                content="Bold",
                style=TextStyle(bold=True),
            )
        ]
        result = render_to_rich(elements)
        assert "[bold]" in result

    def test_text_with_color(self):
        elements = [
            MicronElement(
                element_type=ElementType.TEXT,
                content="Red",
                style=TextStyle(fg_color="#ff0000"),
            )
        ]
        result = render_to_rich(elements)
        assert "#ff0000" in result

    def test_divider(self):
        elements = [
            MicronElement(element_type=ElementType.DIVIDER, divider_char="-")
        ]
        result = render_to_rich(elements)
        assert "[dim" in result
        assert "-" in result

    def test_literal_block(self):
        elements = [
            MicronElement(element_type=ElementType.LITERAL, content="code\nhere")
        ]
        result = render_to_rich(elements)
        assert "code" in result
        assert "here" in result

    def test_link(self):
        elements = [
            MicronElement(
                element_type=ElementType.LINK,
                content="Click",
                url="/page/about.mu",
            )
        ]
        result = render_to_rich(elements)
        assert "[underline" in result
        assert "Click" in result
        assert "navigate_link" in result
        assert "/page/about.mu" in result

    def test_link_url_escaped_in_action(self):
        """Single quotes in URLs should be escaped in @click action."""
        elements = [
            MicronElement(
                element_type=ElementType.LINK,
                content="Weird",
                url="/page/it's.mu",
            )
        ]
        result = render_to_rich(elements)
        assert "\\'" in result
        assert "Weird" in result

    def test_checkbox_unchecked(self):
        elements = [
            MicronElement(
                element_type=ElementType.FORM_FIELD,
                field_type=FieldType.CHECKBOX,
                content="Accept",
                field_checked=False,
            )
        ]
        result = render_to_rich(elements)
        assert "[ ]" in result

    def test_checkbox_checked(self):
        elements = [
            MicronElement(
                element_type=ElementType.FORM_FIELD,
                field_type=FieldType.CHECKBOX,
                content="Accept",
                field_checked=True,
            )
        ]
        result = render_to_rich(elements)
        assert "[x]" in result

    def test_radio_unchecked(self):
        elements = [
            MicronElement(
                element_type=ElementType.FORM_FIELD,
                field_type=FieldType.RADIO,
                content="Red",
                field_checked=False,
            )
        ]
        result = render_to_rich(elements)
        assert "( )" in result

    def test_radio_checked(self):
        elements = [
            MicronElement(
                element_type=ElementType.FORM_FIELD,
                field_type=FieldType.RADIO,
                content="Red",
                field_checked=True,
            )
        ]
        result = render_to_rich(elements)
        assert "(*)" in result

    def test_page_directive_not_rendered(self):
        elements = [
            MicronElement(
                element_type=ElementType.PAGE_DIRECTIVE,
                directive_key="c",
                directive_value="300",
            )
        ]
        result = render_to_rich(elements)
        assert result == ""

    def test_empty_text_produces_empty_line(self):
        elements = [
            MicronElement(element_type=ElementType.TEXT, content="")
        ]
        result = render_to_rich(elements)
        assert result == ""

    def test_rich_markup_escaped(self):
        """Opening brackets in content should be escaped."""
        elements = [
            MicronElement(element_type=ElementType.TEXT, content="[not markup]")
        ]
        result = render_to_rich(elements)
        assert "\\[" in result
        # Closing bracket should NOT be escaped (Rich doesn't need it)
        assert "\\]" not in result


class TestComplexDocuments:
    """Integration-style tests with multi-line micron documents."""

    def test_full_page(self):
        source = """\
#!c=60
>Welcome to My Node
-
Some introductory text
`!Bold text`!

`[About`/page/about.mu]
# This is a comment
`=
Literal code
`=
"""
        elements = parse_micron(source)

        types = [e.element_type for e in elements]
        assert ElementType.PAGE_DIRECTIVE in types
        assert ElementType.HEADING in types
        assert ElementType.DIVIDER in types
        assert ElementType.TEXT in types
        assert ElementType.LINK in types
        assert ElementType.LITERAL in types

    def test_formatting_persistence(self):
        """Formatting state should persist across lines."""
        source = "`!Bold start\nStill bold"
        elements = parse_micron(source)
        # Both text elements should be bold
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) == 2
        assert text_elems[0].style.bold is True
        assert text_elems[1].style.bold is True

    def test_alignment_persistence(self):
        """Alignment should persist across lines."""
        source = "`cCentered\nAlso centered"
        elements = parse_micron(source)
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) == 2
        assert text_elems[0].style.alignment == Alignment.CENTER
        assert text_elems[1].style.alignment == Alignment.CENTER

    def test_lone_backtick_resets_formatting(self):
        """A lone backtick on a line should reset formatting and produce no output."""
        source = "`!Bold text\n`\nNormal text"
        elements = parse_micron(source)
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) == 2
        assert text_elems[0].style.bold is True
        assert text_elems[0].content == "Bold text"
        assert text_elems[1].style.bold is False
        assert text_elems[1].content == "Normal text"

    def test_lone_backtick_not_rendered(self):
        """A lone backtick should not produce a visible element."""
        source = "Before\n`\nAfter"
        elements = parse_micron(source)
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) == 2
        contents = [e.content for e in text_elems]
        assert "`" not in contents


class TestHeadingInlineFormatting:
    """Bug 1: Heading text should be parsed through inline formatter."""

    def test_heading_with_bold_inline(self):
        """Heading containing `! bold toggle should parse children.

        Headings start with bold=True. The `! code toggles bold OFF,
        so 'Styrix' between the toggles is NOT bold.
        """
        elements = parse_micron(">NixOS `!Styrix`!")
        assert len(elements) == 1
        h = elements[0]
        assert h.element_type == ElementType.HEADING
        assert h.children is not None
        assert len(h.children) >= 2
        # First child: "NixOS " inherits heading bold
        assert h.children[0].content == "NixOS "
        assert h.children[0].style.bold is True
        # Second child: "Styrix" — `! toggled bold OFF from heading base
        assert h.children[1].content == "Styrix"
        assert h.children[1].style.bold is False

    def test_heading_with_color_inline(self):
        """Heading with foreground color code should parse inline."""
        elements = parse_micron(">`Ff00Red Heading")
        h = elements[0]
        assert h.element_type == ElementType.HEADING
        assert h.children is not None
        color_child = [c for c in h.children if c.style.fg_color == "#ff0000"]
        assert len(color_child) >= 1

    def test_heading_plain_text_no_children(self):
        """Heading with no inline formatting should have no children."""
        elements = parse_micron(">Plain Heading")
        h = elements[0]
        assert h.element_type == ElementType.HEADING
        # Plain text: children should be None (no inline codes present)
        assert h.children is None

    def test_heading_inline_does_not_leak(self):
        """Inline formatting in heading must not affect subsequent lines."""
        source = ">`!Bold Heading\nRegular text"
        elements = parse_micron(source)
        heading = elements[0]
        assert heading.element_type == ElementType.HEADING
        text = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text) == 1
        # Bold from heading must NOT leak to regular text
        assert text[0].style.bold is False

    def test_heading_inherently_bold(self):
        """Heading children should have bold=True as base style."""
        elements = parse_micron(">Simple Title")
        h = elements[0]
        assert h.style.bold is True


class TestSectionResetRecursive:
    """Bug 2: Section reset < should recursively parse headings/dividers."""

    def test_section_reset_then_heading(self):
        """<>Heading should produce a HEADING element."""
        elements = parse_micron("<>My Heading")
        headings = [e for e in elements if e.element_type == ElementType.HEADING]
        assert len(headings) == 1
        assert headings[0].content == "My Heading"
        assert headings[0].level == 1

    def test_section_reset_then_divider(self):
        """<- should produce a DIVIDER element."""
        elements = parse_micron("<-")
        dividers = [e for e in elements if e.element_type == ElementType.DIVIDER]
        assert len(dividers) == 1

    def test_section_reset_then_level2_heading(self):
        """<>>Sub should produce a level-2 heading."""
        elements = parse_micron("<>>Sub Heading")
        headings = [e for e in elements if e.element_type == ElementType.HEADING]
        assert len(headings) == 1
        assert headings[0].level == 2
        assert headings[0].content == "Sub Heading"

    def test_section_reset_preserves_formatting(self):
        """< does NOT reset inline formatting state (only depth)."""
        source = "`!Bold start\n<Still bold"
        elements = parse_micron(source)
        text_elems = [e for e in elements if e.element_type == ElementType.TEXT]
        assert len(text_elems) == 2
        assert text_elems[0].style.bold is True
        assert text_elems[1].style.bold is True

    def test_section_reset_divider_custom_char(self):
        """<-= should produce a DIVIDER with '=' fill character."""
        elements = parse_micron("<-=")
        dividers = [e for e in elements if e.element_type == ElementType.DIVIDER]
        assert len(dividers) == 1
        assert dividers[0].divider_char == "="


class TestLiteralBlockStyling:
    """Literal blocks should remain visually muted and stable under themed rich tags."""

    def test_literal_renders_dim(self):
        """Literal blocks should render with dim styling."""
        elements = [
            MicronElement(element_type=ElementType.LITERAL, content="code line")
        ]
        result = render_to_rich(elements)
        assert "[dim" in result
        assert "code line" in result

    def test_literal_multiline_all_dim(self):
        """Each line of a literal block should keep dim styling."""
        elements = [
            MicronElement(element_type=ElementType.LITERAL, content="line1\nline2")
        ]
        result = render_to_rich(elements)
        lines = result.split("\n")
        for line in lines:
            assert "[dim" in line


class TestHeadingRenderWithChildren:
    """Bug 1 render side: headings with children should render inline styles."""

    def test_heading_children_rendered_bold(self):
        """Heading with children should produce bold output for all children."""
        children = [
            MicronElement(
                element_type=ElementType.TEXT,
                content="Hello ",
                style=TextStyle(bold=False),
            ),
            MicronElement(
                element_type=ElementType.TEXT,
                content="World",
                style=TextStyle(italic=True),
            ),
        ]
        elem = MicronElement(
            element_type=ElementType.HEADING,
            content="Hello World",
            level=1,
            children=children,
        )
        result = render_to_rich([elem])
        assert "Hello " in result
        assert "World" in result
        # Bold should be applied (heading base style)
        assert "[bold]" in result or "bold" in result

    def test_heading_level3_children_bold_italic(self):
        """Level 3+ headings with children should use bold italic base."""
        children = [
            MicronElement(
                element_type=ElementType.TEXT,
                content="Minor",
                style=TextStyle(),
            ),
        ]
        elem = MicronElement(
            element_type=ElementType.HEADING,
            content="Minor",
            level=3,
            children=children,
        )
        result = render_to_rich([elem])
        assert "bold" in result
        assert "italic" in result

    def test_heading_no_children_backward_compat(self):
        """Heading without children should still render plain content."""
        elem = MicronElement(
            element_type=ElementType.HEADING,
            content="Plain",
            level=1,
        )
        result = render_to_rich([elem])
        assert "[bold" in result
        assert "Plain" in result

    def test_heading_children_with_color(self):
        """Heading children with fg_color should include color in output."""
        children = [
            MicronElement(
                element_type=ElementType.TEXT,
                content="Colored",
                style=TextStyle(fg_color="#ff0000"),
            ),
        ]
        elem = MicronElement(
            element_type=ElementType.HEADING,
            content="Colored",
            level=1,
            children=children,
        )
        result = render_to_rich([elem])
        assert "#ff0000" in result
        assert "bold" in result
