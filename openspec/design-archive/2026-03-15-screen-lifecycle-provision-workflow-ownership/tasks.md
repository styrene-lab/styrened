# Provision workflow lifecycle ownership — Design Tasks

## 1. Design exploration

- [x] 1.1 Confirm Provision is a workflow-owned lifecycle follow-up rather than another aggregate refresh migration.
- [x] 1.2 Audit `ProvisionScreen` for bootstrap, disk-detect, flash-worker, and post-flash watch ownership boundaries.
- [x] 1.3 Decide whether Provision should adopt `StyreneScreen` directly or keep workflow-specific lifecycle ownership.
- [x] 1.4 Define ownership boundaries between `ProvisionScreen` and `ForgeLog`, including who cleans up timers versus higher-level workers/watch state.
- [x] 1.5 Define file scope, constraints, and falsifiable acceptance criteria for the implementation slice.
