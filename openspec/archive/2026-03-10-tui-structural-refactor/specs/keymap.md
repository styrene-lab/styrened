# Keymap Contract

Documented keybinding ownership across the current TUI and the target workspace architecture.

## Requirements

### REQ-KEY-1: KEYMAP.md documents both current bindings and the target workspace model

A `docs/KEYMAP.md` file documents every current keybinding in the TUI organized by scope: global (app-level), per-screen, per-widget, and modal. It also documents the planned target workspace navigation model so the refactor can converge on stable ownership for Home, Nodes, Mail, Comms, Contacts, Admin, and Peer Workspace.

#### Scenario: KEYMAP.md covers current bindings and target workspaces
- Given `docs/KEYMAP.md`
- When checking the document structure
- Then sections exist for current bindings, widget bindings, modal/setup bindings, and intentional key reuse
- And a target-workspace section exists for Home, Nodes, Mail, Comms, Contacts, Admin, and Peer Workspace

### REQ-KEY-2: No undocumented current bindings

Every current `Binding(...)` declaration in `src/styrened/tui/` has a corresponding entry in `docs/KEYMAP.md`.

#### Scenario: Binding count matches current KEYMAP documentation
- Given all `Binding(` declarations in `src/styrened/tui/`
- When counting unique (screen or widget, key) pairs
- Then the count matches the number of current-binding entries in `docs/KEYMAP.md`

### REQ-KEY-3: Target workspace navigation reserves stable top-level shortcuts

The target keymap SHALL reserve a stable top-level navigation layer for Home, Nodes, Mail, Comms, Contacts, and Admin even while legacy screens still exist underneath.

#### Scenario: Target keymap distinguishes aggregate workspaces from drill-down contexts
- Given the target workspace architecture
- When documenting navigation ownership
- Then Home, Nodes, Mail, Comms, Contacts, and Admin are treated as aggregate destinations
- And Peer Workspace is documented as a drill-down context rather than a top-level aggregate workspace

#### Scenario: Mail and Comms use separate navigation ownership
- Given the operator wants asynchronous correspondence or synchronous communication
- When using the target keymap
- Then Mail is documented as the destination for inbox-style store-and-forward workflows
- And Comms is documented as the destination for direct/live/session-oriented workflows and bridge-backed communication
