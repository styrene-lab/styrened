---
id: internal-event-system
title: Internal Event System
status: implemented
tags: [architecture, daemon, tui, ipc]
open_questions: []
branches: ["feature/internal-event-system"]
openspec_change: internal-event-system
---

# Internal Event System

## Overview

Styrened lacks a unified internal event bus. When something happens in the daemon (node announce received, message delivered, hub status change, link established, adapter state change), there is no canonical way to propagate that fact to all interested consumers. This leads to:

1. **Polling everywhere** — Dashboard polls IPC every N seconds, exploration screen polls separately, COP summary re-derives state each tick. All doing redundant work, all with latency gaps.

2. **Shadow state proliferation** — `_live_nodes_cache`, `_stored_nodes_cache`, ephemeral event lists, dedup sets. Each consumer builds its own view of truth because there's no shared event stream.

3. **Missed events** — COP originally couldn't see nodes discovered before TUI connected. Exploration screen counters show "0 active" while table has data. Status bar lags behind reality.

4. **Fragile wiring** — One-off callbacks (`_on_device_discovered`), activity subscription over IPC that's separate from device queries, `ingest_event` vs `update_from_state` confusion.

5. **IPC as the only event path** — TUI gets events only through IPC subscription, which is a serialized socket protocol with its own failure modes. Internal daemon services have no event mechanism at all — they call each other directly or not at all.

The fix is a proper publish-subscribe event bus internal to the daemon process, with IPC as one subscriber that bridges events to external consumers (TUI, CLI, web API). Daemon services publish typed events; the TUI subscribes to event streams rather than polling for state snapshots.

## Research

### Current event propagation audit

**Daemon side:**
- `StyreneAnnounceHandler.received_announce()` → writes to NodeStore (SQLite) → calls `_on_device_discovered()` callback → fires IPC activity event
- Hub connection state → stored in `HubConnection` instance → polled by IPC `get_hub_status()`
- LXMF messages → `LXMFService` callback chain → written to message DB → fires IPC activity event
- Adapter state (I2P/Ygg) → stored in service instance attributes → polled by IPC
- No internal pub/sub — services call daemon methods directly or not at all

**IPC layer:**
- Request/response for state queries (`get_devices`, `get_hub_status`, `get_conversations`)
- Activity subscription stream (separate IPC command) pushes `device_discovered`, `message_received`, `announce_sent` etc.
- Activity events are fire-and-forget — no replay, no sequence numbers, no catch-up
- TUI must both poll AND subscribe to get complete picture

**TUI side:**
- Dashboard: polls every 5s via `_poll_daemon()`, also subscribes to activity stream for COP ephemeral events
- Exploration screen: polls every 15s via `_refresh_via_bridge()`, caches in `_live_nodes_cache`
- Each screen builds its own `MeshDevice` list from `DeviceInfo` objects — redundant conversion
- Status bar, node table, COP summary, tab labels all need updating but trigger independently
- `except Exception: pass` in async workers silently swallows propagation failures

**Symptoms fixed so far (all event-related):**
1. COP missed discoveries before TUI connected → rewrote as stateless/poll-derived
2. Dashboard DeviceInfo→MeshDevice conversion failing silently → fixed isinstance checks
3. Exploration counter showing 0 while table populated → timing race between async load and render
4. `ingest_event()` vs `update_from_state()` confusion → removed event ingestion entirely for store-backed data

### Existing patterns in the codebase that approximate events

1. **IPC activity subscription** (`CMD_SUBSCRIBE_ACTIVITY` / `CMD_ACTIVITY_EVENT`) — closest thing to an event stream. Daemon pushes dicts like `{"type": "device_discovered", "name": "...", "destination_hash": "..."}`. Untyped, no schema, no versioning.

2. **Textual message system** — `self.post_message(SomeMessage(...))` within the TUI process. Already used for widget-to-screen communication (e.g., `HomeNodeSummaryTable.NodeSelected`). This is the TUI-internal event bus but only covers widget interactions, not daemon events.

