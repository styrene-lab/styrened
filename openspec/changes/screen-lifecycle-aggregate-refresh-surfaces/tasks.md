# Aggregate refresh surfaces lifecycle migration — Tasks

## 1. Inbox lifecycle migration
<!-- specs: tui/aggregate-refresh-surfaces -->

- [ ] 1.1 Convert `InboxScreen` to `StyreneScreen` while keeping table bootstrap and no-daemon placeholder rendering explicit in screen code.
- [ ] 1.2 Move bridge-driven conversation and auto-reply refresh into the shared load or resume lifecycle instead of duplicated ad hoc refresh kickoff.
- [ ] 1.3 Replace eager coroutine-style worker launches and delete-confirmation timer ownership with callable worker scheduling and screen-local resource helpers where appropriate.
- [ ] 1.4 Update `tests/tui/screens/test_inbox.py` to cover the shared lifecycle path, local placeholder behavior, and callable worker scheduling expectations.

## 2. Contacts lifecycle migration
<!-- specs: tui/aggregate-refresh-surfaces -->

- [ ] 2.1 Convert `ContactsScreen` to `StyreneScreen` while preserving explicit table and form bootstrap plus workspace-local daemon-required rendering.
- [ ] 2.2 Route aggregate contact refresh through `_load_data()` and the shared resume lifecycle instead of direct `Screen`-level bridge refresh handling.
- [ ] 2.3 Use callable worker scheduling for async contact actions so tests do not rely on eagerly created coroutine objects.
- [ ] 2.4 Update `tests/tui/screens/test_contacts.py` to cover the shared lifecycle path, workspace-local placeholders, and action-worker behavior.

## 3. Comms lifecycle migration
<!-- specs: tui/aggregate-refresh-surfaces -->

- [ ] 3.1 Convert `CommsScreen` to `StyreneScreen` while keeping capability-gated UI state application explicit in the screen.
- [ ] 3.2 Move capability refresh into `_load_data()` and the shared screen resume path instead of ad hoc `on_mount()` and `on_screen_resume()` worker kickoff.
- [ ] 3.3 Preserve control-lane ownership and local placeholder semantics without introducing auxiliary lanes, shadow caches, or background prewarming.
- [ ] 3.4 Update `tests/tui/screens/test_comms.py` to cover the shared lifecycle path and capability-gated rendering behavior.

## 4. Scope guardrails

- [ ] 4.1 Keep the implementation slice narrow to `InboxScreen`, `ContactsScreen`, and `CommsScreen`; do not fold `ProvisionScreen` into this change.
- [ ] 4.2 Keep the shared app bridge as the control lane and avoid new ambient auxiliary lanes unless a concrete long-running workload demands one.
- [ ] 4.3 Preserve truthful workspace-local degraded or no-daemon rendering rather than reading single-screen load failures as daemon-wide disconnect state.
