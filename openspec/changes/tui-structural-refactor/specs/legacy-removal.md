# Legacy Mode Removal

Remove LifecycleMode.LEGACY — the TUI is an IPC-only daemon client.

## Requirements

### REQ-LEG-1: LifecycleMode.LEGACY removed

The `LifecycleMode` enum has only `IPC` (no `LEGACY`, no `AUTO`). The TUI always communicates via IPC to the daemon.

#### Scenario: LifecycleMode only has IPC
- Given `src/styrened/tui/services/app_lifecycle.py`
- When inspecting the `LifecycleMode` enum
- Then it contains only `IPC = "ipc"`

### REQ-LEG-2: use_ipc config field removed

The `TUIConfig.use_ipc` field is removed. The TUI always uses IPC. Existing config files with `use_ipc: false` are ignored (no error, just ignored).

#### Scenario: Config with use_ipc field is parsed without error
- Given a YAML config with `tui: { use_ipc: false }`
- When loading the config
- Then the config loads successfully and the TUI operates in IPC mode

#### Scenario: TUIConfig has no use_ipc field
- Given `src/styrened/tui/models/config.py`
- When inspecting `TUIConfig` dataclass fields
- Then no `use_ipc` field exists

### REQ-LEG-3: CoreLifecycle not used in TUI

The TUI lifecycle does not instantiate or call `CoreLifecycle`. All RNS/LXMF initialization is the daemon's responsibility.

#### Scenario: No CoreLifecycle import in TUI
- Given the `src/styrened/tui/` directory
- When searching for `CoreLifecycle` imports
- Then zero runtime matches are found

### REQ-LEG-4: _initialize_legacy method removed

The `StyreneLifecycle._initialize_legacy()` method and all legacy fallback branches in `_initialize_async()` are removed.

#### Scenario: No legacy initialization code
- Given `src/styrened/tui/services/app_lifecycle.py`
- When searching for `_initialize_legacy` or `LEGACY` or `legacy`
- Then zero matches are found
