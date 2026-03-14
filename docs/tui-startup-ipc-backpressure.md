---
id: tui-startup-ipc-backpressure
title: TUI Startup IPC Backpressure and Demand Shaping
status: implemented
parent: tui-device-cache-regression-fixes
open_questions: []
openspec_change: tui-startup-ipc-backpressure-fix
issue_type: bug
priority: 1
---

# TUI Startup IPC Backpressure and Demand Shaping

## Overview

> Parent: [TUI Device Cache Regression Fixes](tui-device-cache-regression-fixes.md)
> Spawned from: "How should Home startup shape IPC demand so liveness remains truthful on large meshes and constrained hardware without reintroducing per-screen caches?"

Investigate the startup backpressure exposed by live TUI use against large meshes: Home currently mixes cheap liveness/status calls with heavyweight fleet hydration over a single serialized IPC client path, which can make a healthy daemon look disconnected. The design goal is to keep Home truthful and responsive by shrinking first-paint work, deferring bulk hydration, and only introducing IPC traffic-class isolation if demand shaping alone is insufficient.

## Research

### Implications of the startup bottleneck

The observed bottleneck is primarily demand-shaping and head-of-line-blocking, not an inherent need for more total IPC throughput. The TUI currently asks for a mix of cheap control-plane data (`ping`, daemon status, hub/config) and expensive bulk hydration (`get_devices`, conversations) during first paint, while a single client connection to the daemon is processed serially. On large fleets this causes latency-sensitive liveness checks to queue behind full-fleet serialization and merge work. Constrained hardware strengthens the case for reducing startup work rather than simply adding more concurrent streams: extra streams can improve latency isolation, but they do not reduce total daemon work and may increase CPU, allocation, DB, and event-loop pressure on Pi-class systems. The first architectural move should therefore be to shrink and stage startup demand, then optionally isolate traffic classes if liveness still suffers.

### Recommended implementation shape

The preferred implementation sequence is: (1) make first paint depend only on a cheap summary path that already proves daemon reachability and provides Home-safe counts, (2) defer full-fleet and conversation hydration to background work that can update the shared app-level cache later, and (3) represent slow bulk hydration as a degraded/backpressured UI state rather than a hard disconnect. Only if this still leaves status work vulnerable to head-of-line blocking should the design introduce distinct IPC traffic classes or separate bridge/client instances for control, bulk, and event traffic. This preserves correctness on constrained systems because it reduces first-paint work before adding any concurrency.

### Progressive disclosure path for COP surfaces

A clean way to satisfy both responsiveness and richer situational awareness is to separate COP surfaces by cost and ambition. Home should remain the lean, always-available summary layer optimized for constrained devices and first paint. A dedicated TUI Global COP surface can become the place for broader fleet views, richer drill-downs, and optional heavy hydration once the daemon and UI are already stable. A later web UI can sit above that as the highest-capability tier for systems that can afford full visualizations and more expensive data presentation. This creates a graceful-degradation ladder: Home COP → TUI Global COP → richer web UI.

### Single-bridge request fan-out is itself a pressure source

Live probing against the dev daemon showed that issuing multiple IPC requests concurrently through a single `ControlClient`/`IPCBridge` connection is unreliable under load: even cheap `query_status`/`get_hub_status`/`get_unread_counts` requests timed out when fanned out on the same connection, while the same requests succeeded sequentially. Stage-one Home refresh therefore switched not only to cheaper queries but also to a short sequential summary path, avoiding same-connection burst fan-out as an additional pressure source.

## Decisions

### Decision: Prioritize startup demand shaping before adding IPC lane parallelism

**Status:** decided
**Rationale:** Home is a summary surface and should not require full fleet hydration before it can truthfully report daemon liveness. The primary fix should reduce first-paint work, defer bulk hydration, and decouple connection health from heavy queries. Separate IPC lanes may still be useful later for latency isolation, but only after startup demand is trimmed so constrained hardware does not pay for avoidable parallel work.

### Decision: Stage one should reuse existing reachability and status surfaces before adding a new summary endpoint

**Status:** decided
**Rationale:** The first implementation step should remove startup fan-out and make Home tolerant of delayed bulk hydration without expanding the IPC surface area prematurely. Reusing the existing daemon reachability check plus the current status query in a non-blocking way keeps the change smaller and lets us measure whether a dedicated lightweight summary endpoint is still necessary after demand shaping is in place.

### Decision: Keep Home lean and move full-fleet drill-down into a dedicated Global COP surface

**Status:** decided
**Rationale:** The startup bottleneck is partly a product-boundary problem: Home was being asked to behave like both a summary surface and a global fleet console. Splitting those concerns preserves fast, truthful startup on constrained systems while still giving operators a path to richer situational awareness. The dedicated Global COP can absorb heavier queries and richer controls after first paint, and later a web UI can extend that same progressive-disclosure model for systems with more headroom.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/app.py` (modified) — Stage startup initialization so liveness checks and first paint do not depend on bulk hydration completing.
- `src/styrened/tui/screens/dashboard.py` (modified) — Make Home liveness/status rendering independent from full device inventory and surface degraded/backpressured state separately from disconnected.
- `src/styrened/tui/services/device_cache.py` (modified) — Delay or budget initial full-fleet refresh so cache priming happens in the background without blocking first-paint status.
- `src/styrened/ipc/handlers.py` (modified) — Potentially add or expose a cheaper summary path if existing status payload is insufficient for Home first paint.
- `tests/tui/screens/test_dashboard_tui.py` (modified) — Verify Home remains connected/useful when bulk hydration is slow or times out.
- `tests/tui/test_app.py` (modified) — Cover staged startup behavior and non-blocking first paint under slow bulk IPC responses.

### Constraints

- Do not reintroduce per-screen caches or make Home own detailed fleet browsing again.
- Treat daemon liveness, degraded/backpressured IPC, and disconnected states as distinct operator-facing conditions.
- Prefer reducing first-paint work over adding concurrency that merely hides the bottleneck.
- Any bulk hydration path must remain safe for large public-mesh datasets and constrained SBC-class hardware.
