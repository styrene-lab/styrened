# TUI Services Protocol

Typed interface replacing the implicit `self.app._lifecycle.ipc_bridge` contract.

## Requirements

### REQ-SVC-1: TUIServices Protocol

A `TUIServices` runtime protocol class at `src/styrened/tui/services/protocol.py` defines the typed API that all screens and widgets use to interact with the daemon. No screen or widget imports daemon internals directly.

#### Scenario: Screen accesses IPC bridge via typed protocol
- Given a screen that needs to call daemon IPC
- When the screen accesses `self.services.bridge`
- Then it receives a typed `IPCBridge` reference with no `type: ignore` annotation

#### Scenario: Screen accesses unread counts
- Given a screen needs unread message counts
- When the screen calls `self.services.get_unread_counts()`
- Then it receives `dict[str, int]` without touching `app.db_engine`

#### Scenario: Screen accesses local identity
- Given a screen needs the local operator identity hash
- When the screen accesses `self.services.local_identity_hash`
- Then it receives a `str` without reaching into `app.local_identity_hash`

### REQ-SVC-2: No type:ignore[attr-defined] for app access

All `# type: ignore[attr-defined]` annotations on `self.app._lifecycle` access are removed. Screens use `self.services` (a `TUIServices` instance) obtained from a mixin or base class.

#### Scenario: Grep finds zero type:ignore for attr-defined in TUI
- Given the full `src/styrened/tui/` directory
- When searching for `type: ignore[attr-defined]`
- Then zero matches are found in screens/ and widgets/

### REQ-SVC-3: No direct daemon service imports in screens/widgets

Screens and widgets do not import from `styrened.services.*`, `styrened.rpc.*`, `styrened.ipc.*`, or `styrened.daemon`. Only TUI-layer modules (`styrened.tui.*`) and shared data models (`styrened.models.*`) are allowed.

#### Scenario: Grep for daemon imports in TUI screens
- Given the `src/styrened/tui/screens/` directory
- When searching for `from styrened.services` or `from styrened.rpc` or `from styrened.ipc` or `from styrened.daemon`
- Then zero runtime matches are found (TYPE_CHECKING imports for type annotations are acceptable)

#### Scenario: Grep for daemon imports in TUI widgets
- Given the `src/styrened/tui/widgets/` directory
- When searching for `from styrened.services` or `from styrened.rpc` or `from styrened.ipc`
- Then zero runtime matches are found

### REQ-SVC-4: db_engine removed from UI layer

No screen or widget accesses `app.db_engine` or creates SQLAlchemy sessions. The app may use db_engine internally but does not expose it to screens.

#### Scenario: No db_engine access in screens or widgets
- Given `src/styrened/tui/screens/` and `src/styrened/tui/widgets/`
- When searching for `db_engine`
- Then zero matches are found
