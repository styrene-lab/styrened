# tui-structural-refactor — Tasks

## Group 1: IPC Expansion (new daemon-side commands)

Add 5 new IPC commands so the TUI can fetch data it currently gets via direct imports.

### Task 1.1: IPC protocol + message types
- [ ] Add `IPCMessageType` entries: `GET_NODES`, `GET_CORE_CONFIG`, `SAVE_CORE_CONFIG`, `GET_HUB_STATUS`, `GET_UNREAD_COUNTS`
- [ ] Add request/response message classes in `ipc/messages.py`
- **Scope**: `src/styrened/ipc/protocol.py`, `src/styrened/ipc/messages.py`

### Task 1.2: IPC handlers
- [ ] Implement `handle_get_nodes` — calls `get_node_store().get_all_nodes()`, serializes to dicts
- [ ] Implement `handle_get_core_config` — calls `load_core_config()`, serializes
- [ ] Implement `handle_save_core_config` — deserializes, calls `save_core_config()`
- [ ] Implement `handle_get_hub_status` — calls `get_hub_connection()`, returns status dict
- [ ] Implement `handle_get_unread_counts` — queries messages DB for unread counts per peer
- [ ] Register handlers in `ipc/server.py`
- **Scope**: `src/styrened/ipc/handlers.py`, `src/styrened/ipc/server.py`
- **Tests**: `tests/unit/test_ipc_handlers.py` (5 new handler tests)

### Task 1.3: IPC client + bridge methods
- [ ] Add client methods in `ipc/client.py`: `get_nodes()`, `get_core_config()`, `save_core_config()`, `get_hub_status()`, `get_unread_counts()`
- [ ] Add bridge methods in `tui/services/ipc_bridge.py`: same 5 methods
- **Scope**: `src/styrened/ipc/client.py`, `src/styrened/tui/services/ipc_bridge.py`

## Group 2: TUIServices Protocol + App Integration

### Task 2.1: TUIServices protocol
- [ ] Create `src/styrened/tui/services/protocol.py` with `TUIServices` Protocol
- [ ] Protocol exposes: `bridge` property, `local_identity_hash` property, `get_unread_counts()` async method
- [ ] Create `ServicesMixin` or add `services` property to `StyreneApp`
- **Scope**: `src/styrened/tui/services/protocol.py`, `src/styrened/tui/app.py`

### Task 2.2: Move pure functions to tui/utils.py
- [ ] Move `_deduplicate_by_identity()` to `src/styrened/tui/utils.py`
- [ ] Move/inline `META_MAX_RETRIES` constant
- **Scope**: `src/styrened/tui/utils.py` (new)

## Group 3: Screen + Widget Migration

Migrate all screens and widgets to use TUIServices + IPC bridge instead of direct imports.

### Task 3.1: Dashboard screen migration
- [ ] Replace `load_core_config()` calls (4 sites) with `bridge.get_core_config()`
- [ ] Replace `get_node_store()` calls (2 sites) with `bridge.get_nodes()`
- [ ] Replace `_deduplicate_by_identity` with tui/utils import
- [ ] Replace `get_hub_connection` with `bridge.get_hub_status()`
- [ ] Replace `META_MAX_RETRIES` import
- [ ] Replace `app._lifecycle.ipc_bridge` with `self.services.bridge`
- [ ] Remove `db_engine` / SQLAlchemy Session access
- **Scope**: `src/styrened/tui/screens/dashboard.py`

### Task 3.2: Exploration screen migration
- [ ] Replace `get_node_store()` calls (3 sites) with `bridge.get_nodes()`
- [ ] Replace `_deduplicate_by_identity` calls (3 sites) with tui/utils
- [ ] Replace `app._lifecycle.ipc_bridge` pattern
- **Scope**: `src/styrened/tui/screens/exploration.py`

