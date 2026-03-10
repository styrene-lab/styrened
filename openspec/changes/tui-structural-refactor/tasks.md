# tui-structural-refactor — Tasks

## Group 1: IPC Expansion (new daemon-side commands)

Add 5 new IPC commands so the TUI can fetch data it currently gets via direct imports.

### Task 1.1: IPC protocol + message types
- [x] Add `IPCMessageType` entries: `GET_NODES`, `GET_CORE_CONFIG`, `SAVE_CORE_CONFIG`, `GET_HUB_STATUS`, `GET_UNREAD_COUNTS`
- [x] Add request/response message classes in `ipc/messages.py`
- **Scope**: `src/styrened/ipc/protocol.py`, `src/styrened/ipc/messages.py`

### Task 1.2: IPC handlers
- [x] Implement `handle_get_nodes` — calls `get_node_store().get_all_nodes()`, serializes to dicts
- [x] Implement `handle_get_core_config` — calls `load_core_config()`, serializes
- [x] Implement `handle_save_core_config` — deserializes, calls `save_core_config()`
- [x] Implement `handle_get_hub_status` — calls `get_hub_connection()`, returns status dict
- [x] Implement `handle_get_unread_counts` — queries messages DB for unread counts per peer
- [x] Register handlers in `ipc/server.py`
- **Scope**: `src/styrened/ipc/handlers.py`, `src/styrened/ipc/server.py`
- **Tests**: `tests/unit/test_ipc_handlers.py` (5 new handler tests)

### Task 1.3: IPC client + bridge methods
- [x] Add client methods in `ipc/client.py`: `get_nodes()`, `get_core_config()`, `save_core_config()`, `get_hub_status()`, `get_unread_counts()`
- [x] Add bridge methods in `tui/services/ipc_bridge.py`: same 5 methods
- [x] Fold page-browser transport support into the bridge contract so TUI page browsing can open explicit external URLs (`https://` and `.i2p`) through daemon IPC rather than direct service imports
- **Scope**: `src/styrened/ipc/client.py`, `src/styrened/tui/services/ipc_bridge.py`

## Group 1.5: Shared UI-facing state model

Define a frontend-agnostic post-IPC state layer that the TUI consumes first, but which other visual frontends can also reuse.

- [x] Create `src/styrened/ui_state/` (or equivalent shared package outside `tui/`) for canonical typed UI-facing state
- [x] Add canonical aggregates for node catalog, mail index, comms workspace state, peer workspace context, config draft state, local daemon state, and page-browser session state
  - Completed: node catalog, mail index, comms workspace state, peer workspace context, config draft state, local daemon state, and page-browser session state
- [x] Make the mail index conversation-scope aware so it can represent direct identity threads, private group threads with room/epoch metadata, and forum/topic threads without protocol-silo tabs
- [x] Add normalization helpers that convert authoritative IPC payloads into canonical state objects
- [x] Add explicit origin-aware peer-workspace routing context so Back navigation can return to Nodes, Mail, or Comms correctly
- [x] Keep Textual-specific screen/view-model adapters out of the shared state package
- [x] Add focused tests for normalization rules, nullability/unknown semantics, and identity-centric node merging
- **Scope**: `src/styrened/ui_state/` (new), `tests/unit/` for shared state normalization

## Group 2: TUIServices Protocol + App Integration

### Task 2.1: TUIServices protocol
- [x] Create `src/styrened/tui/services/protocol.py` with `TUIServices` Protocol
- [x] Protocol exposes: `bridge` property, `local_identity_hash` property, `get_unread_counts()` async method
- [x] Create `ServicesMixin` or add `services` property to `StyreneApp`
- **Scope**: `src/styrened/tui/services/protocol.py`, `src/styrened/tui/app.py`

### Task 2.2: Move pure functions to tui/utils.py
- [x] Move `_deduplicate_by_identity()` to `src/styrened/tui/utils.py`
- [x] Move/inline `META_MAX_RETRIES` constant
- **Scope**: `src/styrened/tui/utils.py` (new)

## Group 3: Screen + Widget Migration

Migrate all screens and widgets to use TUIServices + IPC bridge instead of direct imports.

