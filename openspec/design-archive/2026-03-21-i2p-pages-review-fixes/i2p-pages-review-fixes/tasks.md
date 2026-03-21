# I2P pages: adversarial review remediations — Tasks

## 1. src/styrened/tui/widgets/html_renderer.py (modified)

- [x] 1.1 C1: Add _escape_rich_markup() that escapes [ and ] before _postprocess_links. C2: Add negative lookbehind to _MD_LINK_RE. W1: Tighten _MICRON_MARKERS — require 2+ distinct markers or definitive-only markers (#!c=, #!md). N1: Fix docstring to say Text.from_markup, not Rich.Markdown.

## 2. src/styrened/tui/widgets/page_browser.py (modified)

- [x] 2.1 C3: Rewrite .i2p URLs to localhost:4444 proxy in action_open_in_browser. C4: Don't call set_external_url() in action_cycle_transport — set fields directly, single run_worker. W2: Move detect_content_type call before render dispatch so _last_content_kind is set unconditionally. W5/W6: Add check_action override to hide O binding on headless.

## 3. src/styrened/services/direct_link.py (modified)

- [x] 3.1 C5: Reject web_url without https:// or http:// prefix. W3: Add 1-65535 range check for ygg_port.

## 4. src/styrened/tui/screens/exchange.py (modified)

- [x] 4.1 W4: Replace browser._mesh_device = device with browser.set_mesh_device(device) in fresh-mount path.

## 5. tests/unit/test_html_renderer.py (modified)

- [x] 5.1 O1: Add Rich markup injection tests ([@click=...], [bold], etc. in HTML). O2: Add image link ![alt](url) non-matching tests.

## 6. tests/unit/test_page_browser_transport.py (modified)

- [x] 6.1 O2/O3: Add tests for action_cycle_transport (single fetch, not double), action_open_in_browser .i2p proxy rewrite. O5: Add web_url scheme rejection tests.

## 7. tests/unit/test_page_content_type.py (modified)

- [x] 7.1 O5: Add _validate_meta_response tests for javascript:, file:, data: scheme rejection. W3: Add ygg_port range tests.

## 8. Cross-cutting constraints

- [x] 8.1 C1 is a security vulnerability — Rich markup injection from untrusted HTML content. Must be fixed before any release that includes html_renderer.
- [x] 8.2 All remediation tests must pass before the node can be marked decided.
- [x] 8.3 Do not regress the 3512 existing passing tests.
- [x] 8.4 The heuristic tightening (W1) must not break detection of real NomadNet micron pages — test with actual micron content from hub.
