# tui-device-cache-regression-fixes — Design

## Spec-Derived Architecture

### tui/device-cache

- **Cache-backed node consumers tolerate unprimed cache state** (added) — preserve a single shared DeviceCache while allowing consumers to fall back when the cache exists but has not yet been populated.
- **Bare-screen or test contexts do not report false daemon disconnects** (added) — separate bridge failure from app/cache lookup failure so dashboard status wiring stays honest.
- **Startup and navigation tests reflect current Home and splash ownership** (added) — update tests to the intentional splash-first startup contract and the Home-versus-Nodes split.

## Scope

In scope:
- Runtime fixes in `DashboardScreen`, `ExplorationScreen`, and `MeshDeviceDetailScreen`
- Regression tests for empty/unprimed cache behavior and dashboard status wiring
- Test reconciliation for splash-first startup and removal of legacy dashboard-owned peer tree assumptions

Out of scope:
- Reintroducing per-screen caches as primary data sources
- Restoring dashboard-owned peer browsing to satisfy outdated tests
- Removing the splash screen or reverting the Home/Nodes ownership model

## File Changes

- `src/styrened/tui/screens/dashboard.py` — add `_get_cached_devices()` helper and keep status refresh robust in unit / bare-screen contexts
- `src/styrened/tui/screens/exploration.py` — treat empty cache as unprimed, fall back to `discover_devices()`, and keep resume behavior testable without a mounted app
- `src/styrened/tui/screens/mesh_device_detail.py` — preserve live-device fallback when the shared cache is present but empty
- `tests/tui/screens/test_dashboard_tui.py` — cover cache-backed dashboard status reads and avoid un-awaited adapter worker warnings in resume tests
- `tests/tui/screens/test_exploration.py` — replace stale pre-migration expectations with current Nodes workspace behavior and cache-backed fixtures
- `tests/tui/screens/test_device_detail_tui.py` — verify peer detail fallback semantics with empty and populated cache states
- `tests/tui/widgets/test_cop_activity_summary.py` — assert activity subscription posts `DaemonEvent` via the screen's message path
- `tests/tui/test_app.py` — expect `SplashScreen` first and isolate operator-identity filesystem state
- `tests/tui/test_navigation_workflows.py` — remove imports of retired dashboard tree symbols and align navigation tests to the current architecture
- `tests/tui/integration/test_chat_dashboard_flow.py` — remove imports of retired dashboard tree symbols and keep integration coverage focused on dashboard-to-peer-workspace flow
