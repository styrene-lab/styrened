# Keymap Reference

Complete keybinding reference for the Styrene TUI. This document serves two purposes:
- document the **current** keybindings exactly as implemented today
- define the **target workspace navigation model** the structural refactor is converging toward

Bindings are organized by scope: global (app-level), per-screen, per-widget, and modal/setup.

Textual resolves key presses bottom-up: focused widget → screen → app. A screen
binding **shadows** an app binding on the same key while that screen is active.
Bindings marked `priority=True` bypass this hierarchy and always fire.

---

## Target Workspace Navigation Model

The refactored TUI is converging on these aggregate workspaces:
- **Home** — overview, alerts, activity, launch summaries
- **Nodes** — canonical peer discovery and browsing
- **Mail** — asynchronous store-and-forward correspondence
- **Comms** — synchronous/direct/live communication
- **Contacts** — identity and address-book management
- **Admin** — configuration, provisioning, setup, maintenance

And one canonical drill-down context:
- **Peer Workspace** — selected-peer view for status, mail, comms, pages, ops, and terminal

### Target navigation ownership

| Destination | Role | Notes |
|---|---|---|
| `Home` | Aggregate workspace | Root overview; not a peer browser |
| `Nodes` | Aggregate workspace | Canonical discovery/browsing surface |
| `Mail` | Aggregate workspace | Async inbox/search/compose/sync |
| `Comms` | Aggregate workspace | Direct, Active, Bridges, Presence |
| `Contacts` | Aggregate workspace | Directory-first, not a hidden inbox |
| `Admin` | Aggregate workspace | Settings, provision, setup/maintenance |
| `Peer Workspace` | Drill-down context | Must preserve origin so Back returns to Nodes, Mail, Comms, Contacts, or Home summary context |

### Target shortcut intent

These are the intended stable top-level destinations for the refactor. They are not all implemented yet, and they must be reconciled with current screen/widget bindings before adoption.

| Key | Target destination | Intent | Collision note |
|---|---|---|---|
| `h` | Home | Return to overview/root workspace | Currently used in Exploration for `toggle_hide_lost`; workable as a future global/workspace binding, but not collision-free today |
| `n` | Nodes | Open canonical node discovery | Currently one of the least-contended candidates |
| `m` | Mail | Open asynchronous correspondence | Currently one of the least-contended candidates |
| `c` | Comms | Open live/direct communication workspace | Currently heavily overloaded by screen-local chat/crawl actions, so adoption likely requires redirecting or demoting legacy `c` bindings first |
| `b` | Contacts | Open address book / identity directory | Already the current global Contacts shortcut and a good stable candidate |
| `` ` `` | Admin | Open settings/admin domain | Already the current Settings/Admin-adjacent shortcut; preferable to `s`, which is overloaded in current screens/widgets |

### Target navigation rules

- `Mail` and `Comms` are intentionally separate. Mail owns inbox-style async flows; Comms owns direct/live/session-oriented flows.
- `Mail` should present a unified async inbox across supported transports, with conversation scope (`direct`, `group`, `forum`) and transport shown as metadata rather than as protocol-silo tabs.
- `Peer Workspace` is not a top-level workspace. It is entered from Nodes, Mail, Comms, Contacts, or Home summaries.
- `Back` from Peer Workspace should return to the originating aggregate workspace rather than always collapsing to Home.
- `Comms` should eventually expose transport-aware submodes such as `Direct`, `Active`, `Bridges`, and `Presence`.
- Bridge-backed communication surfaces such as Meshtastic, Yggdrasil, and I2P belong under global Comms when authoritative daemon capability data exists.

---

## Current Binding Reference

## Global Bindings (App-Level)

Defined in `StyreneApp` (`src/styrened/tui/app.py`). Active on every screen
unless a screen or widget declares the same key.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Ctrl+C` | `interrupt` | Quit (double-press) | **Priority.** Single press pops current screen; double press within 1 s exits the app. |
| `?` | `toggle_help` | Help | Opens Textual help overlay. |
| `` ` `` | `push_screen_settings` | Admin | Opens Settings/Admin screen. No-op if already in stack. |
| `n` | `open_nodes` | Nodes | Opens the canonical Nodes workspace (`ExplorationScreen`). |
| `m` | `open_mail` | Mail | Opens the Mail workspace. No-op if already in stack. Requires daemon mode. |
| `c` | `open_comms` | Comms | Opens the aggregate Comms workspace shell. Screen-local `c` bindings still override this on some screens. |
| `b` | `open_contacts` | Contacts | Opens Contacts screen. No-op if already in stack. |
| `i` | `open_mail` | Mail | Hidden backward-compatible alias for Mail. |
| `p` | `open_provision` | Provision | Opens Provision screen. No-op if already in stack. |
| `Ctrl+R` | `restart_daemon` | Restart Daemon | Hidden binding. Restarts the daemon process. |
| `a` | `announce` | Announce | Triggers a Reticulum announce. |

**Key reuse notes:**
- `i` is global (Inbox) but Dashboard also binds `i` → `request_identity`. When
  Dashboard is focused the screen binding wins.
- `a` is global (Announce) but Contacts (`add_contact`), DeviceDetail
  (`add_contact`), and ChatWidget (`attach_file`) shadow it on their
  respective screens.

---

## Dashboard (`DashboardScreen`)

Home workspace overview. Default screen after startup.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Enter` | `select_device` | Details | Opens device detail for selected node. |
| `c` | `open_chat` | Chat | Opens chat with selected device. |
| `r` | `refresh` | Refresh | **Priority.** Refreshes Home summaries and current-node list. |
| `n` | `open_exploration` | Nodes | Opens the canonical Nodes workspace from Home. |
| `e` | `open_exploration` | Nodes | Hidden legacy alias while Home→Nodes migration settles. |
| `i` | `request_identity` | Request ID | Hidden. Requests identity from selected device in the Home current-nodes summary. Shadows global `i` (Inbox). |

