---
id: tui-device-cache
title: Unified TUI Device Cache
status: exploring
tags: [tui, architecture, ipc]
open_questions: []
---

# Unified TUI Device Cache

## Overview

All TUI screens currently call bridge.get_devices() independently, maintain per-screen caches, and have divergent fallback paths to discover_devices(). mesh_device_detail.py even reaches into exploration.py's _live_nodes_cache via getattr. This creates stale/inconsistent views across screens and silent empty-list failures. A single app-level DeviceCache eliminates all shadow paths.

## Decisions

### Decision: App-level DeviceCache service, not screen-level caches

**Status:** decided
**Rationale:** DeviceCache lives on app.services (alongside bridge). Single periodic refresh loop (configurable interval, default 15s). All screens read from cache synchronously — no per-screen async workers for device data. On-demand refresh still available via cache.refresh(). Fallback: if bridge unavailable, DeviceCache calls discover_devices() directly. mesh_device_detail.py borrows from exploration's _live_nodes_cache — eliminated by reading from app cache instead. dashboard.py fires its own get_devices() every poll cycle — replaced by cache reads. Cache emits a DevicesUpdated message (Textual Message) when data changes so screens can reactively update without polling.

### Decision: Implementation complete — all shadow paths eliminated

**Status:** decided
**Rationale:** DeviceCache service created and wired. dashboard.py no longer fires get_devices() on every poll cycle. exploration.py per-screen caches removed; reacts to DevicesUpdated. mesh_device_detail.py getattr hack removed. All 10 files in scope migrated. 3537 unit tests pass, zero regressions.

### Decision: DevicesUpdated delivery: post to all mounted screens via app handler

**Status:** decided
**Rationale:** App defines on_device_cache_devices_updated which forwards to every currently-mounted Screen via app.query(Screen). Screens that are suspended get stale data; they call _refresh_announce_tables() on on_screen_resume anyway so the cache read catches up. Drop the constraint that screens define the handler themselves — the app is the fan-out point. Alternatively: ExplorationScreen sets a periodic timer in cache mode (matching countdown interval) that reads from cache.get() directly, eliminating the message dependency entirely for the refresh path.

### Decision: All assessment defects resolved — node ready to close

**Status:** decided
**Rationale:** Six fixes applied: (1) getattr(getattr(...),None,None) TypeError in exploration.py:729 and node_info_panel.py:600 — replaced with simple getattr(self.app,'device_cache',None). (2) DevicesUpdated dead-code handler — app.on_device_cache_devices_updated now fans out to all mounted screens via app.query(Screen). (3) ExplorationScreen had no periodic refresh timer in cache mode — set_interval(_REFRESH_INTERVAL) now set on the cache path. (4) _start_node_refresh() now stores worker into _node_refresh_worker so suspend cancel works. (5) DeviceCache.start() made idempotent — stops existing timer before creating new one; stop() called in app.on_shutdown. (6) Dashboard styrene_count always-0 regression fixed — DeviceType enum comparison instead of raw string match against wrong values.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/services/device_cache.py` (new) — DeviceCache: async refresh loop, get() → list[MeshDevice], get_styrene() subset, DevicesUpdated message, bridge/discover fallback
- `src/styrened/tui/services/__init__.py` (modified) — Add DeviceCache to AppServices, start at app boot
- `src/styrened/tui/screens/exploration.py` (modified) — Remove _live_nodes_cache/_stored_nodes_cache/_async_load_all_nodes. Read from app.services.device_cache. on_DevicesUpdated triggers _refresh_announce_tables.
- `src/styrened/tui/screens/dashboard.py` (modified) — Replace bridge.get_devices() task with device_cache.get()
- `src/styrened/tui/screens/contacts.py` (modified) — Replace bridge.get_devices() with device_cache.get()
- `src/styrened/tui/screens/exchange.py` (modified) — Replace bridge.get_devices()+discover_devices() fallback with device_cache.get()
- `src/styrened/tui/screens/exchange_tabs.py` (modified) — Replace bridge.get_devices() with device_cache.get()
- `src/styrened/tui/screens/mesh_device_detail.py` (modified) — Remove getattr(exploration, _live_nodes_cache) hack. Read from app.services.device_cache.
- `src/styrened/tui/widgets/node_info_panel.py` (modified) — Replace bridge.get_devices(styrene_only=True) with device_cache.get_styrene()
- `src/styrened/tui/widgets/reticulum_panel.py` (modified) — Replace discover_devices() with device_cache.get()

### Constraints

- DeviceCache must not block the Textual event loop — refresh runs in a worker
- Cache must be readable synchronously (last known good) — screens never await device data
- DevicesUpdated message posted to app so all mounted screens can react
- Fallback to discover_devices() when bridge is None, not an error
- styrene_only filter applied in-process from the full cache, not as a separate IPC call
- Per-screen _live_nodes_cache and _stored_nodes_cache removed entirely
