# IPC Bridge Expansion

New IPC commands needed to replace direct daemon service imports in the TUI.

## Requirements

### REQ-IPC-1: get_nodes IPC command

The IPC bridge exposes `get_nodes()` returning the list of known mesh devices from the node store. Replaces direct `get_node_store().get_all_nodes()` and `get_node_store().get_styrene_nodes()` calls in screens.

#### Scenario: TUI fetches known nodes via IPC
- Given the daemon has discovered 3 styrene nodes
- When the TUI calls `bridge.get_nodes(styrene_only=True)`
- Then it receives a list of 3 device dicts with identity_hash, name, status, device_type fields

#### Scenario: TUI fetches all nodes including non-styrene
- Given the daemon has discovered 5 nodes (3 styrene, 2 other)
- When the TUI calls `bridge.get_nodes(styrene_only=False)`
- Then it receives a list of 5 device dicts

### REQ-IPC-2: get_core_config / save_core_config IPC commands

The IPC bridge exposes `get_core_config()` and `save_core_config(config_dict)` for reading and writing the daemon's core configuration. Replaces direct `load_core_config()` / `save_core_config()` imports.

#### Scenario: TUI reads core config via IPC
- Given the daemon is running with RBAC configured
- When the TUI calls `bridge.get_core_config()`
- Then it receives a config dict including rbac section

#### Scenario: TUI saves core config via IPC
- Given the TUI has modified config settings
- When the TUI calls `bridge.save_core_config(modified_dict)`
- Then the daemon writes the config to disk and returns success

### REQ-IPC-3: get_hub_status IPC command

The IPC bridge exposes `get_hub_status()` returning hub connection state. Replaces direct `get_hub_connection()` imports.

#### Scenario: TUI queries hub status via IPC
- Given the daemon is connected to a hub
- When the TUI calls `bridge.get_hub_status()`
- Then it receives a dict with is_connected, hub_address, hub_destination fields

### REQ-IPC-4: get_unread_counts IPC command

The IPC bridge exposes `get_unread_counts()` returning per-peer unread message counts. Replaces direct SQLAlchemy session queries in dashboard.

#### Scenario: TUI queries unread counts via IPC
- Given the daemon has 3 unread messages from peer A and 1 from peer B
- When the TUI calls `bridge.get_unread_counts()`
- Then it receives `{"<peer_a_hash>": 3, "<peer_b_hash>": 1}`

### REQ-IPC-5: page browser external URL fetches remain daemon-mediated

The IPC bridge exposes page-browser operations for explicit external URLs so the TUI can browse HTTPS and `.i2p` endpoints through the daemon's transport policy.

#### Scenario: TUI opens HTTPS docs via IPC
- Given the operator selects an `https://` documentation endpoint in the TUI
- When the TUI calls the page-browser bridge method for that URL
- Then the daemon fetches it directly over HTTP(S)
- And the TUI does not import or instantiate an HTTP client itself

#### Scenario: TUI opens an I2P docs endpoint via IPC
- Given the operator selects a `.i2p` documentation endpoint in the TUI
- When the TUI calls the page-browser bridge method for that URL
- Then the daemon applies the explicit I2P enablement policy and proxy routing
- And the TUI receives either the rendered content or the operator-facing disabled-mode error
