# I2P pages: adversarial review remediations — Design Spec (extracted)

> Auto-extracted from docs/i2p-pages-review-fixes.md at decide-time.

## Decisions

### Escape Rich markup in html2text output before link post-processing (decided)

C1 fix: html2text output can contain literal [bold], [@click=...], etc. that Text.from_markup() interprets as Rich markup. Escape all [ and ] in the raw markdown BEFORE _postprocess_links() runs, so only links we explicitly construct carry markup. Use Rich's own escape function or manual bracket replacement.

### Anchor link regex to reject image syntax ![]() (decided)

C2 fix: _MD_LINK_RE matches ![alt](url). Add negative lookbehind (?&lt;!!) to the regex so image markdown is not converted to clickable navigate_link actions.

### Rewrite .i2p URLs to localhost:4444 proxy for browser delegation (decided)

C3 fix: action_open_in_browser must rewrite http://*.i2p/* URLs to http://localhost:4444/url using the I2P HTTP proxy, not pass .i2p hostnames directly to the browser. Get proxy port from I2P adapter config if available.

### Eliminate double-fetch in action_cycle_transport (decided)

C4 fix: set_external_url() already calls run_worker(_load_page()), so action_cycle_transport must not also call it. For I2P/HTTPS branches, set _external_url and destination_hash directly, then call run_worker once. For NomadNet branch, same pattern — set fields directly, single run_worker call.

### Validate web_url scheme to https:// or http:// only (decided)

C5 fix: _validate_meta_response must reject web_url values that don't start with https:// or http://. This prevents javascript:, file:, data: URL scheme injection from malicious remote peers, which would be passed to App.open_url() when the user presses O.

### Tighten micron heuristic markers to reduce false positives (decided)

W1 fix: Single '>' and '`' are too common (blockquotes, code). Require multi-marker evidence: at least 2 distinct micron markers in the first 20 lines, or a definitive marker like #!c= or #!md that only micron uses. This avoids misrouting email quotes and markdown code fences.

### Set _last_content_kind on all render paths including structured data (decided)

W2 fix: When render_structured_page() succeeds, _last_content_kind must still be updated. Use detect_content_type(content, content_type) unconditionally before the render dispatch, not inside the 'rendered is None' branch.

### Validate ygg_port range 1-65535 (decided)

W3 fix: isinstance(int) is necessary but insufficient. Add range check 1 <= port <= 65535 in _validate_meta_response.

### Use set_mesh_device() in ExchangeScreen fresh-mount path (decided)

W4 fix: exchange.py line 641 sets browser._mesh_device directly, bypassing _active_transport initialization. Call set_mesh_device(device) on the freshly created widget before mount instead.

### Conditionally hide O binding in BINDINGS via check_action (decided)

W5/W6 fix: BINDINGS is a class variable evaluated at class definition, so show= can't use a runtime check. Instead, override check_action() on PageBrowserWidget to return False for 'open_in_browser' when _is_headless(). Textual respects check_action for both footer visibility and key handling.
