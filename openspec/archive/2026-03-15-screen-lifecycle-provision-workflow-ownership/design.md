# Provision workflow lifecycle ownership — Design

## Architecture Decisions

### Decision: Keep ProvisionScreen workflow-oriented for now instead of forcing it onto the generic StyreneScreen refresh contract

**Status:** decided
**Rationale:** Provisioning is not primarily a mount/resume refresh surface. Its workflow includes modal confirmation, long-running flash execution, and post-flash watch state that would not map cleanly onto automatic resume refresh without extra guards. The narrowest next step is explicit workflow ownership and teardown rather than generic screen-refresh migration.

### Decision: Use screen-local resource ownership and callable worker scheduling for bootstrap, disk detection, flash execution, and post-flash watch teardown

**Status:** decided
**Rationale:** The real repeated failure mode is worker lifecycle: eager coroutine launch, manual flash-worker tracking, and cleanup-sensitive workflow steps. Reusing the existing callable-worker and resource-ownership patterns keeps the change small and testable without inventing a new provisioning framework.

### Decision: Keep ForgeLog responsible for widget-local timer cleanup while ProvisionScreen owns only screen-level workflow workers and discovery boundaries

**Status:** decided
**Rationale:** `ForgeLog` already uses `WidgetResourceScope` for its mesh-watch timer and status widget lifecycle. The screen should not duplicate that ownership. Instead, `ProvisionScreen` should own only the higher-level flash worker, disk-detect/bootstrap workers, and any discovery/watch registration that outlives a single widget callback.

## Research Context

### ProvisionScreen owns a staged local workflow rather than a resume-driven aggregate refresh surface

`ProvisionScreen` does not primarily fetch daemon-backed summary state on mount and resume the way Inbox, Contacts, and Comms did. It owns a staged local workflow: bootstrap device catalog and forge config, kick off disk detection when a device is chosen or refresh is requested, run a long-lived flash worker, and then bridge into post-flash mesh watch. The lifecycle debt is therefore workflow ownership and teardown sequencing, not repeated workspace refresh fan-out.

### Blind StyreneScreen migration would replay bootstrap at the wrong times

`ProvisionScreen` currently uses async `on_mount()` plus modal-driven flow (`push_screen_wait(ConfirmFlash(...))`) and phase transitions between selection and forge views. A naive conversion to `StyreneScreen` would inherit automatic resume refresh, which could replay catalog or disk bootstrap after modal returns or during workflow transitions that are not actually stale-data refresh events. The narrowest safe follow-up is to make worker ownership and cleanup explicit before deciding whether the screen should ever participate in the generic resume-refresh contract.

### Current workflow debt clusters around eager worker launch and missing teardown boundaries

The screen still launches `_detect_disks()` and `_run_forge()` via eager coroutine `run_worker(...)` calls, tracks `_flash_worker` manually, and starts mesh discovery after flash completion without an explicit screen-owned teardown boundary. `ForgeLog` already owns its mesh-watch timer through `WidgetResourceScope`, so the remaining gap is screen-level ownership for bootstrap/detect/flash workers and any discovery subscription started for post-flash watch.

## File Changes

- `src/styrened/tui/screens/provision.py` (modified) — Introduce explicit screen-local workflow ownership for bootstrap, disk-detect, flash, and post-flash watch cleanup without forcing generic resume-refresh semantics.
- `tests/tui/screens/test_provision.py` (modified) — Add regression coverage for callable worker scheduling, modal-safe workflow ownership, and abort/unmount teardown of flash and detect work.

## Constraints

- Do not force `ProvisionScreen` onto automatic resume-refresh behavior if that would replay bootstrap during confirmation-modal or workflow phase transitions.
- Keep `ForgeLog` as the owner of widget-local mesh-watch timer state; the screen should not duplicate timer cleanup already handled by `WidgetResourceScope`.
- Use callable or `functools.partial(...)` worker scheduling for `_detect_disks()`, forge execution, and any async bootstrap work so tests do not leak unawaited coroutine warnings.
- Any post-flash discovery/watch teardown must stop with the workflow or screen lifecycle rather than persisting after abort, close, or unmount.
- Keep the change narrowly scoped to Provision workflow ownership; do not reopen the already-implemented aggregate refresh surfaces.
