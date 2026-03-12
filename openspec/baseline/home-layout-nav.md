# home-layout-nav

### Requirement: Home compose follows COP layout order

The Home screen composes top-to-bottom: Header, VersionMismatchBanner, HomeStatusBar panel, HomeNodeSummaryTable panel (1fr — takes remaining space), ActivityFeedWidget panel (compact, ~5 lines), Footer. The status bar panel uses height:auto, the activity panel uses a fixed or min-height, and the node table gets the remaining vertical space via 1fr.

#### Scenario: Home layout order is correct
Given the Home screen is mounted
When inspecting the widget tree under dashboard-container
Then the first panel contains HomeStatusBar
And the second panel contains HomeNodeSummaryTable
And the third panel contains ActivityFeedWidget

#### Scenario: Node table gets majority of vertical space
Given a terminal height of 24 lines
When the Home screen renders
Then the node table panel has more vertical lines than the status bar and activity feed combined

### Requirement: Activity feed on Home shows recent events

The Home screen composes an ActivityFeedWidget in a bottom panel. It displays the most recent 3-5 events from the daemon activity stream (node discovered, message received, hub connected/disconnected, announce sent). This is the same ActivityFeedWidget already used in ExplorationScreen's Diagnostics tab.

#### Scenario: Activity feed displays recent events
Given the daemon has emitted events: device_discovered, new_message, hub connection lost
When the Home screen renders
Then the activity feed shows those events with timestamps in reverse chronological order

#### Scenario: Activity feed scrolls when full
Given the activity feed has received more than 5 events
When viewing the Home screen
Then the activity feed shows the most recent events and older events are scrollable

## MODIFIED Requirements

### Requirement: Footer bindings reduced per Exchange consolidation

The app-level Binding list hides `c` (Comms) and `b` (Contacts) by setting `show=False`. These keys still function as fast-paths to Exchange tabs but no longer appear in the footer. This implements the existing tui-navigation-ux decision. The `p` (Provision) binding is also set to `show=False` since provisioning is an infrequent admin action, not a primary navigation target.

#### Scenario: Footer shows reduced binding set
Given the Home screen is displayed
When viewing the footer
Then the visible bindings include: Help, Admin, Nodes, Exchange, and Announce
And the bindings for Comms, Contacts, and Provision are not visible
And pressing c, b, or p still navigates to the correct destination

#### Scenario: Footer fits within 80 columns
Given a terminal width of 80 columns
When the Home screen renders
Then no footer content is clipped or causes horizontal overflow