---

## Local Dashboard (`LocalDashboardScreen`)

Compact single-column dashboard for Zellij pane use.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `q` | `quit` | Quit | Exits the app. |
| `r` | `refresh` | Refresh | Refreshes node status panels. |

---

## Inbox (`InboxScreen`)

Conversation list ordered by most recent message.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `go_back` | Back | Returns to previous screen. |
| `Enter` | `open_conversation` | Open | Opens selected conversation thread. |
| `n` | `compose_new` | New | Compose a new message. |
| `d` | `delete_conversation` | Delete | Deletes selected conversation. |
| `/` | `search_messages` | Search | Opens message search. |
| `s` | `sync_messages` | Sync | Syncs messages with daemon. |
| `o` | `cycle_sort` | Sort | Cycles sort mode: time → unread → name. |

---

## Contacts (`ContactsScreen`)

Contact management — add, edit, remove, resolve contacts.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `go_back` | Back | Returns to previous screen. |
| `Enter` | `open_chat` | Chat | Opens chat with selected contact. |
| `c` | `open_chat` | Chat | Hidden duplicate of Enter. |
| `a` | `add_contact` | Add | Add a new contact. Shadows global `a` (Announce). |
| `e` | `edit_contact` | Edit | Edit selected contact. |
| `Delete` | `delete_contact` | Delete | Delete selected contact. |
| `r` | `resolve_name` | Resolve | Resolve contact name via the mesh. |

---

## Conversation (`ConversationScreen`)

Message thread with a single peer. Embeds `ChatWidget` for messaging.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `app.pop_screen` | Back | Returns to previous screen. |
| `Ctrl+D` | `delete_conversation` | Delete All | Deletes entire conversation history. |
| `B` | `block_peer` | Block | Blocks the conversation peer. Case-sensitive (uppercase B). |

---

## Device Detail (`MeshDeviceDetailScreen`)

Tabbed detail view for a mesh device: Status, Chat, Fleet Ops, Terminal.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `app.pop_screen` | Back | Returns to previous screen. |
| `r` | `refresh_status` | Refresh | Refreshes device status via RPC. |
| `l` | `establish_link` | Link | Establishes a DirectLink to the device. |
| `t` | `run_speedtest` | Speedtest | Runs a link speed test. |
| `a` | `add_contact` | Add Contact | Saves device as a contact. Shadows global `a` (Announce). |
| `y` | `copy_hash` | Copy Hash | Copies the device identity hash to clipboard. |

