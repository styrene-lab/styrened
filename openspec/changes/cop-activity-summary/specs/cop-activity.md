# COP Activity Summary

The Home screen Activity panel shows coalesced situation summaries driven by
`DaemonEvent` Textual messages. `CopActivitySummary` is a presentation-only
widget; all state lives in `CopSituationTracker` owned by `DashboardScreen`.

---

## Architecture: tracker owned by screen, widget is presentation-only

Given `DashboardScreen` with a mounted `CopActivitySummary` widget
When `on_daemon_event(DaemonEvent)` fires
Then the screen updates its `CopSituationTracker`
And calls `cop_widget.apply_snapshot(tracker.snapshot())`
And the widget re-renders without touching the IPC bridge directly

## CopActivitySummary has no bridge access

Given a `CopActivitySummary` widget instance
Then it has no `bridge` property
And it has no subscription loop
And it exposes only `apply_snapshot(snapshot: CopSituationSnapshot) -> None`
And `render()` returns markup derived from the last applied snapshot

---

## UNREAD: message_changed/received coalesces by peer

Given `DashboardScreen.on_daemon_event` receives:
  - `DaemonEvent(event_type="message_changed", action="received", data={"peer": "alpha"})`  ×3
  - `DaemonEvent(event_type="message_changed", action="received", data={"peer": "bravo"})`  ×1
When `tracker.snapshot()` is rendered
Then a single UNREAD situation line reads "4 unread from alpha, bravo"
And its priority is ACTIONABLE

## UNREAD clears when message_changed/read fires for peer

Given an UNREAD situation exists for peer "alpha"
When `DaemonEvent(event_type="message_changed", action="read", data={"peer": "alpha"})` fires
Then the UNREAD situation for "alpha" is resolved

---

## NODE_DISCOVERY: node_changed/announced coalesces per transport

Given `DaemonEvent` events:
  - `node_changed/announced` with `discovered_via="TCPClientInterface"` ×2
  - `node_changed/announced` with `discovered_via="AutoInterface"` ×1
When the tracker renders
Then two NODE_DISCOVERY lines appear: "2 nodes discovered [TCP]" and "1 node discovered [Auto]"

## NODE_ANOMALY: node_changed/stale or /lost persists until recovered

Given node "relay-east" was discovered via "YggdrasilInterface"
When `DaemonEvent(event_type="node_changed", action="lost", data={"name": "relay-east", "discovered_via": "YggdrasilInterface"})` fires
Then a NODE_ANOMALY situation line reads "relay-east lost Xm ago [Ygg]"
And its priority is ANOMALY (highest)

Given a NODE_ANOMALY situation for "relay-east"
When `DaemonEvent(event_type="node_changed", action="announced", data={"name": "relay-east", ...})` fires
Then the NODE_ANOMALY situation for "relay-east" is marked resolved

---

## HUB_STATUS: hub_changed events

Given `DaemonEvent(event_type="hub_changed", action="disconnected")` fires
Then a HUB_STATUS situation line reads "hub disconnected Xm ago"

Given `DaemonEvent(event_type="hub_changed", action="connected")` fires
Then any active HUB_STATUS disconnected situation is resolved
And an informational "hub reconnected Xm ago" line appears

---

## FILE_ACTIVITY: message_changed/file_received and /file_complete

Given `DaemonEvent(event_type="message_changed", action="file_received", data={"peer": "FSJ", "filename": "report.pdf", "size_bytes": 2202009})` fires
Then a FILE_ACTIVITY situation line reads "file from FSJ: report.pdf (2.1 MB)"

Given `DaemonEvent(event_type="message_changed", action="file_complete", data={"peer": "FSJ", "filename": "report.pdf"})` fires
Then the FILE_ACTIVITY situation for that transfer resolves

## SECURITY: link_changed/pqc_established and /pqc_rekey

Given `DaemonEvent(event_type="link_changed", action="pqc_established", data={"peer": "relay-east"})` fires
Then a SECURITY situation line reads "PQC session established with relay-east"
And its priority is INFORMATIONAL

---

## Transport label parsed from discovered_via prefix

Given discovered_via value "TCPClientInterface → 3a4b5c6d"
When `transport_label()` is called
Then it returns "TCP"

Given discovered_via value None
When `transport_label()` is called
Then it returns "—"

## Unrelated DaemonEvent types produce no situation lines

Given `DaemonEvent` with event_type/action combinations:
  - `message_changed/delivered`
  - `message_changed/read`
  - `node_changed/updated`
  - `link_changed/lost` (no peer data)
When the tracker processes them
Then no new situation lines are created for these events
And existing situations are not affected

## Priority ordering

Given active situations in categories UNREAD, NODE_ANOMALY, NODE_DISCOVERY
When the snapshot renders
Then NODE_ANOMALY lines appear first
Then UNREAD lines appear second
Then NODE_DISCOVERY lines appear last

## Maximum situation lines

Given more than 6 active situations exist
When the widget renders
Then only the top 6 by priority are shown

## Resolved situations dim then age out

Given a NODE_ANOMALY situation that was resolved (node came back)
When 30 minutes have elapsed since resolution
Then the situation line is removed from the snapshot

Given a NODE_ANOMALY situation resolved 5 minutes ago
When the widget renders
Then the situation line appears dimmed

## Dashboard composes CopActivitySummary not ActivityFeedWidget

Given `DashboardScreen`
When it composes the ACTIVITY panel
Then it contains a `CopActivitySummary` widget
And it does NOT contain an `ActivityFeedWidget`

---

## Daemon emits new actions for file and PQC events

Given a file offer is received from a peer
When the daemon processes the LXMF message
Then it calls `event_bus.emit("message_changed", action="file_received", peer=..., filename=..., size_bytes=...)`

Given a PQC session is established with a peer
When the daemon completes PQC handshake
Then it calls `event_bus.emit("link_changed", action="pqc_established", peer=...)`
