# TUI: html_renderer module — html2text + link post-processing — Tasks

## 1. src/styrened/tui/widgets/html_renderer.py (new)

- [x] 1.1 New module with: render_html_to_rich(html_str) -> Rich renderable using html2text + link post-processing; detect_content_type(content, content_type_header) -> enum ContentKind {MICRON, HTML, PLAIN}; _postprocess_links(markdown) converts [text](url) to @click Rich markup.

## 2. pyproject.toml (modified)

- [x] 2.1 Add 'html2text>=2024.2.26' to [tui] optional dependency extra.

## 3. tests/unit/test_html_renderer.py (new)

- [x] 3.1 Tests: HTML to Rich rendering, link post-processing, content-type detection heuristic, graceful import failure.

## 4. Cross-cutting constraints

- [x] 4.1 html2text import must be lazy with graceful ImportError — returns a 'not installed' Rich message
- [x] 4.2 Link post-processing must convert ALL markdown links to @click format for internal TUI navigation
- [x] 4.3 detect_content_type must prefer explicit content_type_header over heuristic sniffing
- [x] 4.4 body_width=0 so Rich/Textual handles wrapping, not html2text