### Task 3.1: Dashboard screen migration
- [x] Replace `load_core_config()` calls (4 sites) with `bridge.get_core_config()`
- [x] Replace `get_node_store()` calls (2 sites) with `bridge.get_nodes()`
- [x] Replace `_deduplicate_by_identity` with shared node-catalog normalization, not a screen helper
- [x] Replace `get_hub_connection` with `bridge.get_hub_status()`
- [x] Replace `META_MAX_RETRIES` import
- [x] Replace `app._lifecycle.ipc_bridge` with `self.services.bridge`
- [x] Remove `db_engine` / SQLAlchemy Session access
- [x] Make Dashboard consume canonical shared state objects plus a thin Textual-specific projection layer
- **Scope**: `src/styrened/tui/screens/dashboard.py`

### Task 3.2: Exploration screen migration
- [x] Replace `get_node_store()` calls (3 sites) with `bridge.get_nodes()`
- [x] Replace `_deduplicate_by_identity` calls (3 sites) with shared node-catalog normalization
- [x] Replace `app._lifecycle.ipc_bridge` pattern
- [x] Make Exploration the first thin vertical slice over canonical node-catalog state if a lower-blast-radius pilot is preferred
- [x] Reframe Exploration as the future Nodes workspace and route peer selection through origin-aware peer-workspace context
- **Scope**: `src/styrened/tui/screens/exploration.py`

### Task 3.3: Device detail screen migration
- [x] Replace `get_node_store()` calls (2 sites) with `bridge.get_nodes()`
- [x] Replace `app._lifecycle.ipc_bridge` pattern
- [x] Keep `StatusResponse` as TYPE_CHECKING import
- [ ] Evolve the screen toward a canonical peer workspace with explicit Mail, Comms, Pages, Ops, and Terminal focus targets
- [x] Preserve origin workspace metadata so Back returns to Nodes, Mail, Comms, or Contacts correctly
- **Scope**: `src/styrened/tui/screens/mesh_device_detail.py`

### Task 3.4: Settings screen migration
- [x] Replace `load_core_config()` / `save_core_config()` calls with bridge methods
- [ ] Replace `generate_rns_config()` — move to server-side via save_core_config
- [x] Replace `get_node_store()` call
- [x] Replace `app._lifecycle.ipc_bridge` pattern
- **Scope**: `src/styrened/tui/screens/settings.py`

### Task 3.5: Other screens migration (mail, conversation, contacts, daemon_setup)
- [x] Replace `app._lifecycle.ipc_bridge` pattern in all 4 screens
- [x] Replace `ControlClient` import in daemon_setup
- [x] Reframe Inbox as the future Mail workspace for asynchronous correspondence
- [x] Add mail-thread models and routing that distinguish direct, group, and forum scope kinds while keeping the default inbox unified
  - Done so far: canonical mail-thread state models, scope kinds, Mail workspace aliasing, Inbox consumption of `MailIndexState`, scope-aware open dispatch, and dedicated placeholder destinations for room-centric group threads and topic-centric forum threads
  - Remaining: replace placeholder destinations with full group-room and Pages-adjacent forum discussion workflows
- [ ] Extend group-thread state and UI to model participant reachability as transport-unified but capability-aware
  - Done so far: canonical room participants can carry highest-available interface, fallback interfaces, delivery-path class, and media-friction flags; the group-thread placeholder screen now renders that state
  - Remaining: wire authoritative daemon/runtime inputs into these records and add operator actions on top
- [ ] Surface highest-available authoritative interface, fallback route metadata, and media-friction/confirmation hints for constrained participants such as LoRa-only peers
  - Done so far: placeholder group-thread UI surfaces these hints and local group-thread feature tier summary
  - Remaining: add interactive send/invite/media decision flows that consume the metadata
- [ ] Keep group invitations identity-targeted and room-centric, not transport-silo specific, even when delivery chooses different routes per participant
- [x] Add an explicit group-thread feature/storage tier setting with hardware-informed first-run defaults and clear operator override semantics
  - Completed: core config now has explicit `group_threads` policy fields, a heuristic helper for first-run tier selection from coarse hardware signals, an operator-facing Settings UI section that edits and persists the policy fields, and automatic first-run application during default config creation
  - Notes: first-run auto-tier can still be disabled explicitly by the operator via `group_threads.first_run_auto_tier`
- [ ] Make constrained tiers degrade by bounded retention, metadata-first sync, and disabled/confirmed expensive media actions rather than by hiding or forking rooms
  - Done so far: local policy is now operator-configurable, hardware-informed on first run, and clearly explained inside the dedicated group-room UI with explicit history/sync/media/catch-up behavior plus policy-driven media warnings
  - Remaining: connect these policy semantics to actual invite/send/media action flows and authoritative runtime snapshots