---

## Nodes (`ExplorationScreen`)

Device discovery and mesh browsing.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `dismiss_search` | Back | **Priority.** Closes search or returns to previous screen. |
| `Enter` | `select_device` | Select | Opens the selected peer from Nodes into the peer workspace. |
| `c` | `open_chat` | Chat | Opens the selected peer directly into peer-workspace Comms context. |
| `r` | `refresh` | Refresh | Refreshes the active Nodes tab. |
| `n` | `app.pop_screen` | Home | Returns from Nodes to Home when no deeper transient state is active. |
| `h` | `toggle_hide_lost` | Hide Lost | Toggles visibility of lost devices. |
| `H` | `toggle_hide_stale` | Hide Stale | Toggles visibility of stale devices. Displayed as `Shift+H`. |
| `/` | `show_search` | Search | **Priority.** Opens inline device search. |
| `v` | `preview_page` | Preview | Opens NomadNet page preview for selected node. |

---

## Settings (`SettingsScreen`)

Configuration editor with tabbed sections.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `cancel` | Cancel | Discards changes and returns. |
| `Ctrl+S` | `save` | Save | Saves configuration changes. |
| `[` | `previous_tab` | Previous Tab | Hidden. Navigates to previous settings tab. |
| `]` | `next_tab` | Next Tab | Hidden. Navigates to next settings tab. |

---

## Provision (`ProvisionScreen`)

Edge device provisioning: Select → Configure → Confirm → Flash → Mesh watch.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Escape` | `app.pop_screen` | Back | Returns to previous screen. |
| `r` | `refresh_disks` | Refresh Disks | Rescans for connected storage devices. |

---

## Widget Bindings

Widgets declare their own bindings, active when the widget has focus. These
compose with the screen and app bindings above.

### ChatWidget (`src/styrened/tui/widgets/chat_widget.py`)

Embedded in Conversation and DeviceDetail screens.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Up` | `select_prev` | Prev Msg | Hidden. Selects previous message. |
| `Down` | `select_next` | Next Msg | Hidden. Selects next message. |
| `Escape` | `escape_handler` | Back | Hidden. Blurs input or deselects message. |
| `Tab` | `toggle_focus` | Toggle Focus | Hidden. Toggles focus between message list and input. |
| `R` | `retry_message` | Retry | Retries sending a failed message. Case-sensitive (uppercase R). |
| `Ctrl+R` | `retry_all_failed` | Retry All | **Priority.** Retries all failed messages. Shadows global `Ctrl+R` (Restart Daemon). |
| `d` | `delete_message` | Delete | Deletes selected message. |
| `/` | `open_search` | Search | Opens message search within conversation. |
| `r` | `reply_to_message` | Reply | Replies to selected message. |
| `y` | `copy_message` | Copy | Copies message content to clipboard. |
| `o` | `open_attachment` | Open | Opens message attachment in system viewer. |
| `a` | `attach_file` | Attach | Opens file picker to attach a file. Shadows global `a` (Announce). |
| `Ctrl+Y` | `attach_clipboard` | 📋 Attach | **Priority.** Attaches clipboard content as a file. |
| `Ctrl+V` | `paste_attachment` | Paste | Hidden. Pastes clipboard as attachment. |
| `B` | `block_peer` | Block | Blocks the peer. Case-sensitive (uppercase B). |

### TerminalWidget (`src/styrened/tui/widgets/terminal_widget.py`)

