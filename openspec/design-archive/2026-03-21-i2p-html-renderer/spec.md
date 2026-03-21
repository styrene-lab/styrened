# TUI: html_renderer module — html2text + link post-processing — Design Spec (extracted)

> Auto-extracted from docs/i2p-html-renderer.md at decide-time.

## Decisions

### html_renderer module implemented (decided)

tui/widgets/html_renderer.py created with render_html_to_rich(), detect_content_type(), _postprocess_links(). html2text>=2024.2.26 added to [tui] extra. 35 tests in test_html_renderer.py all pass.
