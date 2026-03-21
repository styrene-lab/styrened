# TUI: Transport selector and browser delegation in PageBrowserWidget — Design

## Architecture Decisions

### Decision: Transport selector and browser delegation implemented

**Status:** decided
**Rationale:** Transport enum with T cycling (clears history, re-fetches root), O browser delegation with headless detection, content-type dispatch in _load_page(), set_mesh_device wired from both ExplorationScreen and ExchangeScreen, URL bar shows transport + content-type indicators. 25 tests in test_page_browser_transport.py all pass.

## File Changes

- `src/styrened/tui/widgets/page_browser.py` (modified) — In _load_page(): use detect_content_type + dispatch to html_renderer or micron_parser. Add _available_transports list property computed from MeshDevice fields. Add _active_transport enum. T binding cycles transports and re-fetches. O binding delegates to App.open_url() with headless guard. URL bar shows transport + content-type indicators.
- `src/styrened/tui/screens/exploration.py` (modified) — Pass MeshDevice reference to PageBrowserWidget when node selected, so transport selector knows available endpoints.
- `src/styrened/tui/screens/exchange.py` (modified) — Same MeshDevice pass-through for transport selector.
- `tests/tui/widgets/test_page_browser_transport.py` (new) — Tests: transport cycling, headless detection, content-type dispatch.

## Constraints

- T cycle must only show transports actually declared by the node (nomadnet_destination_hash, b32_address, https_url)
- O binding hidden when headless detected via SSH_CONNECTION / no DISPLAY / no WAYLAND_DISPLAY
- For .i2p URLs opened in browser, construct http://localhost:4444/{path} proxy URL
- Transport change must clear history and re-fetch from root path of new transport
