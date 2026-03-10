# housekeeping — Cleanup, Test Patterns, and OpenSpec Closure

## Requirement: No app._lifecycle.ipc_bridge references in tests or production code

#### Scenario: tests use services.bridge not _lifecycle.ipc_bridge
Given any TUI test file
When grepped for `app._lifecycle.ipc_bridge`
Then no matches are found

#### Scenario: production code uses self.app.services.bridge
Given any TUI screen or widget
When grepped for `_lifecycle.ipc_bridge`
Then no matches are found (only docstring/comment references are acceptable)

## Requirement: load_core_config and get_node_store not called directly from TUI screens

#### Scenario: TUI screens use IPC bridge for config and nodes
Given any file under src/styrened/tui/screens/ or src/styrened/tui/widgets/
When grepped for direct calls to load_core_config() or get_node_store()
Then no matches are found (services/reticulum.py announce handler is an acceptable exception)

## Requirement: generate_rns_config() moved server-side

#### Scenario: Settings screen uses save_core_config for RNS config
Given the operator saves Reticulum interface settings in SettingsScreen
When the settings are committed
Then bridge.save_core_config() is called with the updated config dict
And generate_rns_config() is not called directly from TUI code

## Requirement: i2p-integration TUI entrypoint exists

#### Scenario: operator can open I2P URL from TUI
Given I2P capability is active (daemon reports i2p capability)
When the operator selects an I2P URL in the page browser or Comms workspace
Then the URL opens through bridge.get_page() using the I2P transport
And the operator can also manually enter a .i2p address

## Requirement: yggdrasil-service Nix tasks documented

#### Scenario: yggdrasil-service tasks 7.1 and 7.2 are tracked
Given yggdrasil-service tasks 7.1 (yggdrasil.nix module) and 7.2 (adopt-mode docs)
When the styrene-edge repo is updated
Then the NixOS module enables yggdrasil with persistentKeys, AdminListen at /var/run/yggdrasil/yggdrasil.sock
And docs state that NixOS deployments use mode: adopt in styrened config

## Requirement: three OpenSpec changes archived on completion

#### Scenario: tui-structural-refactor archived
Given all 87 tasks in tui-structural-refactor are complete
When /opsx:archive tui-structural-refactor is run
Then the change archives successfully

#### Scenario: i2p-integration archived
Given all 27 tasks in i2p-integration are complete
When /opsx:archive i2p-integration is run
Then the change archives successfully

#### Scenario: yggdrasil-service archived
Given all 35 tasks in yggdrasil-service are complete
When /opsx:archive yggdrasil-service is run
Then the change archives successfully
