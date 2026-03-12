# Internal Event System — Tasks

## 1. src/styrened/services/event_bus.py (new)

- [ ] 1.1 EventBus class — subscribe/unsubscribe/emit, ~80 lines

## 2. src/styrened/daemon.py (modified)

- [ ] 2.1 Create EventBus instance, wire node_changed emit into _on_device_discovered, pass bus to IPC server

## 3. src/styrened/ipc/server.py (modified)

- [ ] 3.1 Subscribe to bus events, bridge to CMD_ACTIVITY_EVENT for connected clients

## 4. src/styrened/tui/models/events.py (new)

- [ ] 4.1 DaemonEvent Textual Message class for TUI-side event handling

## 5. src/styrened/tui/services/ipc_bridge.py (modified)

- [ ] 5.1 On activity event received, post DaemonEvent message to app

## 6. src/styrened/tui/screens/dashboard.py (modified)

- [ ] 6.1 Handle DaemonEvent for instant COP/table updates, slow poll to 60s

## 7. src/styrened/tui/screens/exploration.py (modified)

- [ ] 7.1 Handle DaemonEvent for instant table refresh, slow poll to 60s

## 8. tests/unit/test_event_bus.py (new)

- [ ] 8.1 EventBus unit tests — subscribe, emit, unsubscribe, fan-out, error isolation

## 9. Cross-cutting constraints

- [ ] 9.1 EventBus must be pure asyncio — no external dependencies
- [ ] 9.2 emit() must never block the caller (create_task fan-out)
- [ ] 9.3 One subscriber exception must not kill other subscribers
- [ ] 9.4 Existing IPC activity subscription must keep working during migration
- [ ] 9.5 Python 3.11 compatible (from __future__ import annotations)
