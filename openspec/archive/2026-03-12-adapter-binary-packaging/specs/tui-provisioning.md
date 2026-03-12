# tui-provisioning — Delta Spec

## ADDED Requirements

### Requirement: Settings Network tab shows adapter enable toggles

The TRANSPORT panel in Settings → Network tab includes toggles for Yggdrasil and I2P adapters with status indicators.

#### Scenario: Adapter toggle reflects current mode

Given the TUI Settings screen is open on the Network tab
When yggdrasil mode is DISABLED in config
Then the Yggdrasil toggle shows as off
And the status shows "Not installed" if binary is absent, or "Disabled" if binary is present

#### Scenario: Enabling adapter without binary triggers provision modal

Given the TUI Settings screen is open on the Network tab
And no yggdrasil binary is found on the system
When the operator toggles Yggdrasil to enabled
Then a provisioning modal is displayed with platform info and download progress
And the modal shows install target as `~/.styrene/bin/yggdrasil`

### Requirement: Provisioning modal shows download progress

A modal overlay handles binary acquisition with progress feedback and error reporting.

#### Scenario: Successful download shows progress

Given the provisioning modal is displayed for yggdrasil
When the download proceeds
Then a progress bar updates with percentage and bytes
And on completion the modal shows `✓ yggdrasil installed`
And the adapter mode is set to MANAGED in config
And the modal auto-dismisses after 2 seconds

#### Scenario: Download failure shows error with fallback instructions

Given the provisioning modal is displayed for yggdrasil
And the download fails (network error, 404, integrity mismatch)
When the error is caught
Then the modal shows the error message
And the modal shows OS package manager install instructions as fallback
And a "Close" button is available

### Requirement: RPC CMD_PROVISION for remote binary provisioning

A new RPC command `CMD_PROVISION` allows remote binary provisioning on fleet devices, gated by ADMIN RBAC tier.

#### Scenario: ADMIN can remotely provision adapter

Given a remote node is reachable via RPC
And the local identity has ADMIN role on the remote node
When `CMD_PROVISION {"adapter": "yggdrasil"}` is sent
Then the remote node runs BinaryProvisioner for yggdrasil
And the response includes success status and installed path

#### Scenario: Non-ADMIN is rejected

Given a remote node is reachable via RPC
And the local identity has OPERATOR role (not ADMIN)
When `CMD_PROVISION {"adapter": "yggdrasil"}` is sent
Then the response is an RBAC permission denied error

#### Scenario: LOCAL (IPC) bypasses RBAC

Given the operator is using the TUI (IPC context)
When provisioning is triggered via Settings toggle
Then RBAC is not checked (LOCAL context)
And provisioning proceeds directly
