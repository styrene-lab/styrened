---
id: cop-activity-summary
title: COP Activity Summary Widget
status: implemented
parent: tui-home-cop
tags: [tui, cop, activity, dashboard]
open_questions: []
branches: ["feature/cop-activity-summary"]
openspec_change: cop-activity-summary
---

# COP Activity Summary Widget

## Overview

Design a smart activity summary for the Home COP screen that is fundamentally different from the Diagnostics raw event firehose. The COP is the apex view — it should answer 'what needs my attention?' not 'what happened on the wire?'.

## Research

### Event taxonomy and coalescing strategy

Current EVENT_ACTIVITY types (16): new_message, delivery_status, device_discovered, device_updated, announce_sent, rpc_received, contact_set, contact_removed, identity_changed, auto_reply_changed, conversation_read, conversation_deleted, file_offer_received, file_transfer_complete, pqc_established, pqc_rekey.

Proposed COP situation categories (coalesced from raw events):
1. UNREAD — new_message events grouped by peer → '3 unread from Cleric Deck, FSJ' (bright, actionable)
2. NODE_ANOMALY — device lost/stale transitions → 'relay-east lost 4m ago' (bright, persists until recovered)
3. NODE_DISCOVERY — device_discovered coalesced → '2 nodes discovered in last 10m' (medium, ages to dim)
4. HUB_STATUS — hub connect/disconnect → 'hub reconnected 12m ago' (dims over time)
5. FILE_ACTIVITY — file_offer/transfer_complete → 'file from FSJ: report.pdf (2.1MB)' (bright → dim)
6. SECURITY — pqc_established/rekey → 'PQC session established with relay-east' (medium → dim)

Events NOT shown on COP: delivery_status, announce_sent, rpc_received, contact_set/removed, identity_changed, auto_reply_changed, conversation_read/deleted. These are wire-level detail for Diagnostics only.

Widget is a Static (re-rendered on each update), NOT a RichLog (append-only). Max 5-6 situation lines. Priority ordering: anomalies first, then actionable (unread), then informational. Resolved situations dim then age out after configurable TTL (default 30m).

### Event system conflict — full reassessment (2026-03-12)

The original spec was written before `internal-event-system` was implemented. It assumed the widget would own a `bridge.subscribe_activity()` loop and route 16 raw IPC event types through an `ingest_event()` method on the widget itself. This conflicts with three implemented decisions:

1. **IPC bridge is the only subscriber** — `DashboardScreen._subscribe_activity()` already subscribes once, posts `DaemonEvent` Textual messages to the app, and `on_daemon_event()` handles them. A second subscription loop inside the widget would duplicate the connection and bypass the event bus architecture.

2. **Widget is presentation-only** — The NodeInfoPanel/snapshot pattern established that widgets receive parent-owned canonical state, not bridge access. `CopActivitySummary` should be a `Static` that renders a `CopSituationSnapshot` pushed by the dashboard.

3. **Five coarse bus types, not 16 raw event strings** — The live bus uses: `node_changed` (announced/stale/lost/updated), `message_changed` (received/delivered/read), `hub_changed` (connected/disconnected/disabled), `link_changed` (established/lost). The spec's raw event names (`new_message`, `device_discovered`, `device_updated`, `pqc_established`, `file_offer_received`) no longer exist at the TUI boundary.

**Taxonomy resolution (no new bus types required):**
- UNREAD → `message_changed/received`
- NODE_ANOMALY → `node_changed/stale`, `node_changed/lost`
- NODE_DISCOVERY → `node_changed/announced`
- HUB_STATUS → `hub_changed/connected`, `hub_changed/disconnected`
- FILE_ACTIVITY → `message_changed/file_received`, `message_changed/file_complete` (new actions, existing type)
- SECURITY → `link_changed/pqc_established`, `link_changed/pqc_rekey` (new actions, existing type)

New actions on `message_changed` and `link_changed` require corresponding emit sites in the daemon — these don't exist yet and are the only daemon-side additions needed.

