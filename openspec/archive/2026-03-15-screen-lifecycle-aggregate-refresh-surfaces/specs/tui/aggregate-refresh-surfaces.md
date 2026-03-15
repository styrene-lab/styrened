# tui/aggregate-refresh-surfaces — Delta Spec

## ADDED Requirements

### Requirement: Aggregate refresh workspaces use the shared screen lifecycle

Inbox, Contacts, and Comms must route bridge-driven refresh through the shared `StyreneScreen` load/resume contract instead of duplicating ad hoc mount and resume refresh kickoff.

#### Scenario: Mount and resume refresh use the shared screen contract
Given `InboxScreen`, `ContactsScreen`, or `CommsScreen` is mounted or resumed with a connected bridge
When the screen refreshes its daemon-backed state
Then the refresh work runs through the shared `StyreneScreen` load/resume lifecycle
And the screen does not keep its own duplicated bridge-refresh kickoff in both `on_mount()` and `on_screen_resume()`.

### Requirement: Aggregate refresh workspaces keep local bootstrap and degraded states explicit

Migrating these surfaces onto the shared screen base must not hide their local widget setup or replace truthful workspace-local empty-state handling with preload assumptions.

#### Scenario: No-daemon placeholders remain workspace-local
Given one of the aggregate refresh workspaces is shown without a connected bridge
When the screen mounts
Then its local table or placeholder UI still renders a truthful workspace-local daemon-required or empty-state message
And the screen does not depend on a screen-owned shadow cache or daemon-wide disconnect semantics to render.

### Requirement: User-triggered async actions follow the shared worker-scheduling convention

Aggregate refresh workspaces must use callable worker scheduling and local resource ownership for timers or cleanup-sensitive state so runtime behavior and mock-heavy tests stay aligned.

#### Scenario: Async action launch avoids eager coroutine creation
Given Inbox or Contacts launches an async follow-up action such as delete, search, sync, resolve, or auto-reply work
When the action is scheduled
Then the screen passes an async callable or `functools.partial(...)` into worker scheduling instead of an eagerly created coroutine object
And any timer or cleanup-sensitive state used by that action remains screen-local.
