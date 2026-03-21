# TUI: Transport selector and browser delegation in PageBrowserWidget — Tasks

## 1. src/styrened/tui/widgets/page_browser.py (modified)

- [x] 1.1 In _load_page(): use detect_content_type + dispatch to html_renderer or micron_parser. Add _available_transports list property computed from MeshDevice fields. Add _active_transport enum. T binding cycles transports and re-fetches. O binding delegates to App.open_url() with headless guard. URL bar shows transport + content-type indicators.

## 2. src/styrened/tui/screens/exploration.py (modified)

- [x] 2.1 Pass MeshDevice reference to PageBrowserWidget when node selected, so transport selector knows available endpoints.

## 3. src/styrened/tui/screens/exchange.py (modified)

- [x] 3.1 Same MeshDevice pass-through for transport selector.

## 4. tests/tui/widgets/test_page_browser_transport.py (new)

- [x] 4.1 Tests: transport cycling, headless detection, content-type dispatch.

## 5. Cross-cutting constraints

- [x] 5.1 T cycle must only show transports actually declared by the node (nomadnet_destination_hash, b32_address, https_url)
- [x] 5.2 O binding hidden when headless detected via SSH_CONNECTION / no DISPLAY / no WAYLAND_DISPLAY
- [x] 5.3 For .i2p URLs opened in browser, construct http://localhost:4444/{path} proxy URL
- [x] 5.4 Transport change must clear history and re-fetch from root path of new transport
