# tui-pages-browser-ipc-isolation — Tasks

## 1. Page browsing must not block control-plane IPC

- [x] 1.1 Slow page fetch does not stall shared control requests
- [x] 1.2 Write tests for Page browsing must not block control-plane IPC

## 2. Page browsing preserves traffic-class separation

- [x] 2.1 Page browser uses a dedicated long-running lane
- [x] 2.2 Write tests for Page browsing preserves traffic-class separation

## 3. Page failures remain local to the browser surface

- [x] 3.1 Page timeout remains local to the browser
- [x] 3.2 Write tests for Page failures remain local to the browser surface

## Verification notes

- Targeted tests passed:
  - `.venv/bin/python -m pytest tests/tui/widgets/test_page_browser.py tests/tui/services/test_ipc_bridge.py tests/tui/screens/test_exploration.py -q`
  - `101 passed`
- Live probe against the dev daemon confirmed the intended isolation:
  - control lane `get_status()` returned immediately while a stale-node page fetch continued on a spawned `execution` lane
