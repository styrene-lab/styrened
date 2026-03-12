# workspace-nav — Stable Workspace Navigation

## Requirement: Six stable top-level workspaces

#### Scenario: workspace navigation covers all six areas
Given the TUI is running
When the operator presses workspace hotkeys (grave/1-6 or via header)
Then the six workspaces Home, Nodes, Mail, Comms, Contacts, Admin are reachable
And each workspace has a distinct screen with a distinct purpose
And no workspace duplicates content owned by another workspace

#### Scenario: Dashboard renders only Home-scope content
Given the operator opens Home (workspace 1 / default)
When DashboardScreen mounts
Then it shows: local node status summary, recent activity/alerts, and quick-launch actions
And it does NOT render a full peer-browsing tree (that belongs in Nodes)
And it does NOT show protocol-level transport tabs (Yggdrasil, I2P) as standalone sections

#### Scenario: Nodes workspace owns peer browsing
Given the operator opens Nodes (workspace 2)
When ExplorationScreen mounts
Then the full peer tree (My Mesh / Other Styrene Nodes) renders there
And selecting a peer opens the peer workspace as a drill-down, not a new top-level workspace

#### Scenario: Comms workspace only shows bridge-backed transports with capability evidence
Given the operator opens Comms (workspace 4)
When CommsScreen mounts
Then Yggdrasil is shown only when daemon reports yggdrasil capability active
And I2P is shown only when daemon reports i2p capability active
And placeholder panels are replaced with capability-driven content or hidden
