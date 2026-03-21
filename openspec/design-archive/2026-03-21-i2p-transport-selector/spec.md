# TUI: Transport selector and browser delegation in PageBrowserWidget — Design Spec (extracted)

> Auto-extracted from docs/i2p-transport-selector.md at decide-time.

## Decisions

### Transport selector and browser delegation implemented (decided)

Transport enum with T cycling (clears history, re-fetches root), O browser delegation with headless detection, content-type dispatch in _load_page(), set_mesh_device wired from both ExplorationScreen and ExchangeScreen, URL bar shows transport + content-type indicators. 25 tests in test_page_browser_transport.py all pass.