### Task 3.3: Device detail screen migration
- [ ] Replace `get_node_store()` calls (2 sites) with `bridge.get_nodes()`
- [ ] Replace `app._lifecycle.ipc_bridge` pattern
- [ ] Keep `StatusResponse` as TYPE_CHECKING import
- **Scope**: `src/styrened/tui/screens/mesh_device_detail.py`

### Task 3.4: Settings screen migration
- [ ] Replace `load_core_config()` / `save_core_config()` calls with bridge methods
- [ ] Replace `generate_rns_config()` — move to server-side via save_core_config
- [ ] Replace `get_node_store()` call
- [ ] Replace `app._lifecycle.ipc_bridge` pattern
- **Scope**: `src/styrened/tui/screens/settings.py`

### Task 3.5: Other screens migration (inbox, conversation, contacts, daemon_setup)
- [ ] Replace `app._lifecycle.ipc_bridge` pattern in all 4 screens
- [ ] Replace `ControlClient` import in daemon_setup
- **Scope**: `src/styrened/tui/screens/inbox.py`, `conversation.py`, `contacts.py`, `daemon_setup.py`

### Task 3.6: Widget migration
- [ ] node_info_panel: Replace `get_hub_connection`, `get_operator_identity`, `get_node_store`, `_deduplicate_by_identity`, remove `db_engine` access
- [ ] chat_widget: Replace `IPCMessageType` import path, `app._lifecycle` pattern, `attachment_store` import
- [ ] command_widget: Replace `app._lifecycle` and `app.rpc_client` patterns
- [ ] terminal_widget: Replace `IPCMessageType` import, `app._lifecycle` pattern
- [ ] message_bubble: Replace `app._lifecycle` pattern
- [ ] page_browser: Replace `app._lifecycle` pattern
- [ ] device_status_widget: Keep `StatusResponse` as TYPE_CHECKING
- **Scope**: `src/styrened/tui/widgets/` (7 files)

## Group 4: Legacy Mode Removal

### Task 4.1: Remove legacy lifecycle
- [ ] Remove `LifecycleMode.LEGACY` and `LifecycleMode.AUTO` from enum
- [ ] Remove `StyreneLifecycle._initialize_legacy()` method
- [ ] Remove `StyreneLifecycle._core` attribute (CoreLifecycle)
- [ ] Remove all `if active_mode == LEGACY` branches
- [ ] Remove `CoreLifecycle` import from TUI
- [ ] Simplify `_initialize_async()` to IPC-only path
- **Scope**: `src/styrened/tui/services/app_lifecycle.py`

### Task 4.2: Remove use_ipc config
- [ ] Remove `TUIConfig.use_ipc` field
- [ ] Remove `use_ipc` serialization/deserialization in config.py
- [ ] Ensure old configs with `use_ipc: false` parse without error (ignore unknown field)
- **Scope**: `src/styrened/tui/models/config.py`, `src/styrened/tui/services/config.py`

### Task 4.3: Remove legacy references in app.py
- [ ] Remove `LifecycleMode.LEGACY` check in app startup
- [ ] Clean up any remaining legacy conditional branches
- **Scope**: `src/styrened/tui/app.py`

## Group 5: Keymap Documentation

### Task 5.1: Write KEYMAP.md
- [ ] Audit all `Binding(...)` declarations across app.py and all screens
- [ ] Document in `docs/KEYMAP.md`: global bindings, per-screen bindings, modals
- [ ] Note intentional key reuse (e.g. `r` = refresh on every screen)
- **Scope**: `docs/KEYMAP.md` (new)

## Group 6: Test Updates

### Task 6.1: Update TUI tests for new patterns
- [ ] Update tests that reference `app._lifecycle.ipc_bridge` to use services
- [ ] Update tests that mock `load_core_config` or `get_node_store` in TUI context
- [ ] Verify existing TUI tests pass with legacy mode removed
- **Scope**: `tests/tui/`, `tests/unit/tui/`
