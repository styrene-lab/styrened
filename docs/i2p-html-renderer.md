---
id: i2p-html-renderer
title: "TUI: html_renderer module — html2text + link post-processing"
status: exploring
parent: i2p-pages-strategy
dependencies: [i2p-daemon-content-type]
tags: [tui, rendering, html2text]
open_questions: []
---

# TUI: html_renderer module — html2text + link post-processing

## Overview

New tui/widgets/html_renderer.py: html2text conversion with tuned options (body_width=0, ignore_images, protect_links, unicode_snob), markdown [text](url) → @click Rich markup post-processing for internal link navigation, content-type detection heuristic fallback. Add html2text to [tui] extra in pyproject.toml.

## Decisions

### Decision: html_renderer module implemented

**Status:** decided
**Rationale:** tui/widgets/html_renderer.py created with render_html_to_rich(), detect_content_type(), _postprocess_links(). html2text>=2024.2.26 added to [tui] extra. 35 tests in test_html_renderer.py all pass.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/html_renderer.py` (new) — New module with: render_html_to_rich(html_str) -> Rich renderable using html2text + link post-processing; detect_content_type(content, content_type_header) -> enum ContentKind {MICRON, HTML, PLAIN}; _postprocess_links(markdown) converts [text](url) to @click Rich markup.
- `pyproject.toml` (modified) — Add 'html2text>=2024.2.26' to [tui] optional dependency extra.
- `tests/unit/test_html_renderer.py` (new) — Tests: HTML to Rich rendering, link post-processing, content-type detection heuristic, graceful import failure.

### Constraints

- html2text import must be lazy with graceful ImportError — returns a 'not installed' Rich message
- Link post-processing must convert ALL markdown links to @click format for internal TUI navigation
- detect_content_type must prefer explicit content_type_header over heuristic sniffing
- body_width=0 so Rich/Textual handles wrapping, not html2text
