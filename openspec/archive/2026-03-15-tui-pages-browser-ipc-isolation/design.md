# tui-pages-browser-ipc-isolation — Design

## Spec-Derived Architecture

### tui/pages-browser-ipc

- **Page browsing must not block control-plane IPC** (added) — 1 scenarios
- **Page browsing preserves traffic-class separation** (added) — 1 scenarios
- **Page failures remain local to the browser surface** (added) — 1 scenarios

## Scope

Implement a smaller-blast-radius client-side isolation fix for page browsing:

- add a lightweight IPC lane-cloning primitive to `IPCBridge`
- have `PageBrowserWidget` lazily spawn and cache a dedicated `execution` lane for page fetches and related page operations
- keep the normal app bridge as the control/summary lane
- tear down the dedicated page lane when the widget unmounts
- verify the widget prefers the dedicated lane and the bridge can spawn sibling lanes without changing startup behavior

Out of scope for this slice:

- changing `ipc/server.py` request scheduling semantics
- introducing new priority/QoS knobs in the daemon
- expanding startup traffic or restoring per-screen caches

## File Changes

- `src/styrened/ipc/bridge.py`
  - add `traffic_class` metadata and `spawn_lane()` so callers can create sibling bridges with the same socket/timeout settings
  - improve connect/disconnect logging to include the lane class
- `src/styrened/tui/widgets/page_browser.py`
  - lazily create a dedicated `execution` bridge for page browsing
  - route page loads, form submissions, save-site, and crawl-site actions through the dedicated page lane
  - disconnect the dedicated page lane on widget unmount
- `tests/tui/services/test_ipc_bridge.py`
  - verify spawned lanes clone transport settings and expose the requested traffic class
- `tests/tui/widgets/test_page_browser.py`
  - verify page browsing spawns one dedicated execution lane, prefers it over the shared bridge, and does not disconnect the shared bridge during cleanup
