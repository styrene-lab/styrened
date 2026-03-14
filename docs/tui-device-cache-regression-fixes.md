---
id: tui-device-cache-regression-fixes
title: TUI Device Cache Regression Fixes
status: exploring
parent: tui-device-cache
tags: [tui, bug, ipc, device-cache, navigation, tests]
open_questions: []
issue_type: bug
priority: 1
---

# TUI Device Cache Regression Fixes

## Overview

Repair the regressions introduced during the DeviceCache migration and splash-first startup integration: preserve usable fallback semantics when the shared cache is empty or unprimed, avoid bare-screen app access crashes, update tests for the Home/Nodes ownership split, and reconcile startup expectations around the splash screen.

## Research

### Assessment findings from manual cradle-to-grave pass

The Home overflow affordance tests are green, but the shared device-cache migration is not fully behaviorally reconciled. ExplorationScreen and MeshDeviceDetailScreen now prefer app.device_cache whenever the app object exists, even when the cache is present but empty or unprimed, which causes empty node tables and unresolved peer detail in tests and likely in startup/race windows. DashboardScreen._fetch_daemon_status similarly touches self.app.device_cache inside an exception boundary that can mark the daemon disconnected in unmounted test contexts. Separately, splash-first startup changed the app contract so app-level tests that assumed immediate DashboardScreen availability are now stale. Legacy tests importing MeshDeviceTree from dashboard are also stale because peer browsing belongs to Nodes/Exploration now.

### Implementation and verification after regression-fix pass

Runtime consumers now distinguish cache availability from cache readiness. Dashboard status refresh reads cached devices through a helper that swallows bare-screen app access failures rather than reporting false daemon disconnects. ExplorationScreen and MeshDeviceDetailScreen fall back to direct discovery when the shared cache exists but is still empty/unprimed, preserving startup-race and direct test contexts without reintroducing per-screen shadow caches. Targeted verification passed: 228 tests across Home summary, sharp-edge regressions, dashboard, Nodes, peer detail, COP activity summary, app startup, navigation workflows, and chat integration.

### Lifecycle closure state

OpenSpec change `tui-device-cache-regression-fixes` has been archived after a passing spec assessment. Baseline spec was emitted under `openspec/baseline/tui/device-cache.md`, and the change moved to `openspec/archive/2026-03-14-tui-device-cache-regression-fixes/`. The design-tree node still requires the external design-assessment gate before `set_status(decided)` will be accepted by the tool, so lifecycle closure is complete in OpenSpec but status reconciliation remains tool-gated.

## Decisions

### Decision: Cache consumers must distinguish cache availability from cache readiness

**Status:** decided
**Rationale:** The presence of an app-level DeviceCache object is not sufficient proof that device data is usable. Cache consumers must preserve a sane fallback path when the cache is empty or not yet primed, especially in startup races, direct unit contexts, and peer-resolution paths. The migration goal remains a single authoritative cache, but consumers must treat empty/unready cache reads as a state to handle rather than as authoritative absence.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/dashboard.py` (modified) — Guard device-cache reads in _fetch_daemon_status and keep unit/bare-screen contexts from falsely reporting daemon disconnect.
- `src/styrened/tui/screens/exploration.py` (modified) — Restore robust device-loading semantics when the shared cache exists but is empty or unprimed; avoid NoActiveAppError on bare screen resume paths.
- `src/styrened/tui/screens/mesh_device_detail.py` (modified) — Preserve live device lookup fallback when cache is unprimed so peer detail resolution still works.
- `tests/tui/screens/test_dashboard_tui.py` (modified) — Update dashboard wiring expectations to match cache-backed device reads and splash-era startup behavior where needed.
- `tests/tui/screens/test_exploration.py` (modified) — Reconcile stale expectations with current Nodes workspace shape and keep behavior coverage focused on real regressions.
- `tests/tui/screens/test_device_detail_tui.py` (modified) — Keep peer detail tests passing under cache-backed resolution and current screen lifecycle.
- `tests/tui/test_app.py` (modified) — Update app startup expectation to account for SplashScreen as the first visible screen.
- `tests/tui/test_navigation_workflows.py` (modified) — Retire or rewrite legacy dashboard MeshDeviceTree imports so collection reflects current Home vs Nodes ownership.
- `tests/tui/integration/test_chat_dashboard_flow.py` (modified) — Retire or rewrite legacy dashboard MeshDeviceTree imports so integration collection reflects current architecture.

### Constraints

- Do not reintroduce per-screen shadow caches as the primary data path.
- Exploration and peer-detail flows must remain functional in startup races and test contexts where app.device_cache exists but has not yet been populated.
- Home remains a summary surface; do not restore dashboard-owned peer browsing just to satisfy stale tests.
- Splash-first startup is intentional; tests should be updated to the new contract rather than removing the splash screen.
