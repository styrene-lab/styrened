# Keymap Contract

Documented keybinding ownership across all screens.

## Requirements

### REQ-KEY-1: KEYMAP.md documents all bindings

A `docs/KEYMAP.md` file documents every keybinding in the TUI organized by scope: global (app-level), per-screen, and modal. Each entry shows the key, action, description, and which screen owns it.

#### Scenario: KEYMAP.md exists and covers all screens
- Given `docs/KEYMAP.md`
- When checking for screen sections
- Then sections exist for: App (global), Dashboard, Inbox, Contacts, Conversation, DeviceDetail, Exploration, Settings, Provision

### REQ-KEY-2: No undocumented bindings

Every `Binding(...)` declaration in `src/styrened/tui/` has a corresponding entry in `docs/KEYMAP.md`.

#### Scenario: Binding count matches KEYMAP documentation
- Given all `Binding(` declarations in `src/styrened/tui/`
- When counting unique (screen, key) pairs
- Then the count matches the number of entries in KEYMAP.md
