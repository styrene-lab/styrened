---
id: tui-global-cop-surface
title: TUI Global COP Surface
status: implemented
parent: tui-startup-ipc-backpressure
open_questions: []
issue_type: feature
priority: 2
---

# TUI Global COP Surface

## Overview

> Parent: [TUI Startup IPC Backpressure and Demand Shaping](tui-startup-ipc-backpressure.md)
> Spawned from: "What should the dedicated TUI Global COP surface include once Home is kept lean?"

*To be explored.*

## Research

### Progressive disclosure target above Home

The Global COP surface should become the richer TUI drill-down once Home is intentionally kept lean. It can own broader fleet visibility, richer filters/sorting, multi-panel summaries, and heavier or more optional hydration that would be inappropriate for first paint on constrained systems. This supports a layered operator experience: lightweight Home COP first, richer TUI Global COP second, and potentially an even more capable web UI later on systems that can afford it.

### Current workspace map and Home's scope

Current workspaces: HOME (dashboard.py, key: default), NODES (exploration.py, key: n), MAIL/EXCHANGE (exchange.py, key: x/m/i), COMMS (comms.py, key: c), ADMIN (settings, key: `).

Home currently owns:
- HomeStatusBar: hub/adapter/RNS health, unread count, uptime
- HomeNodeSummaryTable: compact node list with overflow affordance
- CopActivitySummary: situation tracker (recent events, human-readable summary)
- ActivityFeedWidget (COP variant): recent activity

ADMIN (grave_accent) exists but is just SettingsScreen. No dedicated Global COP screen exists yet — the design space is open.

Nodes (exploration.py) is browse-first: fleet tables with tab per node type (Styrene/LXMF/Infra/Other/Pages), plus a Diagnostics tab with ActivityFeedWidget that's currently broken (lazy subscription, no backfill). Nodes is not the right place for monitoring — it's for selection and interaction.

### Monitor-first vs browse-first distinction

The critical design distinction between Global COP and existing screens:

- HOME: Lowest cost, passive glance. "Am I connected? Any messages? How many peers?"
- NODES: Browse-first. You go there to find and interact with a specific node.
- GLOBAL COP: Monitor-first. You go there to watch the mesh. No node selection needed.

A monitor-first surface answers: "What is the full state of my mesh right now? What has changed? What needs my attention?" It should update live without operator interaction and surface anomalies proactively.

Analogy: Home is a status light. Nodes is a contacts list. Global COP is a network operations dashboard.

### Proposed layout and content

Four zones, using components that already exist where possible:

**Zone 1 — Aggregate health bar (top, 2-3 rows)**
Extends HomeStatusBar with richer metrics not appropriate for Home:
- Node counts: total / reachable / LOST / new-since-last-seen
- Delivery success rate (sent / delivered / failed in last N messages)
- Hub propagation lag (time since last hub announce)
- Adapter health: I2P tunnel status, Yggdrasil peer count
- RNS interface breakdown: active interfaces, transport-enabled nodes

**Zone 2 — Full fleet table (middle-left, largest zone)**
Not the browse-oriented ReticumAnnounceTable from Nodes, but a health-oriented view:
- All nodes sorted by health/urgency: LOST nodes first (with time since last seen), then by hop count, then alphabetically
- Columns: name, type, status (reachable/LOST/new), hops, last announce age, capabilities icons
- Colour-coded rows: danger for LOST nodes recently active, warning for nodes approaching announce timeout, dim for stable
- Read-only: no row-click navigation. This is a monitor, not a nav surface. (Or: row-click is allowed but opens node detail as a push, not a switch.)
- Filter bar: quick filter by type/status/name without leaving the surface

**Zone 3 — Alert list (middle-right, narrow column)**
First-class surface for things requiring attention:
- Failed message deliveries (peer + count + age)
- Nodes that went LOST in the last N minutes (were healthy, now unreachable)
- Adapter errors (I2P tunnel down, Yggdrasil peer lost)
- Config issues surfaced by doctor (missing identity, low announce interval, etc.)
- Unacknowledged: alerts stay until operator dismisses or condition resolves

**Zone 4 — Live activity feed (bottom)**
The ActivityFeedWidget currently buried in Nodes Diagnostics tab, promoted here as a first-class element. Subscribed at screen mount (fixing the lazy subscription bug). Backfilled with recent history from daemon ring buffer on connect. Shows real-time mesh events: announces, deliveries, link events, adapter state changes.

### Component reuse and new work required

Reusable as-is:
- HomeStatusBar (or a richer variant) for Zone 1
- ActivityFeedWidget for Zone 4 (with the backfill fix from tui-diagnostics-panel-empty)
- CopActivitySummary (situation tracker) — may fold into Zone 3 alert list

Needs extension:
- A new GlobalCopFleetTable widget for Zone 2 — health-sorted, colour-coded, read-only-first, distinct from the browse-oriented ReticumAnnounceTable/StyreneFleetTable in Nodes
- A new AlertListWidget for Zone 3 — acknowledging state, persistence across refreshes, auto-resolve when condition clears
- Richer aggregate metrics in the daemon IPC (delivery success rate, per-interface stats) — currently only node count and uptime are exposed

New screen:
- GlobalCopScreen (src/styrened/tui/screens/global_cop.py) — a StyreneScreen subclass with live subscriptions, no lazy loading
- Keybinding: 'g' on the app level (currently unused) — "g for global"
- Listed in app BINDINGS, shown in Footer

## Decisions

### Decision: Global COP is a dedicated screen, not a tab or panel on an existing screen

**Status:** decided
**Rationale:** Nodes is browse-first; embedding a monitor surface there would conflict with its navigation model and force it to carry the cost of both. Home is intentionally lean. A dedicated GlobalCopScreen owns its own subscription lifecycle, layout, and keybinding — making the cost explicit and the surface composable independently.

### Decision: Keybinding: 'g' for Global COP

**Status:** decided
**Rationale:** 'g' is currently unused at the app level. Mnemonic: "g for global." Consistent with the single-letter navigation scheme (n=nodes, m=mail, c=comms). Shown in Footer. Grave_accent remains for Admin/Settings.

### Decision: Fleet table is health-sorted and monitor-first — row selection navigates to node detail without switching workspace

**Status:** decided
**Rationale:** Sorting by health urgency (LOST → warning → stable) makes the most critical nodes immediately visible without any operator action. Read-only-first means no accidental navigation — the surface stays as a monitor. If the operator does select a row, it pushes the node detail screen (same pattern as Nodes) rather than switching workspaces, preserving the COP as the background context to return to.

### Decision: Alert persistence is ephemeral — in-memory per TUI session

**Status:** decided
**Rationale:** Alerts re-derive from live state on reconnect. Durable alert history is the activity feed ring buffer's job — not the alert list's. Keeps AlertListWidget simple and stateless across restarts.

### Decision: Fleet table is Styrene-primary with expand toggle for full announce neighbourhood

**Status:** decided
**Rationale:** Styrene nodes support RPC health queries, daemon version, capability diff, and config drift checks — the depth needed for a real COP. Non-Styrene nodes are announce-only and already covered in the Nodes workspace. Default view is Styrene nodes. A toggle (tab or f) expands to all discovered peers. Warning threshold is defined as: no RPC health response within N announce intervals, regardless of announce presence.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/dashboard.py` (modified) — Keep Home scoped to the lightweight summary COP and navigation affordances into richer surfaces.
- `src/styrened/tui/screens/exploration.py` (modified) — Potential reuse of existing fleet-table and filtering primitives inside a richer Global COP workspace.
- `src/styrened/tui/widgets/home_node_summary.py` (modified) — Preserve Home as a compact summary widget rather than the owner of global fleet detail.
- `src/styrened/tui/screens/global_cop.py` (new) — GlobalCopScreen — StyreneScreen subclass. Four-zone layout: aggregate health bar, health-sorted fleet table, alert list, live activity feed. Subscribes to activity at mount. Keybinding: g.
- `src/styrened/tui/widgets/global_cop_fleet_table.py` (new) — GlobalCopFleetTable — health-sorted, colour-coded fleet widget. LOST nodes first, then by hop count. Columns: name, type, status, hops, last-seen age, capability icons. Row-select pushes node detail.
- `src/styrened/tui/widgets/alert_list.py` (new) — AlertListWidget — acknowledging alert surface. Entries: failed deliveries, nodes gone LOST, adapter errors, doctor findings. Auto-resolves when condition clears.
- `src/styrened/tui/app.py` (modified) — Add g keybinding and action_open_global_cop(). Register GlobalCopScreen in screen map. Show in Footer.
- `src/styrened/ipc/handlers.py` (modified) — Add GET_ACTIVITY_HISTORY (ring buffer, N=200). Add delivery stats to GET_STATUS response (sent/delivered/failed counts for last N messages).

### Constraints

- Home must remain the lowest-cost COP surface and stay usable on constrained devices.
- Global COP may be richer and heavier than Home, but should still degrade gracefully as data becomes available.
- The richer web UI, if added later, should extend the same progressive-disclosure model rather than forcing Home to absorb those concerns.
- Home must remain unchanged — Global COP adds richness above it, not replaces it.
- Activity feed subscription must start at screen mount, not lazily — this is the fix for the diagnostics panel bug applied properly.
- Fleet table sort order is by health urgency first (LOST > warning > stable), not alphabetical.
- Alert list entries must auto-resolve when the underlying condition clears — no stale alerts.
- Delivery success rate requires a daemon-side ring buffer of recent message outcomes — not just counts from ConversationService.
