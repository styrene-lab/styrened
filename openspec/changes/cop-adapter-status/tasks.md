# COP Adapter Status — Extensible Overlay Service Health Surface — Tasks

## 1. Event bus extension + adapter registry
<!-- specs: adapter-protocol -->

- [x] 1.1 Add `adapter_changed` as 6th EventBus type in `src/styrened/services/event_bus.py`
- [x] 1.2 Create `src/styrened/services/adapter_registry.py` with AdapterState, WarmupBehavior, AdapterProtocol ABC, AdapterRegistry, AdapterStateRecord
- [x] 1.3 Tests in `tests/unit/test_adapter_registry.py`

## 2. I2PAdapter implements AdapterProtocol + daemon probe loop
<!-- specs: adapter-protocol -->

- [x] 2.1 I2PAdapter implements AdapterProtocol (display_name, short_label, warmup_behavior, probe())
- [x] 2.2 YggdrasilAdapter stub implements AdapterProtocol
- [x] 2.3 Daemon `_start_adapter_probe_loop()` + `_adapter_probe_loop()` — 30s poll, emits adapter_changed on transitions

## 3. TUI model + AdapterStatusBar widget
<!-- specs: tui-model, widget -->

- [x] 3.1 `src/styrened/tui/models/adapter_status.py` — AdapterDisplayState, AdapterStatusSnapshot, AdapterStatusTracker
- [x] 3.2 `src/styrened/tui/widgets/adapter_status_bar.py` — AdapterStatusBar(Static), apply_snapshot(), render() with per-state Rich markup
- [x] 3.3 Tests in `tests/tui/widgets/test_adapter_status_bar.py`

## 4. Dashboard wiring
<!-- specs: dashboard -->

- [x] 4.1 DashboardScreen: AdapterStatusTracker instantiated, AdapterStatusBar in compose, on_daemon_event handles ADAPTER_CHANGED
- [x] 4.2 READY→DEGRADED injects anomaly SituationLine into CopSituationTracker
- [x] 4.3 WARMING→READY / DEGRADED→READY inject informational SituationLines
- [x] 4.4 Tests extended in `tests/tui/screens/test_dashboard_tui.py`
