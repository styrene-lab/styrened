# TUI: html_renderer module — html2text + link post-processing — Design

## Architecture Decisions

### Decision: html_renderer module implemented

**Status:** decided
**Rationale:** tui/widgets/html_renderer.py created with render_html_to_rich(), detect_content_type(), _postprocess_links(). html2text>=2024.2.26 added to [tui] extra. 35 tests in test_html_renderer.py all pass.

## File Changes

- `src/styrened/tui/widgets/html_renderer.py` (new) — New module with: render_html_to_rich(html_str) -> Rich renderable using html2text + link post-processing; detect_content_type(content, content_type_header) -> enum ContentKind {MICRON, HTML, PLAIN}; _postprocess_links(markdown) converts [text](url) to @click Rich markup.
- `pyproject.toml` (modified) — Add 'html2text>=2024.2.26' to [tui] optional dependency extra.
- `tests/unit/test_html_renderer.py` (new) — Tests: HTML to Rich rendering, link post-processing, content-type detection heuristic, graceful import failure.

## Constraints

- html2text import must be lazy with graceful ImportError — returns a 'not installed' Rich message
- Link post-processing must convert ALL markdown links to @click format for internal TUI navigation
- detect_content_type must prefer explicit content_type_header over heuristic sniffing
- body_width=0 so Rich/Textual handles wrapping, not html2text
