# tui-startup-ipc-backpressure-fix — Design

## Spec-Derived Architecture

### tui/startup-ipc

- **Home first paint does not wait for bulk hydration** (added) — 0 scenarios
- **Home distinguishes degraded IPC pressure from disconnect** (added) — 0 scenarios
- **Shared DeviceCache primes after first paint** (added) — 0 scenarios
- **Home uses cheaper unread hydration than full conversation enumeration** (added) — 0 scenarios

## Scope

In scope:
- Stage shared `DeviceCache` startup so bulk fleet hydration begins after first paint.
- Keep Home status refresh on cheap summary IPC calls (`get_status`, `get_hub_status`, `get_unread_counts`).
- Surface degraded/backpressured IPC separately from a hard disconnect.
- Preserve Home as a summary surface and continue using the shared app-level cache for richer fleet detail.

Out of scope:
- New IPC summary endpoints.
- Global COP feature work.
- Web UI expansion.

## File Changes

- `src/styrened/tui/app.py` — stop starting `DeviceCache` during service initialization; start it after the initial screen paint.
- `src/styrened/tui/services/device_cache.py` — schedule delayed priming after first refresh rather than issuing the first bulk fetch immediately.
- `src/styrened/tui/screens/dashboard.py` — remove conversation/config fan-out from Home refresh, use unread-count summary, trigger background cache priming, and fall back to cheap status counts when cache detail is not ready yet.
- `src/styrened/tui/widgets/home_status_bar.py` — add a distinct backpressured IPC rendering path.
- `tests/tui/test_app.py` — verify staged cache startup behavior.
- `tests/tui/screens/test_dashboard_tui.py` — verify connected-vs-degraded behavior and cache-prime fallback behavior.
- `tests/tui/widgets/test_home_status_bar.py` — verify backpressured IPC rendering is distinct from disconnected.