**Corrected architecture:**
- `CopSituationTracker` — owns situation state machine, lives on DashboardScreen
- `DashboardScreen.on_daemon_event()` → updates tracker → calls `cop_widget.apply_snapshot(tracker.snapshot())`
- `CopActivitySummary(Static)` — presentation only, renders snapshot
- No widget-owned subscription, no `ingest_event()`, no bridge access from widget

## Decisions

### Decision: Separate widget (CopActivitySummary) backed by situation state machine, not a filtered ActivityFeedWidget

**Status:** decided
**Rationale:** The COP apex view needs coalesced situation lines ('3 unread from X, Y'), not individual events. This requires fundamentally different data structure (situation dict with counters, timestamps, aging) vs the append-only RichLog model. A Static that re-renders from situation state is the right primitive. ActivityFeedWidget continues to serve Diagnostics tab as the raw firehose.

### Decision: 6 situation categories with priority ordering and aging

**Status:** decided
**Rationale:** Categories: UNREAD (peer-grouped), NODE_ANOMALY (lost/stale persists), NODE_DISCOVERY (coalesced count), HUB_STATUS (connect/disconnect), FILE_ACTIVITY, SECURITY (PQC). Priority: anomalies → actionable → informational. Max 5-6 lines. Resolved situations dim then drop after 30m TTL. Wire-level events (delivery_status, announce_sent, rpc_received, etc.) stay exclusively in Diagnostics.

### Decision: Transport-tagged situation lines via discovered_via

**Status:** decided
**Rationale:** Node events (discovery, anomaly) get a transport tag derived from MeshDevice.discovered_via — short label like [TCP], [Auto], [Ygg], [I2P]. Discovery lines coalesce per transport so operator sees mesh fabric shape ('2 nodes [Auto], 1 node [Ygg]'). Anomaly lines include transport to aid diagnosis ('relay-east lost 4m ago [TCP]'). Messages don't get transport tags — redundant with NODES panel. Requires adding discovered_via to the device_discovered activity event metadata payload (currently missing).

### Decision: Transport short-label mapping from discovered_via string prefix

**Status:** decided
**Rationale:** Parse the discovered_via string prefix (before ' → ' next-hop) and map to short COP tags: TCP, Auto, RNode, I2P, Ygg, UDP, SER, KISS, Pipe. Fallback '—' for None/unknown. Mapping lives in cop_activity_summary.py as a dict. Example: 'TCPClientInterface → 3a4b5c6d' → 'TCP'. This keeps the transport label derivation local to the COP widget.

### Decision: Include Mesh label in transport mapping now, bridge implementation deferred

**Status:** decided
**Rationale:** Adding 'Mesh' to the label dict is one line, costs nothing, and signals intent. MeshtasticBridgeService is a separate design node (meshtastic-bridge) with its own open questions around message format mapping and trust boundary semantics. Radio-only, no MQTT.

### Decision: CopSituationTracker owned by DashboardScreen — widget is presentation-only

**Status:** decided
**Rationale:** Aligns with the NodeInfoPanel snapshot pattern and StyreneScreen lifecycle contract. DashboardScreen.on_daemon_event() is the single intake point for all daemon events. It updates a CopSituationTracker (holds situation dict, coalescing logic, aging), then pushes a CopSituationSnapshot to the widget via apply_snapshot(). CopActivitySummary(Static) renders the snapshot — no bridge access, no subscription, no mutable state. This keeps worker/timer/subscription ownership at the screen level, consistent with all other dashboard surfaces.

### Decision: FILE_ACTIVITY and SECURITY fold into existing bus types via new actions — no new top-level types

**Status:** decided
**Rationale:** FILE_ACTIVITY maps to message_changed with actions file_received and file_complete. SECURITY (PQC) maps to link_changed with actions pqc_established and pqc_rekey. Both are semantically correct — files are message-layer, PQC is link-layer. Daemon emit sites for these actions don't exist yet and must be added as part of this change. The EventBus schema (5 coarse types) remains stable; only the action vocabulary expands.

## Open Questions

*No open questions.*
