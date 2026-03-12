# peer-workspace — MeshDeviceDetailScreen as Canonical Peer Workspace

## Requirement: MeshDeviceDetailScreen exposes PeerWorkspaceFocus tabs

#### Scenario: peer workspace has focus tabs
Given the operator selects a peer from Nodes (ExplorationScreen)
When MeshDeviceDetailScreen mounts
Then it shows tabs: Status, Mail, Comms, Pages, Ops, Terminal
And the active tab is determined by PeerWorkspaceFocus.STATUS by default
And Back navigation returns the operator to the originating workspace (Nodes, Mail, Comms, or Contacts)

#### Scenario: origin-aware back navigation
Given the operator opened the peer workspace from Mail
When they press Back
Then they return to Mail, not to Nodes
And the originating workspace context (scroll position, selected thread) is preserved

#### Scenario: Mail tab in peer workspace shows peer-scoped thread list
Given the operator opens the Mail tab in the peer workspace
When the tab mounts
Then it shows only threads with this peer (direct mail + shared group threads)
And it does not show the global inbox

#### Scenario: Terminal tab is RBAC-gated
Given the operator opens the Terminal tab in the peer workspace
When the operator has PEER or MONITOR role only
Then the Terminal tab is hidden or shows an "Unauthorized" notice
And no terminal session is started

## Requirement: Back navigation is origin-aware

#### Scenario: peer workspace opened from Nodes returns to Nodes
Given origin = WorkspaceId.NODES
When operator presses Back in peer workspace
Then ExplorationScreen is shown

#### Scenario: peer workspace opened from Mail returns to Mail
Given origin = WorkspaceId.MAIL
When operator presses Back
Then InboxScreen is shown
