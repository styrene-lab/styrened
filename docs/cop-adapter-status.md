---
id: cop-adapter-status
title: COP Adapter Status — Extensible Overlay Service Health Surface
status: implementing
parent: tui-home-cop
tags: [tui, cop, adapters, i2p, yggdrasil, overlay, health, dashboard]
open_questions: []
branches: ["feature/cop-adapter-status"]
openspec_change: cop-adapter-status
---

# COP Adapter Status — Extensible Overlay Service Health Surface

## Overview

Surface the readiness state of optional overlay adapters (I2P, Yggdrasil, and future philosophically-aligned projects) directly on the COP home screen. Two visual layers: a persistent ADAPTERS row showing current state with per-adapter visual language, and transient situation lines in the activity feed for meaningful state transitions. The system must be extensible — not hardcoded to I2P/Yggdrasil — because many future adapters may register against it.

## Research

### Architecture summary

**Daemon side:** Each adapter class (I2PAdapter, future YggdrasilAdapter) implements AdapterProtocol ABC. AdapterRegistry at daemon startup holds list[AdapterProtocol]. Probe loop runs in daemon service layer on a per-adapter interval. On any state transition, daemon emits DaemonEvent(adapter_changed, action, {adapter_name, prev_state, ...}) onto the EventBus. EventBus gains adapter_changed as its 6th top-level type (actions: ready, warming, degraded, probing, disabled).\n\n**TUI side:** DashboardScreen.on_daemon_event() receives adapter_changed events — no timer, no probe logic in TUI. AdapterStatusTracker on DashboardScreen maintains current snapshot of all registered adapters. Snapshot pushed to AdapterStatusBar widget (presentation-only, apply_snapshot()). Meaningful transitions (WARMING→READY, READY→DEGRADED, DEGRADED→READY) also inject a SituationLine into CopSituationTracker for the activity feed.\n\n**Visual:** ADAPTERS row always renders all registered adapters. DISABLED = dashed/inactive visual. PROBING/WARMING = amber indicator. READY = green. DEGRADED = red/anomaly. Warm-up affordances (retry button etc.) declared per-adapter via WarmupBehavior, rendered conditionally by the widget.

## Decisions

### Decision: Adapter registry is open and extensibility-first — not hardcoded to I2P/Yggdrasil

**Status:** decided
**Rationale:** The adapter status surface must accommodate any future project that philosophically aligns with Styrene and isn't prohibitively difficult to support. Adapters register against a common interface (name, state machine, probe callable, warm-up behavior metadata) rather than being enumerated statically. The ADAPTERS row renders whatever is registered — 2 adapters today, potentially 5-6 in the future. The extensibility boundary is the adapter registration protocol, not the COP widget itself.

### Decision: DISABLED adapters remain visible with dashed/inactive visual language — not hidden

**Status:** decided
**Rationale:** A DISABLED adapter is still a latent capability the operator hasn't turned on yet. Hiding it removes the affordance entirely. Instead, use a dashed outline or similar visual language that communicates "this exists but is off" — a nudge without noise. This respects the operator's choice while keeping discoverability alive. Active adapters (PROBING, WARMING, READY, DEGRADED) use solid indicators.

### Decision: Warm-up actionability is per-adapter — no universal WARMING behavior

**Status:** decided
**Rationale:** Different adapters have fundamentally different warm-up cycles. I2P tunnel bootstrapping is non-actionable — it's a probabilistic network integration process; the operator can only wait. A future Yggdrasil adapter might offer a "retry peer connection" affordance. The adapter registration interface must allow each adapter to declare its warm-up behavior (non-actionable, retryable, configurable-interval, etc.) so the COP widget can render appropriate affordances or none at all. No universal WARMING UX pattern is imposed top-down.

### Decision: Adapter status reflects actual probe reality — no inferred or cached state beyond probe interval

**Status:** decided
**Rationale:** The displayed state must match the adapter's actual probe result. If the probe says READY (proxy bound, test fetch succeeded), show READY — do not hold in WARMING longer than the probe interval. If the probe says DEGRADED (proxy was reachable, now isn't), show DEGRADED immediately — do not linger in READY. Accuracy is non-negotiable: showing WARMING when the adapter is actually functional, or READY when it has silently failed, actively deceives the operator. The probe interval is the only tolerable lag.

### Decision: Adapter registration interface is a Protocol/ABC — each adapter class implements it directly

**Status:** decided
**Rationale:** Each adapter (I2PAdapter, future YggdrasilAdapter, etc.) implements an AdapterProtocol ABC: probe() → AdapterState, display_name: str, warmup_behavior: WarmupBehavior. The registry is simply list[AdapterProtocol] assembled at daemon startup. Probe logic stays encapsulated in the adapter class, not in external config. Elegant, avoids overcomplication, and minimizes maintenance overhead as new adapters are added.

### Decision: adapter_changed is a 6th EventBus top-level type

**Status:** decided
**Rationale:** Adapter state is a distinct semantic category — service-layer, not transport-layer (link_changed) and not operator-infrastructure (hub_changed). The "no new bus types" constraint from cop-activity-summary was scoped to avoid inflating the schema for one widget's convenience; it doesn't apply here. A clean 6th type is better than contaminating an existing one. Actions: ready, warming, degraded, probing, disabled.

### Decision: Every meaningful state transition generates a situation line — no first-boot-only exception

**Status:** decided
**Rationale:** READY→DEGRADED: anomaly situation line, persists until recovered. DEGRADED→READY: informational line, dims normally. WARMING→READY: informational line, dims normally — fires on every cycle (daemon restart, reconnect), not just first boot, because each recovery is meaningful to the operator. DISABLED→anything: no situation line, operator-initiated config change not a COP event.

### Decision: Probe timer lives in the daemon service layer — DashboardScreen is a pure observer

**Status:** decided
**Rationale:** The probe loop runs inside the daemon alongside where adapters already operate (I2PAdapter._probe() etc.). On state transition, the daemon emits adapter_changed onto the EventBus. DashboardScreen receives it via on_daemon_event() like any other DaemonEvent — no timer ownership, no probe logic in the TUI. Clean separation: adapter state is accurate regardless of which TUI screen is active or whether the TUI is connected at all.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/adapter_registry.py` (new) — AdapterProtocol ABC, WarmupBehavior, AdapterState enum, AdapterRegistry
- `src/styrened/services/i2p.py` (modified) — I2PAdapter implements AdapterProtocol
- `src/styrened/tui/models/adapter_status.py` (new) — AdapterStatusSnapshot, AdapterStatusTracker
- `src/styrened/tui/widgets/adapter_status_bar.py` (new) — AdapterStatusBar widget — presentation-only, apply_snapshot()
- `src/styrened/tui/screens/dashboard.py` (modified) — Wire AdapterStatusTracker, on_daemon_event adapter_changed handling
- `src/styrened/services/event_bus.py` (modified) — Add adapter_changed as 6th EventBus type

### Constraints

- Probe timer and probe logic must live entirely in daemon service layer — no probe code in TUI
- AdapterStatusBar is presentation-only — no bridge access, no subscriptions
- adapter_changed EventBus type uses actions: ready, warming, degraded, probing, disabled
- WarmupBehavior per-adapter declares actionability — widget renders affordances conditionally
- DISABLED adapters always visible in ADAPTERS row with dashed visual, never hidden
