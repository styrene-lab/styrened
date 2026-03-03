"""Micron markup parser for NomadNet page rendering.

Parses NomadNet's micron markup language into structured elements,
then renders them to Rich markup strings for display in Textual widgets.

Micron is a lightweight markup language used by NomadNet for serving
pages over Reticulum mesh networks. It supports headings, text formatting,
links, form fields, literal blocks, dividers, and page directives.

Reference: NomadNet MicronParser.py
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto


class ElementType(Enum):
    """Types of parsed micron elements."""

    HEADING = auto()
    TEXT = auto()
    DIVIDER = auto()
    LINK = auto()
    LITERAL = auto()
    FORM_FIELD = auto()
    PAGE_DIRECTIVE = auto()


class Alignment(Enum):
    """Text alignment."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class FieldType(Enum):
    """Form field types."""

    TEXT = "text"
    PASSWORD = "password"
    CHECKBOX = "checkbox"
    RADIO = "radio"


@dataclass
class TextStyle:
    """Inline text formatting state."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    fg_color: str | None = None
    bg_color: str | None = None
    alignment: Alignment = Alignment.LEFT


@dataclass
class MicronElement:
    """A parsed micron markup element."""

    element_type: ElementType
    content: str = ""
    level: int = 0  # Heading level (1-based)
    style: TextStyle = field(default_factory=TextStyle)
    # Link-specific
    url: str = ""
    link_fields: str = ""
    # Form field-specific
    field_type: FieldType = FieldType.TEXT
    field_name: str = ""
    field_value: str = ""
    field_width: int = 24
    field_checked: bool = False
    # Page directive
    directive_key: str = ""
    directive_value: str = ""
    # Divider fill character
    divider_char: str = "\u2500"
    # Compound children for inline-formatted headings
    children: list["MicronElement"] | None = None


def _expand_color(code: str) -> str | None:
    """Expand a micron color code to a #RRGGBB hex string.

    Handles:
    - 3-char hex: 'f00' -> '#ff0000'
    - 6-char hex: 'ff8800' -> '#ff8800'
    - Grayscale: 'g50' -> gray at 50%

    Returns:
        Hex color string or None if invalid.
    """
    if not code:
        return None

    # Grayscale: gNN (decimal 0-99)
    if code.startswith("g") and len(code) >= 2:
        try:
            gray_pct = int(code[1:])
            gray_val = int(gray_pct * 255 / 99)
            gray_val = max(0, min(255, gray_val))
            return f"#{gray_val:02x}{gray_val:02x}{gray_val:02x}"
        except ValueError:
            return None

    # 3-char hex
    if len(code) == 3:
        try:
            int(code, 16)
            r, g, b = code[0], code[1], code[2]
            return f"#{r}{r}{g}{g}{b}{b}"
        except ValueError:
            return None

    # 6-char hex
    if len(code) == 6:
        try:
            int(code, 16)
            return f"#{code}"
        except ValueError:
            return None

    return None


def _has_inline_codes(text: str) -> bool:
    """Check whether text contains any backtick formatting codes."""
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "`" and i + 1 < len(text):
            return True
        i += 1
    return False


def _parse_line(
    stripped: str, style: TextStyle, elements: list[MicronElement]
) -> None:
    """Parse a single stripped line into elements.

    Handles section reset, headings, dividers, lone backtick reset,
    and regular text. Extracted from parse_micron() to enable recursive
    parsing of section reset remainder.

    Args:
        stripped: The stripped line content.
        style: Current formatting state (modified in-place for regular text).
        elements: Accumulator list to append parsed elements to.
    """
    # Section reset (<) — recurse on remainder
    if stripped.startswith("<"):
        remainder = stripped[1:]
        if remainder:
            _parse_line(remainder, style, elements)
        return

    # Headings (>, >>, >>>)
    if stripped.startswith(">"):
        level = 0
        i = 0
        while i < len(stripped) and stripped[i] == ">":
            level += 1
            i += 1
        heading_text = stripped[i:].strip()

        # Parse heading text through inline formatter with isolated style
        children = None
        if _has_inline_codes(heading_text):
            heading_style = replace(style)
            heading_style.bold = True
            children = _parse_inline(heading_text, heading_style)
            # Discard heading_style — formatting does NOT leak

        elements.append(
            MicronElement(
                element_type=ElementType.HEADING,
                content=heading_text,
                level=level,
                style=TextStyle(bold=True),
                children=children,
            )
        )
        return

    # Dividers (- at start of line)
    if stripped.startswith("-"):
        fill_char = "\u2500"
        if len(stripped) > 1:
            fill_char = stripped[1]
        elements.append(
            MicronElement(
                element_type=ElementType.DIVIDER,
                divider_char=fill_char,
            )
        )
        return

    # Lone backtick — formatting reset (no visible output)
    if stripped == "`":
        style.bold = False
        style.italic = False
        style.underline = False
        style.fg_color = None
        style.bg_color = None
        style.alignment = Alignment.LEFT
        return

    # Regular text with inline formatting
    if stripped:
        text_elements = _parse_inline(stripped, style)
        elements.extend(text_elements)
    else:
        # Empty line
        elements.append(
            MicronElement(
                element_type=ElementType.TEXT,
                content="",
                style=TextStyle(
                    alignment=style.alignment,
                ),
            )
        )


def parse_micron(source: str) -> list[MicronElement]:
    """Parse micron markup source into a list of elements.

    Args:
        source: Raw micron markup string.

    Returns:
        List of MicronElement objects representing the parsed content.
    """
    if not source:
        return []

    elements: list[MicronElement] = []
    lines = source.split("\n")
    literal_mode = False
    literal_lines: list[str] = []

    # Structured data block accumulation (parallel to literal_mode)
    sd_block_mode = False
    sd_block_encoding: str = ""
    sd_block_lines: list[str] = []

    # Current formatting state (persists across lines)
    style = TextStyle()

    for line in lines:
        # Literal mode toggle
        if line.strip() == "`=":
            if literal_mode:
                # End literal block
                elements.append(
                    MicronElement(
                        element_type=ElementType.LITERAL,
                        content="\n".join(literal_lines),
                    )
                )
                literal_lines = []
                literal_mode = False
            else:
                literal_mode = True
            continue

        if literal_mode:
            literal_lines.append(line)
            continue

        # Page directives (#!key=value) and structured data blocks
        stripped = line.strip()
        if stripped.startswith("#!"):
            # Check for structured data block end marker (#!sd:<enc>:end)
            if sd_block_mode and stripped == f"#!sd:{sd_block_encoding}:end":
                # Emit accumulated block as a single PAGE_DIRECTIVE element
                elements.append(
                    MicronElement(
                        element_type=ElementType.PAGE_DIRECTIVE,
                        directive_key=f"sd:{sd_block_encoding}:block",
                        directive_value="\n".join(sd_block_lines),
                    )
                )
                sd_block_mode = False
                sd_block_encoding = ""
                sd_block_lines = []
                continue

            # Inside a block, accumulate content (including #! lines)
            if sd_block_mode:
                sd_block_lines.append(line)
                continue

            # Check for structured data block begin marker (#!sd:<enc>:begin)
            if stripped.startswith("#!sd:") and stripped.endswith(":begin"):
                # Extract encoding from #!sd:<enc>:begin
                inner = stripped[5:-6]  # strip "#!sd:" and ":begin"
                if inner and ":" not in inner:
                    sd_block_mode = True
                    sd_block_encoding = inner
                    sd_block_lines = []
                    continue

            directive = stripped[2:]
            if "=" in directive:
                key, _, value = directive.partition("=")
                elements.append(
                    MicronElement(
                        element_type=ElementType.PAGE_DIRECTIVE,
                        directive_key=key.strip(),
                        directive_value=value.strip(),
                    )
                )
            continue

        # Inside a structured data block, non-directive lines are block content
        if sd_block_mode:
            sd_block_lines.append(line)
            continue

        # Comments (# at start of line)
        if stripped.startswith("#"):
            continue

        _parse_line(stripped, style, elements)

    # Close unclosed structured data block (discard — incomplete block)
    # We intentionally don't emit partial blocks as they're malformed.

    # Close unclosed literal block
    if literal_mode and literal_lines:
        elements.append(
            MicronElement(
                element_type=ElementType.LITERAL,
                content="\n".join(literal_lines),
            )
        )

    return elements


def _parse_inline(text: str, style: TextStyle) -> list[MicronElement]:
    """Parse inline formatting, links, and form fields from a line.

    Updates the style state in-place (formatting toggles persist).

    Args:
        text: Line of text to parse.
        style: Current formatting state (modified in-place).

    Returns:
        List of elements produced from this line.
    """
    elements: list[MicronElement] = []
    current_text = []
    i = 0

    while i < len(text):
        ch = text[i]

        # Escape sequence
        if ch == "\\" and i + 1 < len(text):
            current_text.append(text[i + 1])
            i += 2
            continue

        # Backtick formatting
        if ch == "`" and i + 1 < len(text):
            next_ch = text[i + 1]

            # Double backtick — reset all formatting
            if next_ch == "`":
                # Flush current text
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.bold = False
                style.italic = False
                style.underline = False
                style.fg_color = None
                style.bg_color = None
                style.alignment = Alignment.LEFT
                i += 2
                continue

            # Bold toggle
            if next_ch == "!":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.bold = not style.bold
                i += 2
                continue

            # Italic toggle
            if next_ch == "*":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.italic = not style.italic
                i += 2
                continue

            # Underline toggle
            if next_ch == "_":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.underline = not style.underline
                i += 2
                continue

            # Foreground color
            if next_ch == "F":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                # Try 6-char then 3-char color
                color_str = text[i + 2 : i + 8]
                color = _expand_color(color_str)
                if color and len(color_str) == 6:
                    style.fg_color = color
                    i += 8
                else:
                    color_str = text[i + 2 : i + 5]
                    color = _expand_color(color_str)
                    style.fg_color = color
                    i += 5
                continue

            # Reset foreground
            if next_ch == "f":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.fg_color = None
                i += 2
                continue

            # Background color
            if next_ch == "B":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                color_str = text[i + 2 : i + 8]
                color = _expand_color(color_str)
                if color and len(color_str) == 6:
                    style.bg_color = color
                    i += 8
                else:
                    color_str = text[i + 2 : i + 5]
                    color = _expand_color(color_str)
                    style.bg_color = color
                    i += 5
                continue

            # Reset background
            if next_ch == "b":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                style.bg_color = None
                i += 2
                continue

            # Alignment
            if next_ch in ("c", "l", "r", "a"):
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                alignment_map = {
                    "c": Alignment.CENTER,
                    "l": Alignment.LEFT,
                    "r": Alignment.RIGHT,
                    "a": Alignment.LEFT,
                }
                style.alignment = alignment_map[next_ch]
                i += 2
                continue

            # Link: `[label`url`fields]
            if next_ch == "[":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                link_element, consumed = _parse_link(text, i + 2, style)
                if link_element:
                    elements.append(link_element)
                i += consumed
                continue

            # Form field: `<...>
            if next_ch == "<":
                if current_text:
                    elements.append(_make_text_element("".join(current_text), style))
                    current_text = []
                field_element, consumed = _parse_form_field(text, i + 2)
                if field_element:
                    elements.append(field_element)
                i += consumed
                continue

            # Literal mode toggle (handled at line level, but handle gracefully)
            if next_ch == "=":
                i += 2
                continue

            # Unknown backtick code — emit literally
            current_text.append(ch)
            i += 1
            continue

        # Regular character
        current_text.append(ch)
        i += 1

    # Flush remaining text
    if current_text:
        elements.append(_make_text_element("".join(current_text), style))

    return elements


def _make_text_element(content: str, style: TextStyle) -> MicronElement:
    """Create a text element with a snapshot of the current style."""
    return MicronElement(
        element_type=ElementType.TEXT,
        content=content,
        style=TextStyle(
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
            fg_color=style.fg_color,
            bg_color=style.bg_color,
            alignment=style.alignment,
        ),
    )


def _parse_link(
    text: str, start: int, style: TextStyle
) -> tuple[MicronElement | None, int]:
    """Parse a link element starting after `[`.

    Format: label`url`fields]

    Returns:
        Tuple of (element, total chars consumed from original position).
    """
    # Find closing ]
    end = text.find("]", start)
    if end == -1:
        return None, 2  # Just skip `[

    inner = text[start:end]
    parts = inner.split("`")

    if len(parts) == 1:
        # Just URL: `[url]
        url = parts[0]
        label = url
        link_fields = ""
    elif len(parts) == 2:
        # `[label`url]
        label = parts[0]
        url = parts[1]
        link_fields = ""
    else:
        # `[label`url`fields]
        label = parts[0]
        url = parts[1]
        link_fields = parts[2]

    element = MicronElement(
        element_type=ElementType.LINK,
        content=label,
        url=url,
        link_fields=link_fields,
        style=TextStyle(
            bold=style.bold,
            italic=style.italic,
            underline=True,
            fg_color=style.fg_color,
            bg_color=style.bg_color,
            alignment=style.alignment,
        ),
    )

    # Consumed: `[ + inner + ]
    return element, (end - start + 2 + 1)


def _parse_form_field(text: str, start: int) -> tuple[MicronElement | None, int]:
    """Parse a form field starting after `<`.

    Formats:
    - `<name`value>           — text field
    - `<width|name`value>     — sized text field
    - `<!|name`value>         — password field
    - `<?|name|value`>label   — checkbox
    - `<^|name|value`>label   — radio

    Returns:
        Tuple of (element, total chars consumed from original position).
    """
    # Find closing >
    end = text.find(">", start)
    if end == -1:
        return None, 2  # Just skip `<

    inner = text[start:end]
    parts = inner.split("`")

    descriptor = parts[0]
    default_value = parts[1] if len(parts) > 1 else ""

    # Parse descriptor for flags and field name
    field_type = FieldType.TEXT
    field_name = descriptor
    field_width = 24
    field_checked = False
    field_value = default_value

    if "|" in descriptor:
        segments = descriptor.split("|")
        flags = segments[0]

        if flags == "?" or flags.startswith("?"):
            # Checkbox
            field_type = FieldType.CHECKBOX
            field_name = segments[1] if len(segments) > 1 else ""
            field_value = segments[2] if len(segments) > 2 else ""
            field_checked = len(segments) > 3 and segments[3] == "*"
        elif flags == "^" or flags.startswith("^"):
            # Radio button
            field_type = FieldType.RADIO
            field_name = segments[1] if len(segments) > 1 else ""
            field_value = segments[2] if len(segments) > 2 else ""
            field_checked = len(segments) > 3 and segments[3] == "*"
        elif flags == "!" or flags.startswith("!"):
            # Password field
            field_type = FieldType.PASSWORD
            field_name = segments[1] if len(segments) > 1 else ""
            # Check for width in flags
            width_str = flags.lstrip("!")
            if width_str.isdigit():
                field_width = min(int(width_str), 256)
        else:
            # Width or other flags
            field_name = segments[1] if len(segments) > 1 else ""
            if flags.isdigit():
                field_width = min(int(flags), 256)

    element = MicronElement(
        element_type=ElementType.FORM_FIELD,
        content=default_value,
        field_type=field_type,
        field_name=field_name,
        field_value=field_value,
        field_width=field_width,
        field_checked=field_checked,
    )

    # Consumed: `< + inner + >
    return element, (end - start + 2 + 1)


def render_to_rich(
    elements: list[MicronElement],
    form_state: dict[str, str] | None = None,
) -> str:
    """Convert parsed micron elements to a Rich markup string.

    Args:
        elements: List of MicronElement objects from parse_micron().
        form_state: Optional dict of field_name → current_value for form
            fields.  When provided, field displays reflect user edits and
            fields become clickable for editing.

    Returns:
        Rich markup string suitable for display in a Static widget.
    """
    lines: list[str] = []

    for elem in elements:
        if elem.element_type == ElementType.PAGE_DIRECTIVE:
            # Directives are metadata, not displayed
            continue

        if elem.element_type == ElementType.HEADING:
            level = min(elem.level, 3)
            # Visual hierarchy: h1 = bright cyan bold, h2 = cyan bold, h3 = dim cyan italic
            _HEADING_STYLES = {
                1: "bold #5af0ce",
                2: "bold #3fbfa0",
                3: "bold italic #6a9a8e",
            }
            base_tag = _HEADING_STYLES.get(level, "bold #5af0ce")

            if elem.children:
                parts: list[str] = []
                for child in elem.children:
                    child_tags = [base_tag]
                    if child.style.fg_color:
                        child_tags.append(child.style.fg_color)
                    if child.style.underline:
                        child_tags.append("underline")
                    tag_str = " ".join(child_tags)
                    parts.append(
                        f"[{tag_str}]{_escape(child.content)}[/{tag_str}]"
                    )
                lines.append("".join(parts))
            else:
                lines.append(f"[{base_tag}]{_escape(elem.content)}[/{base_tag}]")

        elif elem.element_type == ElementType.TEXT:
            if not elem.content:
                lines.append("")
            else:
                markup = _style_to_rich(elem.style, _escape(elem.content))
                lines.append(markup)

        elif elem.element_type == ElementType.DIVIDER:
            lines.append(f"[dim #3a6a5e]{elem.divider_char * 48}[/dim #3a6a5e]")

        elif elem.element_type == ElementType.LITERAL:
            # Render verbatim content in a visually distinct monospace block
            for lit_line in elem.content.split("\n"):
                lines.append(f"[dim #8a9a8e]  │ {_escape(lit_line)}[/dim #8a9a8e]")

        elif elem.element_type == ElementType.LINK:
            label = _escape(elem.content) or _escape(elem.url)
            url_safe = elem.url.replace("\\", "\\\\").replace("'", "\\'")
            link_style = "underline #5ac8fa"
            if elem.link_fields:
                fields_safe = elem.link_fields.replace("\\", "\\\\").replace("'", "\\'")
                lines.append(
                    f"[@click=\"submit_form('{url_safe}', '{fields_safe}')\"]"
                    f"[{link_style}]▸ {label}[/{link_style}]"
                    f"[/]"
                )
            else:
                lines.append(
                    f"[@click=\"navigate_link('{url_safe}')\"]"
                    f"[{link_style}]▸ {label}[/{link_style}]"
                    f"[/]"
                )

        elif elem.element_type == ElementType.FORM_FIELD:
            # Use form_state if available, otherwise use default
            current_value = (
                form_state.get(elem.field_name, elem.field_value)
                if form_state is not None
                else elem.field_value
            )
            # Populate form_state for later collection
            if form_state is not None and elem.field_name not in form_state:
                form_state[elem.field_name] = elem.field_value

            name_safe = elem.field_name.replace("\\", "\\\\").replace("'", "\\'")
            val_safe = current_value.replace("\\", "\\\\").replace("'", "\\'")

            if elem.field_type == FieldType.TEXT:
                display_val = _escape(current_value) or "…"
                lines.append(
                    f"[@click=\"edit_field('{name_safe}', '{val_safe}')\"]"
                    f"[underline]\\[{_escape(elem.field_name)}: {display_val}][/underline]"
                    f"[/]"
                )
            elif elem.field_type == FieldType.PASSWORD:
                display_val = "•" * len(current_value) if current_value else "…"
                lines.append(
                    f"[@click=\"edit_field('{name_safe}', '{val_safe}')\"]"
                    f"[underline]\\[{_escape(elem.field_name)}: {display_val}][/underline]"
                    f"[/]"
                )
            elif elem.field_type == FieldType.CHECKBOX:
                check = "x" if elem.field_checked else " "
                lines.append(f"\\[{check}] {_escape(elem.content)}")
            elif elem.field_type == FieldType.RADIO:
                dot = "*" if elem.field_checked else " "
                lines.append(f"({dot}) {_escape(elem.content)}")

    return "\n".join(lines)


def _style_to_rich(style: TextStyle, content: str) -> str:
    """Apply a TextStyle as Rich markup around content."""
    tags: list[str] = []
    if style.bold:
        tags.append("bold")
    if style.italic:
        tags.append("italic")
    if style.underline:
        tags.append("underline")
    if style.fg_color:
        tags.append(style.fg_color)

    if not tags:
        return content

    tag_str = " ".join(tags)
    return f"[{tag_str}]{content}[/{tag_str}]"


def _escape(text: str) -> str:
    """Escape Rich markup special characters.

    Only ``[`` needs escaping — Rich treats ``\\[`` as a literal bracket.
    ``]`` is literal unless preceded by an unescaped ``[``, and since we
    escape all ``[`` characters, bare ``]`` is always safe.
    """
    return text.replace("[", "\\[")
