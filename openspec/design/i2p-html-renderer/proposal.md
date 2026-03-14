# TUI: html_renderer module — html2text + link post-processing

## Intent

New tui/widgets/html_renderer.py: html2text conversion with tuned options (body_width=0, ignore_images, protect_links, unicode_snob), markdown [text](url) → @click Rich markup post-processing for internal link navigation, content-type detection heuristic fallback. Add html2text to [tui] extra in pyproject.toml.

See [TUI: html_renderer module — html2text + link post-processing design doc](../../../docs/i2p-html-renderer.md) for full context.