PTY-over-RNS interactive shell, embedded in DeviceDetail.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Ctrl+\` | `disconnect` | Disconnect | Terminates the remote terminal session. |

### PageBrowserWidget (`src/styrened/tui/widgets/page_browser.py`)

NomadNet page browser, embedded in Exploration.

| Key | Action | Description | Notes |
|-----|--------|-------------|-------|
| `Backspace` | `go_back` | Back | Navigates to previous page. |
| `F5` | `reload` | Reload | Reloads current page. |
| `u` | `focus_url` | URL | Focuses the URL input bar. |
| `s` | `save_site` | Save Site | Saves current site for offline access. |
| `c` | `crawl_site` | Crawl | Starts a BFS crawl of the current site. |

---

## Modal / Setup Screens

These screens appear during first-run or confirmation flows. They have minimal
bindings — mostly just Escape to dismiss.

### FirstRunWizardScreen

| Key | Action | Description |
|-----|--------|-------------|
| `Escape` | `cancel` | Skip Setup |

### DaemonSetupScreen

| Key | Action | Description |
|-----|--------|-------------|
| `Escape` | `skip` | Skip |

### ConfirmFlash (ModalScreen)

No explicit bindings. Uses Textual's default modal dismiss behavior.

### UpgradeScreen (ModalScreen)

No explicit bindings. Uses Textual's default modal dismiss behavior.

---

## Intentional Key Reuse

The following keys are intentionally bound to different actions depending on
context. Textual's bottom-up resolution ensures only the most specific binding
fires.

| Key | Scope | Action | Rationale |
|-----|-------|--------|-----------|
| `i` | App (global) | Open Inbox | Navigation shortcut. |
| `i` | Dashboard | Request ID | Dashboard-specific RPC action. Shadows global Inbox while on Dashboard. |
| `a` | App (global) | Announce | Mesh announce. |
| `a` | Contacts | Add Contact | Contextual "add" action. |
| `a` | DeviceDetail | Add Contact | Contextual "add" action. |
| `a` | ChatWidget | Attach File | Contextual "attach" action. |
| `r` | Dashboard | Refresh | Common refresh pattern. |
| `r` | Exploration | Refresh | Common refresh pattern. |
| `r` | Contacts | Resolve Name | Contextual action. |
| `r` | DeviceDetail | Refresh Status | Common refresh pattern. |
| `r` | Provision | Refresh Disks | Common refresh pattern. |
| `r` | ChatWidget | Reply | Contextual messaging action. |
| `Ctrl+R` | App (global) | Restart Daemon | Hidden power-user action. |
| `Ctrl+R` | ChatWidget | Retry All Failed | **Priority** — always wins when ChatWidget is focused. |
| `c` | Dashboard | Open Chat | Contextual chat. |
| `c` | Exploration | Open Chat | Contextual chat. |
| `c` | Contacts | Open Chat | Duplicate of Enter. |
| `c` | PageBrowser | Crawl Site | Contextual browser action. |
| `/` | Inbox | Search Messages | Search within inbox. |
| `/` | Exploration | Show Search | **Priority** — search within device list. |
| `/` | ChatWidget | Open Search | Search within conversation. |
| `Escape` | Various | Back / Cancel / Dismiss | Universal "go back" across all screens. |
| `B` | Conversation | Block Peer | Uppercase B to avoid accidental activation. |
| `B` | ChatWidget | Block Peer | Same action, available in both contexts. |
| `Enter` | Dashboard | Select Device | Context-dependent selection. |
| `Enter` | Exploration | Select Device | Context-dependent selection. |
| `Enter` | Inbox | Open Conversation | Context-dependent selection. |
| `Enter` | Contacts | Open Chat | Context-dependent selection. |

---

## Binding Count

**75 total `Binding()` declarations** across all files in `src/styrened/tui/`.

| Location | Count |
|----------|-------|
| `app.py` (global) | 8 |
| `dashboard.py` | 5 |
| `dashboard_local.py` | 2 |
| `inbox.py` | 7 |
| `contacts.py` | 7 |
| `conversation.py` | 3 |
| `mesh_device_detail.py` | 6 |
| `exploration.py` | 8 |
| `settings.py` | 4 |
| `provision.py` | 2 |
| `first_run_wizard.py` | 1 |
| `daemon_setup.py` | 1 |
| `chat_widget.py` | 15 |
| `terminal_widget.py` | 1 |
| `page_browser.py` | 5 |
| **Total** | **75** |
