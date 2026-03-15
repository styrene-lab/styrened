# Aggregate refresh surfaces lifecycle migration — Design

## Architecture Decisions

### Decision: Migrate Inbox, Contacts, and Comms onto StyreneScreen rather than inventing another standalone-screen helper

**Status:** decided
**Rationale:** The shared screen contract already covers the repeated problems in these three surfaces: mount/resume refresh kickoff, retry behavior, bridge access, and screen-local resource ownership. Introducing another bespoke helper for standalone refresh surfaces would duplicate what `StyreneScreen` already standardizes.

### Decision: Keep local widget/table bootstrap explicit, but move daemon refresh work into `_load_data()` and resource-backed action helpers

**Status:** decided
**Rationale:** These screens still need local on-mount setup such as `DataTable` columns, cursor configuration, and empty-state placeholders. That UI bootstrap should stay explicit, while bridge-driven refresh work moves into the shared load/resume cycle and user-triggered async actions use callable worker scheduling plus `WidgetResourceScope` helpers for timers and cleanup.

### Decision: Treat ProvisionScreen as a separate workflow-ownership follow-up, not part of this migration slice

**Status:** decided
**Rationale:** Provision owns long-running flash/detect workflow state rather than an aggregate refresh workspace contract. Keeping it separate preserves a narrow implementation slice and avoids forcing provisioning-specific cleanup into a design meant for mail/comms refresh surfaces.

## Research Context

### Inbox, Contacts, and Comms still duplicate the pre-StyreneScreen refresh contract

`InboxScreen`, `ContactsScreen`, and `CommsScreen` all still subclass `Screen` directly and manually split one lifecycle shape across `on_mount()`, `on_screen_resume()`, direct `_ipc_bridge` property checks, and repeated `run_worker(...)` refresh kickoff. Inbox loads conversations and auto-reply state on mount, re-loads conversations on resume, and still launches several command workers from eagerly created coroutine objects. Contacts bootstraps table columns in `on_mount()` and then performs a multi-source aggregate refresh (`get_contacts`, device state, conversation previews) outside the shared load/retry contract. Comms repeats the same mount/resume capability refresh pattern and still fans out `get_core_config()` and `get_status()` from a direct bridge accessor.

### The shared screen base already provides most of the missing contract

`StyreneScreen` now centralizes screen load kickoff, resume refresh, retry handling, bridge access, and screen-local `WidgetResourceScope` ownership. The remaining aggregate surfaces do not need another new abstraction; they mainly need migration onto that base while preserving local UI bootstrap such as table-column setup and placeholder rendering. The reusable helpers already landed in `WidgetResourceScope` also cover the timer and callable-worker patterns these screens still manage manually.

### Provisioning should stay a separate follow-up because its lifecycle debt is workflow-owned, not aggregate-refresh-owned

`ProvisionScreen` differs materially from the mail/comms aggregate surfaces. Its main lifecycle risks are async mount bootstrap, disk-detect refresh ownership, and long-running flash worker cleanup rather than repeated resume-driven aggregate refresh. That makes it a poor proving ground for the aggregate refresh migration pattern and a better fit for its own child node.

## File Changes

- `src/styrened/tui/screens/inbox.py` (modified) — Migrate `InboxScreen` to `StyreneScreen`, moving bridge-driven refresh into `_load_data()` and replacing direct coroutine-style worker launches/timer ownership with resource-backed helpers.
- `src/styrened/tui/screens/contacts.py` (modified) — Migrate `ContactsScreen` to `StyreneScreen` while preserving explicit form/table bootstrap and moving aggregate refresh through the shared load contract.
- `src/styrened/tui/screens/comms.py` (modified) — Migrate `CommsScreen` capability refresh onto `StyreneScreen` and keep capability-gated UI state updates as explicit render logic.
- `tests/tui/screens/test_inbox.py` (modified) — Add or adjust regression coverage for `StyreneScreen`-backed mount/resume loading, local empty states, and callable worker scheduling in Inbox.
- `tests/tui/screens/test_contacts.py` (modified) — Add or adjust regression coverage for shared load-cycle migration, local daemon-required placeholders, and action-worker behavior in Contacts.
- `tests/tui/screens/test_comms.py` (modified) — Add or adjust regression coverage for capability loading via the shared screen lifecycle instead of ad hoc mount/resume kicks.

## Constraints

- Do not reintroduce screen-owned shadow caches or background prewarming just to make these screens appear instant.
- Keep the shared app bridge as the control lane; these screens should not spawn ambient auxiliary lanes unless a concrete long-running workload demands it.
- Bridge-unavailable behavior must stay local and truthful (workspace placeholder or warning) rather than reading as a daemon-wide disconnect if only one screen cannot load.
- Use callable or `functools.partial(...)` worker scheduling for async actions so mock-heavy tests do not leak unawaited-coroutine warnings.
- Keep the implementation slice narrow to Inbox, Contacts, and Comms; `ProvisionScreen` lifecycle ownership stays in its own follow-up node.
