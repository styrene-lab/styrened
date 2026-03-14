## Result

**Status:** SUCCESS

**Summary:** Refactored Home startup refresh to use cheap summary IPC for first paint, switched unread hydration from full conversation enumeration to unread-count summaries, and separated degraded/backpressured IPC from hard disconnects in the Home status bar.

**Artifacts:**
- `src/styrened/tui/screens/dashboard.py` — first-paint refresh now relies on `get_status()`, `get_hub_status()`, and `get_unread_counts()`; background device-cache priming is kicked off when cache is empty; unread-summary failures mark IPC as backpressured without forcing disconnect
- `src/styrened/tui/widgets/home_status_bar.py` — added distinct `ipc_backpressured` state and rendering (`IPC ◐ ...`) separate from disconnected (`IPC ○`)
- `tests/tui/screens/test_dashboard_tui.py` — updated status wiring tests for unread summary hydration, degraded-vs-disconnected behavior, and async device-cache priming
- `tests/tui/widgets/test_home_status_bar.py` — added coverage for the new backpressured IPC indicator

**Decisions Made:**
- Treat daemon liveness as driven only by cheap status/hub IPC calls; unread hydration and cache priming are non-critical follow-up paths
- Use `get_unread_counts()` instead of `get_conversations()` for Home summary state so slow conversation enumeration cannot stall first paint
- Prime `DeviceCache` in the background when empty instead of blocking Home status refresh on a bulk device fetch

**Assumptions:**
- An empty shared `DeviceCache` during startup means “not primed yet” often enough to justify opportunistic background refresh
- `get_unread_counts()` may return either `{counts: ...}` or a raw mapping, so Home accepts both shapes defensively

**Interfaces Published:**
- `HomeStatusBar.ipc_backpressured` reactive flag for degraded/backpressured IPC rendering

**Verification:**
- Command: `python3 -m pytest tests/tui/widgets/test_home_status_bar.py tests/tui/screens/test_dashboard_tui.py -q`
- Output: `42 passed in 6.38s`
- Command: `python3 -m py_compile src/styrened/tui/screens/dashboard.py src/styrened/tui/widgets/home_status_bar.py tests/tui/screens/test_dashboard_tui.py tests/tui/widgets/test_home_status_bar.py`
- Output: `(no output)`
- Command: `mypy .`
- Output: `Failed with 482 pre-existing repository-wide errors, including existing failures in src/styrened/ipc/bridge.py, src/styrened/tui/widgets/glitch_logo.py, src/styrened/tui/screens/settings.py, and many test modules outside this task scope. Scoped dashboard/home-status changes were validated with targeted pytest and py_compile, but the required repo-wide mypy gate is not currently green in this worktree.`
- Edge cases: unread-summary IPC failure after successful daemon status; empty/unprimed device cache on first Home paint; repeated device-cache updates triggering Home refresh without blocking initial status render
