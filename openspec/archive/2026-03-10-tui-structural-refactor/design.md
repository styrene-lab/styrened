# tui-structural-refactor — Design

## Architecture

### TUIServices Protocol

New file: `src/styrened/tui/services/protocol.py`

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TUIServices(Protocol):
    """Typed contract between screens/widgets and the app."""
    
    @property
    def bridge(self) -> "IPCBridge": ...
    
    @property
    def local_identity_hash(self) -> str: ...
    
    async def get_unread_counts(self) -> dict[str, int]: ...
```

Screens access via `self.services` property provided by a `ServicesMixin` or on the Screen base.

### IPC Expansion

New IPC commands (server + client + bridge):
- `CMD_GET_NODES` → replaces `get_node_store().get_all_nodes()` / `.get_styrene_nodes()`
- `CMD_GET_CORE_CONFIG` → replaces `load_core_config()`
- `CMD_SAVE_CORE_CONFIG` → replaces `save_core_config()`
- `CMD_GET_HUB_STATUS` → replaces `get_hub_connection()`
- `CMD_GET_UNREAD_COUNTS` → replaces direct SQLAlchemy sessions for unread counts

### Data Flow Migration

Direct imports to replace:
- `get_node_store()` (9 call sites) → `bridge.get_nodes()`
- `load_core_config()` (7 call sites) → `bridge.get_core_config()` 
- `save_core_config()` (5 call sites) → `bridge.save_core_config()`
- `get_hub_connection()` (3 call sites) → `bridge.get_hub_status()`
- `_deduplicate_by_identity()` (4 call sites) → move to `styrened.tui.utils` (pure function, no daemon dependency)
- `generate_rns_config()` (3 call sites) → `bridge.save_core_config()` handles this server-side
- `get_operator_identity()` (2 call sites) → `bridge.get_identity()` (already exists)
- `app.db_engine` (3 call sites) → `bridge.get_unread_counts()` / remove
- `META_MAX_RETRIES` constant (1 site) → inline or move to tui constants
- `StatusResponse` type (2 sites) → keep as TYPE_CHECKING import (data model, not service)

### Legacy Removal

Delete:
- `LifecycleMode.LEGACY` and `LifecycleMode.AUTO` enum values
- `StyreneLifecycle._initialize_legacy()` method
- `StyreneLifecycle._core` (CoreLifecycle) attribute
- `TUIConfig.use_ipc` field
- All `if active_mode == LEGACY` branches
- Config serialization for `use_ipc`

## File Changes

### New Files
| Path | Description |
|------|-------------|
| `src/styrened/tui/services/protocol.py` | TUIServices Protocol definition |
| `src/styrened/tui/utils.py` | Pure functions moved from daemon (deduplicate, etc.) |
| `docs/KEYMAP.md` | Keybinding contract documentation |

### Modified Files (IPC expansion)
| Path | Description |
|------|-------------|
| `src/styrened/ipc/protocol.py` | New message types: GET_NODES, GET_CORE_CONFIG, SAVE_CORE_CONFIG, GET_HUB_STATUS, GET_UNREAD_COUNTS |
| `src/styrened/ipc/messages.py` | Request/response message classes for new commands |
| `src/styrened/ipc/handlers.py` | Handler implementations for new commands |
| `src/styrened/ipc/server.py` | Register new command handlers |
| `src/styrened/ipc/client.py` | Client methods for new commands |
| `src/styrened/tui/services/ipc_bridge.py` | Bridge methods wrapping new IPC commands |

### Modified Files (TUIServices + migration)
| Path | Description |
|------|-------------|
| `src/styrened/tui/app.py` | Implement TUIServices, expose `services` property, remove db_engine from screen API |
| `src/styrened/tui/screens/dashboard.py` | Replace 6 direct imports with bridge calls |
| `src/styrened/tui/screens/exploration.py` | Replace 4 direct imports with bridge calls |
| `src/styrened/tui/screens/mesh_device_detail.py` | Replace 3 direct imports with bridge calls |
| `src/styrened/tui/screens/settings.py` | Replace 5 direct imports with bridge calls |
| `src/styrened/tui/screens/contacts.py` | Use services protocol |
| `src/styrened/tui/screens/inbox.py` | Use services protocol |
| `src/styrened/tui/screens/conversation.py` | Use services protocol |
| `src/styrened/tui/screens/daemon_setup.py` | Replace IPC import |
| `src/styrened/tui/widgets/node_info_panel.py` | Replace 4 direct imports, remove db_engine |
| `src/styrened/tui/widgets/chat_widget.py` | Replace IPC import, use services |
| `src/styrened/tui/widgets/command_widget.py` | Use services protocol |
| `src/styrened/tui/widgets/terminal_widget.py` | Replace IPC import, use services |
| `src/styrened/tui/widgets/message_bubble.py` | Use services protocol |
| `src/styrened/tui/widgets/page_browser.py` | Use services protocol |
| `src/styrened/tui/widgets/device_status_widget.py` | Replace StatusResponse import |

### Modified Files (legacy removal)
| Path | Description |
|------|-------------|
| `src/styrened/tui/services/app_lifecycle.py` | Remove LEGACY/AUTO, CoreLifecycle, _initialize_legacy |
| `src/styrened/tui/models/config.py` | Remove use_ipc field |
| `src/styrened/tui/services/config.py` | Remove use_ipc serialization |

## Constraints

- `StatusResponse` and data model imports under `TYPE_CHECKING` are acceptable (they're data types, not services)
- The `_deduplicate_by_identity` function is pure (no I/O) — move to tui/utils.py rather than IPC
- `IPCMessageType` enum import in widgets for event filtering is acceptable (it's a shared enum)
- Settings screen `generate_rns_config` becomes a server-side operation triggered via save_core_config