3. **Direct callbacks** — `start_discovery(callback=self._on_device_discovered)` in the exploration screen. One subscriber per callback, no fan-out.

4. **`asyncio.Event` flags** — Used in tests and some service coordination but not for event propagation.

5. **`signal` module** — Not used. Python signals are process-level, not suitable for in-process pub/sub.

The Textual message system is the closest model for what we want on the daemon side — typed messages, multiple handlers, bubbling/routing. But it's tied to the Textual DOM tree.

## Decisions

### Decision: Simple observer pattern on daemon — not a framework

**Status:** decided
**Rationale:** Single EventBus instance (~100 lines), dict of {event_type: [async_callbacks]}, emit fans out via asyncio.create_task. No queues, no broker, no middleware. It's a dict and a for loop.

### Decision: Notification events with minimal payload — stores remain source of truth

**Status:** decided
**Rationale:** Events carry type + identity key + small metadata dict. Consumers re-read from NodeStore/message DB if they need full state. Keeps emit cheap — an announce handler shouldn't block on serializing a full MeshDevice for N subscribers.

### Decision: Five coarse event types — split later if needed

**Status:** decided
**Rationale:** node_changed, message_changed, hub_changed, link_changed, config_changed. Each carries an 'action' field (e.g. node_changed/announced, node_changed/stale). Coarse types mean fewer subscriptions to manage; action field gives granularity without type explosion.

### Decision: IPC bridge is one subscriber — feeds Textual messages into TUI

**Status:** decided
**Rationale:** Existing CMD_ACTIVITY_EVENT becomes the IPC-side subscriber of the bus. TUI bridge receives events, posts Textual messages (DaemonEvent). Screens handle DaemonEvent. No separate TUI event bus — Textual's message system already is one.

### Decision: Polling drops to 60s heartbeat — events are the fast path

**Status:** decided
**Rationale:** Dashboard goes from 5s poll to event-driven + 60s reconciliation. Exploration screen same. The slow poll catches anything an event missed (dropped IPC frame, subscriber exception). Belt and suspenders — events make it fast, polling makes it correct.

### Decision: No replay — late subscribers read current state from stores

**Status:** decided
**Rationale:** Fire-and-forget via create_task. No event log, no sequence numbers, no replay buffer. The 'missed early discoveries' problem is solved by reading stores on connect, not replaying events. Stores are the source of truth; events are acceleration.

### Decision: Incremental migration — node_changed first, one event type per PR

**Status:** decided
**Rationale:** Wire node_changed from announce handler → bus → IPC subscriber → TUI. Everything else keeps polling until migrated. No big-bang. Each event type is a small PR: add emit site in daemon, add handler in TUI, reduce poll frequency for that data.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/event_bus.py` (new) — EventBus class — subscribe/unsubscribe/emit, ~80 lines
- `src/styrened/daemon.py` (modified) — Create EventBus instance, wire node_changed emit into _on_device_discovered, pass bus to IPC server
- `src/styrened/ipc/server.py` (modified) — Subscribe to bus events, bridge to CMD_ACTIVITY_EVENT for connected clients
- `src/styrened/tui/models/events.py` (new) — DaemonEvent Textual Message class for TUI-side event handling
- `src/styrened/tui/services/ipc_bridge.py` (modified) — On activity event received, post DaemonEvent message to app
- `src/styrened/tui/screens/dashboard.py` (modified) — Handle DaemonEvent for instant COP/table updates, slow poll to 60s
- `src/styrened/tui/screens/exploration.py` (modified) — Handle DaemonEvent for instant table refresh, slow poll to 60s
- `tests/unit/test_event_bus.py` (new) — EventBus unit tests — subscribe, emit, unsubscribe, fan-out, error isolation

### Constraints

- EventBus must be pure asyncio — no external dependencies
- emit() must never block the caller (create_task fan-out)
- One subscriber exception must not kill other subscribers
- Existing IPC activity subscription must keep working during migration
- Python 3.11 compatible (from __future__ import annotations)
