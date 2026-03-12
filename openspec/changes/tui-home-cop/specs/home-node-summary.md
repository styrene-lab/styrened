# home-node-summary — Delta Spec

## ADDED Requirements

### Requirement: Home screen embeds a compact read-only node summary table

The Home screen's primary display area shows a HomeNodeSummaryTable widget: a compact, read-only table of known mesh nodes. Columns: Name, Status (symbol+label), Last Seen (relative time), Unread (message count or dash), Link (connection type). Rows are sorted abnormal-first: lost/error nodes at top, then stale, then online. The table is not interactive beyond cursor navigation and Enter-to-drill. It replaces the current COMMS panel (CommsSummaryWidget).

#### Scenario: Node summary table shows discovered nodes
Given 3 nodes are known: one online (12s ago), one stale (3m ago), one lost (2h ago)
When the Home screen renders
Then the node table shows 3 rows with correct Name, Status, Last Seen, and Link columns
And rows are sorted: lost first, then stale, then online

#### Scenario: Node summary table shows unread count per node
Given node relay-east has 2 unread messages and node casbah has 0
When the Home screen renders
Then the relay-east row shows 2 in the Unread column
And the casbah row shows a dash in the Unread column

#### Scenario: Enter on a node navigates to peer workspace
Given the Home screen is displayed with nodes in the table
When the operator presses Enter on a selected node row
Then the app pushes MeshDeviceDetailScreen for that node's identity hash

#### Scenario: Empty mesh shows placeholder
Given no mesh nodes have been discovered
When the Home screen renders
Then the node table area shows a dim placeholder message indicating no nodes found

#### Scenario: Node summary updates when discovery changes
Given the Home screen is displayed with 2 known nodes
When a new node is discovered via announce
Then the node table adds the new node row within one refresh cycle

### Requirement: CommsSummaryWidget removed from Home compose

The Home screen no longer composes CommsSummaryWidget or the COMMS HighlightedPanel. The comms summary information (mail count, contacts count) is surfaced only through the unread column in the node table and the activity feed. CommsSummaryWidget continues to exist for any other consumer but is not mounted on DashboardScreen.

#### Scenario: Home screen does not contain CommsSummaryWidget
Given the Home screen is mounted
When querying the widget tree
Then no CommsSummaryWidget is found
And no panel with title COMMS is found
