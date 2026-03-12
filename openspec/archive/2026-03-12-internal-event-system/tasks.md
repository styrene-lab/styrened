# Internal Event System — Tasks

## 1. src/styrened/services/event_bus.py (new)

- [x] 1.1 EventBus class — subscribe/unsubscribe/emit with logging escalation (TRACE→ERROR)
- [x] 1.2 Auto-removal after 5 consecutive failures, recovery tracking
- [x] 1.3 Slow subscriber warning (>500ms), stats/diagnostics

## 2. src/styrened/daemon.py (modified)

- [x] 2.1 Create EventBus instance in __init__, emit node_changed from _on_device_discovered
- [x] 2.2 _bridge_to_event_bus() translates notification types → coarse bus types
- [x] 2.3 Wire all 5 event types: node_changed, message_changed, hub_changed, link_changed, config_changed
- [x] 2.4 _NOTIFICATION_TO_BUS class-level mapping dict

## 3. src/styrened/ipc/handlers.py (modified)

- [x] 3.1 Emit config_changed/saved from SAVE_CORE_CONFIG handler

## 4. src/styrened/tui/models/events.py (new)

- [x] 4.1 DaemonEvent Textual Message class with event_type, action, data

## 5. src/styrened/tui/screens/dashboard.py (modified)

- [x] 5.1 Post DaemonEvent from activity subscription via _ipc_type_to_bus_type mapping
- [x] 5.2 Handle DaemonEvent for instant refresh (node/message/hub)
- [x] 5.3 60s reconciliation timer as belt-and-suspenders
- [x] 5.4 5s debounce on event-driven refreshes
- [x] 5.5 call_after_refresh + refresh_bindings for Footer rendering

## 6. src/styrened/tui/screens/exploration.py (modified)

- [x] 6.1 Handle DaemonEvent/node_changed → _start_node_refresh()
- [x] 6.2 Polling slowed from 15s → 60s
- [x] 6.3 Refresh countdown ⟳ Ns in status bar
- [x] 6.4 5s debounce on event-driven refreshes
- [x] 6.5 Retry with backoff in _async_load_all_nodes (3 attempts, 1s/2s/4s)
- [x] 6.6 Silent except→debug logging in async workers

## 7. tests/unit/test_event_bus.py (new)

- [x] 7.1 Core: subscribe, emit, unsubscribe, fan-out, isolation, duplicate ignore
- [x] 7.2 Auto-removal after max consecutive failures
- [x] 7.3 Failure count reset on success, recovery logged at INFO
- [x] 7.4 Slow subscriber warning logged at WARNING
- [x] 7.5 Stats, emit counts, log_summary
- [x] 7.6 TRACE-level payload and dispatch timing
- [x] 7.7 _NOTIFICATION_TO_BUS mapping coverage (all 5 bus types)

## 8. Theme/Chrome fixes (discovered during verification)

- [x] 8.1 Remove border-top/border-bottom from Footer/Header (ate content height to 0px)
- [x] 8.2 Let theme variables control Footer background (footer-background, footer-key-foreground)
- [x] 8.3 _ensure_chrome_contrast() auto-nudges footer bg away from screen bg (OKLCH delta ≥ 0.06)

## 9. Cross-cutting constraints

- [x] 9.1 EventBus is pure asyncio — no external dependencies
- [x] 9.2 emit() never blocks caller (create_task fan-out)
- [x] 9.3 One subscriber exception does not kill others
- [x] 9.4 Existing IPC activity subscription preserved during migration
- [x] 9.5 Python 3.11 compatible (from __future__ import annotations)
