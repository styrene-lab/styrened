# Provision workflow lifecycle ownership — Tasks

## 1. src/styrened/tui/screens/provision.py (modified)

- [x] 1.1 Replace raw async `on_mount()` bootstrap with explicit workflow-owned bootstrap worker scheduling.
- [x] 1.2 Route disk detection through callable worker scheduling and screen-owned teardown tracking.
- [x] 1.3 Route forge execution through callable worker scheduling and screen-owned teardown tracking.
- [x] 1.4 End post-flash mesh-watch state with workflow abort/unmount while keeping widget-local timer ownership in `ForgeLog`.

## 2. src/styrened/services/reticulum.py (modified)

- [x] 2.1 Add a narrow discovery-state probe so Provision can tell whether it owns the watch discovery boundary before stopping it.

## 3. src/styrened/tui/services/reticulum.py (modified)

- [x] 3.1 Re-export the discovery-state probe through the TUI service wrapper used by `ProvisionScreen`.

## 4. tests/tui/screens/test_provision.py (modified)

- [x] 4.1 Add regression coverage for callable bootstrap worker scheduling.
- [x] 4.2 Add regression coverage for callable disk-detect and forge worker scheduling.
- [x] 4.3 Add regression coverage for abort/unmount teardown of flash work and screen-owned mesh-watch state.

## 5. Verification

- [x] 5.1 `ruff check src/styrened/services/reticulum.py src/styrened/tui/services/reticulum.py src/styrened/tui/screens/provision.py tests/tui/screens/test_provision.py`
- [x] 5.2 `.venv/bin/python -m pytest tests/tui/screens/test_provision.py tests/tui/widgets/test_forge_log.py -q`

## 6. Cross-cutting constraints

- [x] 6.1 Do not force `ProvisionScreen` onto automatic resume-refresh behavior if that would replay bootstrap during confirmation-modal or workflow phase transitions.
- [x] 6.2 Keep `ForgeLog` as the owner of widget-local mesh-watch timer state; the screen does not duplicate timer cleanup already handled by `WidgetResourceScope`.
- [x] 6.3 Use callable or `functools.partial(...)` worker scheduling for `_detect_disks()`, forge execution, and async bootstrap work so tests do not leak unawaited coroutine warnings.
- [x] 6.4 Stop screen-owned discovery/watch state with workflow abort or screen unmount so it does not outlive the provisioning workflow.
- [x] 6.5 Keep the change narrowly scoped to Provision workflow ownership without reopening the already-implemented aggregate refresh surfaces.
