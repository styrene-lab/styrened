# tui

### Requirement: tui core functionality

Implement GlobalCopScreen — a monitor-first TUI workspace (keybinding g) with four zones: aggregate health bar, health-sorted Styrene fleet table, ephemeral alert list, and live activity feed with backfill. Styrene-primary fleet view with toggle to expand to all discovered peers.

#### Scenario: Happy path

Given the system is in a default state
When the tui feature is exercised
Then the expected behavior is observed

### Requirement: GlobalCopScreen is a new dedicated screen

Monitor-first, separate from browse-first Nodes. Keybinding g. Registered in app SCREENS map. action_open_global_cop replaces the stub notify.

#### Scenario: GlobalCopScreen is a new dedicated screen — default case

Given the system uses the decided approach
When globalcopscreen is a new dedicated screen is applied
Then the system behaves according to the decision

### Requirement: Fleet table is Styrene-primary

Default view shows only Styrene nodes — RPC-queryable health, daemon version, capability diff. Tab/f toggles to all discovered peers.

#### Scenario: Fleet table is Styrene-primary — default case

Given the system uses the decided approach
When fleet table is styrene-primary is applied
Then the system behaves according to the decision

### Requirement: Alert list is ephemeral

In-memory per TUI session. Alerts re-derive from live state. Auto-resolves when condition clears.

#### Scenario: Alert list is ephemeral — default case

Given the system uses the decided approach
When alert list is ephemeral is applied
Then the system behaves according to the decision

### Requirement: Activity feed subscribed at mount with backfill

Uses GET_ACTIVITY_HISTORY ring buffer (already implemented). No lazy tab-click subscription.

#### Scenario: Activity feed subscribed at mount with backfill — default case

Given the system uses the decided approach
When activity feed subscribed at mount with backfill is applied
Then the system behaves according to the decision
