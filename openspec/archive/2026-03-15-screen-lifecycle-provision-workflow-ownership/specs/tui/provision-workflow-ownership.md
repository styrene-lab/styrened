# tui/provision-workflow-ownership — Delta Spec

## ADDED Requirements

### Requirement: Provision bootstrap is workflow-owned and cancellable

ProvisionScreen must own catalog/config bootstrap through explicit workflow worker management rather than relying on raw eager async screen-mount behavior.

#### Scenario: Bootstrap is cancellable and screen-owned
Given `ProvisionScreen` is opened
When catalog or forge-config bootstrap work begins
Then the screen owns that bootstrap through explicit workflow worker management
And the bootstrap can be cancelled or ignored safely if the screen goes away mid-load.

### Requirement: Detect and flash work use callable worker scheduling with teardown

Provision workflow actions that may outlive a single callback must use callable worker scheduling and explicit cleanup boundaries.

#### Scenario: Detect and flash scheduling avoids eager coroutines
Given the operator refreshes disks or starts a flash run
When `ProvisionScreen` schedules `_detect_disks()` or forge execution
Then it passes callable worker inputs instead of eagerly created coroutine objects
And the screen has an explicit teardown boundary for in-flight detect or flash workers during abort or unmount.

### Requirement: Post-flash watch ends with the workflow while ForgeLog keeps timer ownership

ProvisionScreen must not duplicate ForgeLog timer cleanup, but it must end any screen-owned watch or discovery boundary when the provisioning workflow ends.

#### Scenario: Workflow exit stops screen-owned watch state
Given flash completes and mesh watch starts
When the operator aborts, closes, or leaves the provisioning workflow
Then any screen-owned discovery or watch boundary ends with that workflow
And `ForgeLog` remains the owner of widget-local mesh-watch timer cleanup.
