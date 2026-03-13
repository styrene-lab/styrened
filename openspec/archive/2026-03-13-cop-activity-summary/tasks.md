# COP Activity Summary Widget — Tasks

> All groups complete. See commit on feature/cop-activity-summary.

## Group 1: Daemon — EventBus emit sites ✅ pre-existing

All emit sites were already wired via `_NOTIFICATION_TO_BUS` + `_bridge_to_event_bus()`
in `daemon.py`. No daemon changes were needed.

- [x] 1.1 `file_offer` → `message_changed/file_offer`
- [x] 1.2 `file_complete` → `message_changed/file_complete`
- [x] 1.3 `pqc_established` → `link_changed/pqc_established`
- [x] 1.4 `pqc_rekey` → `link_changed/pqc_rekey`
- [x] 1.5 `discovered_via` present in `node_changed/announced` emit payload

## Group 2: CopSituationTracker ✅

- [x] 2.1 `src/styrened/tui/models/cop_situation.py` — `SituationPriority`,
  `SituationLine`, `CopSituationSnapshot`, `_TRANSPORT_LABELS`, `transport_label()`,
  `CopSituationTracker` with `ingest(DaemonEvent)`, `update_from_state()`, `snapshot()`

## Group 3: CopActivitySummary — presentation-only ✅

- [x] 3.1 `src/styrened/tui/widgets/cop_activity_summary.py` rewritten as
  presentation-only `Widget` with `apply_snapshot()` and `render()`. No internal state,
  no bridge access, no `update_from_state`/`add_ephemeral` API.
- [x] 3.2 `transport_label` re-exported from widget for import compatibility

## Group 4: DashboardScreen wiring ✅

- [x] 4.1 `_situation_tracker: CopSituationTracker` instantiated in `__init__`
- [x] 4.2 `on_daemon_event()` — calls `tracker.ingest(event)` + `apply_snapshot()` on
  widget immediately (fast path for file/PQC events; store-backed events still
  debounce-trigger poll refresh)
- [x] 4.3 `_fetch_daemon_status()` — calls `tracker.update_from_state()` then
  `apply_snapshot()` (replaces old direct `update_from_state()` on widget)
- [x] 4.4 `_subscribe_activity()` — removed `add_ephemeral()` call; `DaemonEvent` post
  now routes through `on_daemon_event` which handles tracker + snapshot
- [x] 4.5 `action_refresh()` — resets tracker and pushes empty snapshot

## Group 5: Tests ✅

- [x] 5.1 `transport_label()` — 15 parametrized cases
- [x] 5.2 `CopSituationTracker.update_from_state()` — discovery, anomaly, unread, hub
- [x] 5.3 `CopSituationTracker.ingest()` — file_offer, file_complete, pqc_established,
  pqc_rekey, 10 ignored event/action combinations
- [x] 5.4 Ephemeral cap (4), dim after 10m, drop after 30m
- [x] 5.5 Priority ordering, 6-line cap
- [x] 5.6 `update_from_state` replaces (stateless), anomaly clears on recovery
- [x] 5.7 `CopActivitySummary.apply_snapshot()` — render output, replacement
- [x] 5.8 Dashboard: `on_daemon_event` routes to tracker → snapshot (not `add_ephemeral`)
- [x] 5.9 Dashboard: subscription posts `DaemonEvent`, no longer calls `add_ephemeral`
- [x] 5.10 `test_dashboard_tui.py` updated for new routing model

**Total: 99 tests passing (57 new + 19 dashboard + 23 event bus)**
