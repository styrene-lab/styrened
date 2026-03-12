# COP Activity Summary

The Home screen Activity panel shows coalesced situation summaries, not raw events.

## CopActivitySummary coalesces events into situation lines

Given a CopActivitySummary widget
When it receives 3 `new_message` events from peer "alpha" and 1 from peer "bravo"
Then a single UNREAD situation line reads "4 unread from alpha, bravo"
And the situation priority is ACTIONABLE

## Node discovery coalesces per transport

Given a CopActivitySummary widget
When it receives `device_discovered` events with discovered_via "TCPClientInterface" (2 nodes) and "AutoInterface" (1 node)
Then two NODE_DISCOVERY situation lines appear: "2 nodes discovered [TCP]" and "1 node discovered [Auto]"

## Transport labels parsed from discovered_via prefix

Given discovered_via value "TCPClientInterface → 3a4b5c6d"
When transport_label() is called
Then it returns "TCP"

Given discovered_via value None
When transport_label() is called
Then it returns "—"

## Node anomaly includes transport tag

Given a node "relay-east" was discovered via "YggdrasilInterface"
When a `device_updated` event marks it status "offline"
Then a NODE_ANOMALY situation line reads "relay-east lost Xm ago [Ygg]"
And the situation priority is ANOMALY (highest)

## Resolved situations age out

Given a NODE_ANOMALY situation that was resolved (node came back)
When 30 minutes have elapsed since resolution
Then the situation line is removed from display

Given a NODE_ANOMALY situation that was resolved 5 minutes ago
When the widget renders
Then the situation line appears dimmed

## Wire-level events are excluded

Given a CopActivitySummary widget
When it receives events: delivery_status, announce_sent, rpc_received, contact_set, conversation_read
Then no situation lines are created

## Priority ordering

Given situations exist in categories UNREAD, NODE_ANOMALY, NODE_DISCOVERY
When the widget renders
Then NODE_ANOMALY lines appear first
Then UNREAD lines appear second
Then NODE_DISCOVERY lines appear last

## Maximum situation lines

Given more than 6 active situations exist
When the widget renders
Then only the top 6 by priority are shown

## Dashboard uses CopActivitySummary not ActivityFeedWidget

Given the Home screen DashboardScreen
When it composes the ACTIVITY panel
Then it contains a CopActivitySummary widget
And it does NOT contain an ActivityFeedWidget

## Daemon includes discovered_via in device event

Given a device is discovered via "AutoInterface"
When the daemon emits a device_discovered activity event
Then the event metadata includes "discovered_via": "AutoInterface"
