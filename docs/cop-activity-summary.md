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

## Open Questions

*No open questions.*
