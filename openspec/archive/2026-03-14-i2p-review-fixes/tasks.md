# i2p-review-fixes — Tasks

> Dependencies: Groups 1 and 2 are independent. Group 3 depends on Group 1 (escaping must exist before link regex matters). Group 4 is independent.

## 1. [CRITICAL] Rich markup escaping and image link fix in html_renderer.py
<!-- specs: html-renderer-security -->

- [x] 1.1 Add `_escape_rich_markup(text: str) -> str` function that escapes `[` and `]` in raw html2text output
- [x] 1.2 In `render_html_to_rich()`: call `_escape_rich_markup()` on the html2text markdown output BEFORE `_postprocess_links()` — this means only links we explicitly construct carry active Rich markup
- [x] 1.3 Add negative lookbehind `(?<!\!)` to `_MD_LINK_RE` to reject `![alt](url)` image syntax
- [x] 1.4 Handle empty-label links `[](url)` — `_postprocess_links` should skip links where text is empty after strip
- [x] 1.5 Fix docstring line "3. Rich.Markdown renders the final markup" → "3. Rich Text.from_markup renders the final markup"
- [x] 1.6 Add tests: HTML containing `[@click="evil"]pwned[/]` renders as literal escaped text, not a click action
- [x] 1.7 Add tests: HTML containing `[bold red]text[/bold red]` renders as literal escaped text, not styled
- [x] 1.8 Add tests: `![img](url)` not matched by `_postprocess_links`, `[](url)` not matched, normal `[text](url)` still matched
- [x] 1.9 Add tests: legitimate `<a href="...">` links still produce working `navigate_link` actions after escaping

## 2. [CRITICAL] Daemon validation hardening in direct_link.py
<!-- specs: daemon-validation -->

- [x] 2.1 In `_validate_meta_response()`: add URL scheme check — `web_url` must start with `https://` or `http://` (case-insensitive); reject otherwise
- [x] 2.2 In `_validate_meta_response()`: add port range check — `ygg_port` must be `1 <= port <= 65535`; reject otherwise
- [x] 2.3 Add tests: `web_url` with `javascript:`, `file:///`, `data:text/html,...` schemes all rejected
- [x] 2.4 Add tests: `web_url` with `https://` and `http://` accepted, empty string still excluded
- [x] 2.5 Add tests: `ygg_port` -1, 0, 65536, 99999 rejected; 1, 443, 9002, 65535 accepted

## 3. Micron heuristic tightening in html_renderer.py
<!-- specs: html-renderer-security -->

- [x] 3.1 Split `_MICRON_MARKERS` into `_DEFINITIVE_MARKERS` (`#!c=`, `#!md`, `-=-`) and `_AMBIGUOUS_MARKERS` (`>`, backtick, `-=`)
- [x] 3.2 Rewrite heuristic logic: any definitive marker → MICRON immediately; ambiguous markers require ≥2 distinct types in first 20 lines
- [x] 3.3 Add tests: email quote (`> On Tuesday...`) → PLAIN, code fence (triple backtick) → PLAIN, single `>` line → PLAIN
- [x] 3.4 Add tests: `#!c=3600` → MICRON, `#!md` → MICRON, `-=-` → MICRON (definitive markers alone suffice)
- [x] 3.5 Add tests: `>Title` + `-= separator =-` → MICRON (2 distinct ambiguous markers)
- [x] 3.6 Verify existing heuristic tests still pass (header-takes-precedence, case-insensitive, etc.)

## 4. Transport selector fixes in page_browser.py
<!-- specs: transport-browser -->

- [x] 4.1 Fix `action_cycle_transport()` I2P/HTTPS branches: set `self._external_url`, `self.destination_hash`, `self._history` directly instead of calling `set_external_url()` — then single `run_worker(_load_page())` call
- [x] 4.2 Fix `action_open_in_browser()` .i2p rewrite: extract path from parsed URL, construct `http://localhost:4444/{original_url}` for browser
- [x] 4.3 Move `detect_content_type()` call in `_load_page()` before the render dispatch — set `_last_content_kind` unconditionally (even when structured renderer used)
- [x] 4.4 Add `check_action()` override to return `False` for `"open_in_browser"` when `_is_headless()` returns `True`
- [x] 4.5 Fix ExchangeScreen `exchange.py`: replace `browser._mesh_device = device` with `browser.set_mesh_device(device)` in fresh-mount path
- [x] 4.6 Add tests: .i2p URL rewritten to localhost:4444 proxy, HTTPS URL unchanged, NomadNet path shows info notification
- [x] 4.7 Add tests: `check_action("open_in_browser")` returns False on headless, True on macOS/display-available
- [x] 4.8 Add tests: `_last_content_kind` updated even when structured data renderer used
