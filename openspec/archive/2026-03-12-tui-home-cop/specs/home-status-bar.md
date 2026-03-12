# home-status-bar — Delta Spec

## ADDED Requirements

### Requirement: Compact horizontal status bar replaces NodeInfoPanel on Home

The Home screen's top panel renders a compact 1-2 line horizontal status bar instead of the current multi-line two-column NodeInfoPanel. The bar shows key subsystem indicators (RNS, Hub, Mesh count, IPC, Unread) separated by delimiters. All fields are always present. Nominal fields render dim; anomalous fields render bright with warning/error color. The bar occupies minimal vertical space (height: auto) so the node table below gets maximum real estate.

#### Scenario: Status bar renders all nominal state dimmed
Given the daemon is connected with RNS online (1 interface), hub connected, 4 mesh nodes, IPC connected for 34 seconds, and 0 unread messages
When the Home screen renders
Then the status bar shows all indicators in dim/nominal color
And no indicator uses warning or error color

#### Scenario: Status bar promotes hub disconnected as anomaly
Given the daemon is connected with RNS online but hub status is disconnected
When the Home screen renders
Then the hub indicator renders in warning/bright color
And all other nominal indicators render dim

#### Scenario: Status bar promotes RNS offline as anomaly
Given the daemon reports RNS is offline with an error state
When the Home screen renders
Then the RNS indicator renders in error/bright color
And a recovery hint is shown if available

#### Scenario: Status bar shows unread count when messages exist
Given there are 3 unread messages across conversations
When the Home screen renders
Then the status bar includes an unread indicator showing the count in bright color

#### Scenario: Status bar fits within standard terminal widths
Given a terminal width of 80 columns
When the Home screen renders
Then the status bar does not overflow horizontally or cause a scrollbar

### Requirement: NodeInfoPanel state drives the status bar

The new status bar widget (HomeStatusBar) reads the same reactive properties currently exposed by NodeInfoPanel (rns_online, hub_status, interface_count, styrene_mesh_count, daemon_connected, daemon_uptime, messages_received, pending_deliveries, error_state). The existing _fetch_daemon_status() worker in DashboardScreen updates these properties. NodeInfoPanel continues to exist as a widget for other screens (LocalDashboard) but is no longer composed on the main Home screen.

#### Scenario: Status bar updates when daemon status changes
Given the Home screen is displayed with hub connected
When the daemon reports hub disconnected via IPC status update
Then the status bar updates the hub indicator to warning/bright within one refresh cycle

#### Scenario: NodeInfoPanel remains available for LocalDashboard
Given the LocalDashboardScreen is displayed
When it composes its layout
Then it uses the existing NodeInfoPanel widget (not the new HomeStatusBar)