- [x] Keep ConversationScreen as compatibility-only mail-thread UI until peer-workspace mail context supersedes it
- [x] Make Contacts launch explicitly into Mail or Comms instead of acting as a generic chat surface
- **Scope**: `src/styrened/tui/screens/inbox.py`, `conversation.py`, `contacts.py`, `daemon_setup.py`

### Task 3.6: Widget migration
- [x] node_info_panel: Replace `get_hub_connection`, `get_operator_identity`, `get_node_store`, `_deduplicate_by_identity`, remove `db_engine` access
- [x] chat_widget: Replace `IPCMessageType` import path, `app._lifecycle` pattern, `attachment_store` import
- [x] command_widget: Replace `app._lifecycle` and `app.rpc_client` patterns
- [x] terminal_widget: Replace `IPCMessageType` import, `app._lifecycle` pattern
- [x] message_bubble: Replace `app._lifecycle` pattern
- [x] page_browser: Replace `app._lifecycle` pattern
- [x] page_browser: add explicit external-URL mode so the refactored TUI can browse parallel HTTPS and I2P docs endpoints without implicit fallback, while keeping NomadNet-specific save/crawl/form actions gated to NomadNet destinations
- [x] device_status_widget: Keep `StatusResponse` as TYPE_CHECKING
- [ ] Add workspace-facing projections so widgets can render Mail vs Comms capabilities without embedding navigation policy
- **Scope**: `src/styrened/tui/widgets/` (7 files)

## Group 3.7: Workspace architecture migration

- [ ] Introduce stable top-level workspace concepts: Home, Nodes, Mail, Comms, Contacts, Admin
  - Done so far: stable workspace identifiers, Mail naming in app navigation, and origin-aware routing contexts for Home/Nodes/Mail/Contacts
  - Remaining: complete top-level screen/navigation surfacing for Nodes/Comms/Admin model
- [x] Add a new aggregate Comms workspace with transport-aware submodes Direct, Active, Bridges, and Presence
- [x] Route dashboard/exploration chat shortcuts to Peer Workspace Comms context instead of bespoke chat entry paths
- [ ] Narrow Dashboard into Home summaries/alerts/activity and move canonical peer browsing into Nodes
- [ ] Surface bridge-backed transports such as Meshtastic, Yggdrasil, and I2P in Comms only when authoritative daemon capability data exists
- **Scope**: `src/styrened/tui/app.py`, `src/styrened/tui/screens/`, `src/styrened/ui_state/`, `tests/tui/`

## Group 4: Legacy Mode Removal

### Task 4.1: Remove legacy lifecycle
- [x] Remove `LifecycleMode.LEGACY` and `LifecycleMode.AUTO` from enum
- [x] Remove `StyreneLifecycle._initialize_legacy()` method
- [x] Remove `StyreneLifecycle._core` attribute (CoreLifecycle)
- [x] Remove all `if active_mode == LEGACY` branches
- [x] Remove `CoreLifecycle` import from TUI
- [x] Simplify `_initialize_async()` to IPC-only path
- **Scope**: `src/styrened/tui/services/app_lifecycle.py`

### Task 4.2: Remove use_ipc config
- [x] Remove `TUIConfig.use_ipc` field
- [x] Remove `use_ipc` serialization/deserialization in config.py
- [x] Ensure old configs with `use_ipc: false` parse without error (ignore unknown field)
- **Scope**: `src/styrened/tui/models/config.py`, `src/styrened/tui/services/config.py`

### Task 4.3: Remove legacy references in app.py
- [x] Remove `LifecycleMode.LEGACY` check in app startup
- [x] Clean up any remaining legacy conditional branches
- **Scope**: `src/styrened/tui/app.py`

## Group 5: Keymap Documentation

### Task 5.1: Write KEYMAP.md
- [x] Audit all `Binding(...)` declarations across app.py and all screens
- [x] Document in `docs/KEYMAP.md`: global bindings, per-screen bindings, modals
- [x] Note intentional key reuse (e.g. `r` = refresh on every screen)
- **Scope**: `docs/KEYMAP.md` (new)

## Group 6: Test Updates

### Task 6.1: Update TUI tests for new patterns
- [ ] Update tests that reference `app._lifecycle.ipc_bridge` to use services
- [ ] Update tests that mock `load_core_config` or `get_node_store` in TUI context
- [x] Verify existing TUI tests pass with legacy mode removed
- **Scope**: `tests/tui/`, `tests/unit/tui/`
