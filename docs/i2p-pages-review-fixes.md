---
id: i2p-pages-review-fixes
title: "I2P pages: adversarial review remediations"
status: exploring
parent: i2p-pages-strategy
dependencies: [i2p-transport-selector]
tags: [security, bug, tui, daemon]
open_questions: []
---

# I2P pages: adversarial review remediations

## Overview

Fixes for 5 critical issues, 6 warnings, and 5 omissions found during adversarial assessment of the i2p-daemon-content-type, i2p-html-renderer, and i2p-transport-selector implementations. Covers Rich markup injection, image link false matching, .i2p proxy URL construction, double-fetch race, URL scheme validation, micron heuristic false positives, stale content-type indicator, port validation, ExchangeScreen init bypass, and headless binding visibility.

## Decisions

### Decision: Escape Rich markup in html2text output before link post-processing

**Status:** decided
**Rationale:** C1 fix: html2text output can contain literal [bold], [@click=...], etc. that Text.from_markup() interprets as Rich markup. Escape all [ and ] in the raw markdown BEFORE _postprocess_links() runs, so only links we explicitly construct carry markup. Use Rich's own escape function or manual bracket replacement.

### Decision: Anchor link regex to reject image syntax ![]()

**Status:** decided
**Rationale:** C2 fix: _MD_LINK_RE matches ![alt](url). Add negative lookbehind (?&lt;!!) to the regex so image markdown is not converted to clickable navigate_link actions.

### Decision: Rewrite .i2p URLs to localhost:4444 proxy for browser delegation

**Status:** decided
**Rationale:** C3 fix: action_open_in_browser must rewrite http://*.i2p/* URLs to http://localhost:4444/url using the I2P HTTP proxy, not pass .i2p hostnames directly to the browser. Get proxy port from I2P adapter config if available.

### Decision: Eliminate double-fetch in action_cycle_transport

**Status:** decided
**Rationale:** C4 fix: set_external_url() already calls run_worker(_load_page()), so action_cycle_transport must not also call it. For I2P/HTTPS branches, set _external_url and destination_hash directly, then call run_worker once. For NomadNet branch, same pattern — set fields directly, single run_worker call.

### Decision: Validate web_url scheme to https:// or http:// only

**Status:** decided
**Rationale:** C5 fix: _validate_meta_response must reject web_url values that don't start with https:// or http://. This prevents javascript:, file:, data: URL scheme injection from malicious remote peers, which would be passed to App.open_url() when the user presses O.

### Decision: Tighten micron heuristic markers to reduce false positives

**Status:** decided
**Rationale:** W1 fix: Single '>' and '`' are too common (blockquotes, code). Require multi-marker evidence: at least 2 distinct micron markers in the first 20 lines, or a definitive marker like #!c= or #!md that only micron uses. This avoids misrouting email quotes and markdown code fences.

### Decision: Set _last_content_kind on all render paths including structured data

**Status:** decided
**Rationale:** W2 fix: When render_structured_page() succeeds, _last_content_kind must still be updated. Use detect_content_type(content, content_type) unconditionally before the render dispatch, not inside the 'rendered is None' branch.

### Decision: Validate ygg_port range 1-65535

**Status:** decided
**Rationale:** W3 fix: isinstance(int) is necessary but insufficient. Add range check 1 <= port <= 65535 in _validate_meta_response.

### Decision: Use set_mesh_device() in ExchangeScreen fresh-mount path

**Status:** decided
**Rationale:** W4 fix: exchange.py line 641 sets browser._mesh_device directly, bypassing _active_transport initialization. Call set_mesh_device(device) on the freshly created widget before mount instead.

### Decision: Conditionally hide O binding in BINDINGS via check_action

**Status:** decided
**Rationale:** W5/W6 fix: BINDINGS is a class variable evaluated at class definition, so show= can't use a runtime check. Instead, override check_action() on PageBrowserWidget to return False for 'open_in_browser' when _is_headless(). Textual respects check_action for both footer visibility and key handling.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/html_renderer.py` (modified) — C1: Add _escape_rich_markup() that escapes [ and ] before _postprocess_links. C2: Add negative lookbehind to _MD_LINK_RE. W1: Tighten _MICRON_MARKERS — require 2+ distinct markers or definitive-only markers (#!c=, #!md). N1: Fix docstring to say Text.from_markup, not Rich.Markdown.
- `src/styrened/tui/widgets/page_browser.py` (modified) — C3: Rewrite .i2p URLs to localhost:4444 proxy in action_open_in_browser. C4: Don't call set_external_url() in action_cycle_transport — set fields directly, single run_worker. W2: Move detect_content_type call before render dispatch so _last_content_kind is set unconditionally. W5/W6: Add check_action override to hide O binding on headless.
- `src/styrened/services/direct_link.py` (modified) — C5: Reject web_url without https:// or http:// prefix. W3: Add 1-65535 range check for ygg_port.
- `src/styrened/tui/screens/exchange.py` (modified) — W4: Replace browser._mesh_device = device with browser.set_mesh_device(device) in fresh-mount path.
- `tests/unit/test_html_renderer.py` (modified) — O1: Add Rich markup injection tests ([@click=...], [bold], etc. in HTML). O2: Add image link ![alt](url) non-matching tests.
- `tests/unit/test_page_browser_transport.py` (modified) — O2/O3: Add tests for action_cycle_transport (single fetch, not double), action_open_in_browser .i2p proxy rewrite. O5: Add web_url scheme rejection tests.
- `tests/unit/test_page_content_type.py` (modified) — O5: Add _validate_meta_response tests for javascript:, file:, data: scheme rejection. W3: Add ygg_port range tests.

### Constraints

- C1 is a security vulnerability — Rich markup injection from untrusted HTML content. Must be fixed before any release that includes html_renderer.
- All remediation tests must pass before the node can be marked decided.
- Do not regress the 3512 existing passing tests.
- The heuristic tightening (W1) must not break detection of real NomadNet micron pages — test with actual micron content from hub.
