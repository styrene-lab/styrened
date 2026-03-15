# Aggregate refresh surfaces lifecycle migration — Design Spec

> This spec defines acceptance criteria for the design phase.
> Add Given/When/Then scenarios that must be true before marking this node 'decided'.

## Scenarios

### Scenario 1: Shared screen lifecycle owns aggregate refresh kickoff

Given `InboxScreen`, `ContactsScreen`, or `CommsScreen` is mounted or resumed with a bridge available
When the migration is implemented
Then bridge-driven refresh work runs through `StyreneScreen`'s shared load or resume path instead of duplicated ad hoc `on_mount()` and `on_screen_resume()` refresh kickoff in each screen.

### Scenario 2: Local UI bootstrap remains explicit and truthful

Given one of the aggregate refresh surfaces needs local widget setup or no-daemon placeholders
When it migrates onto `StyreneScreen`
Then table columns, cursor configuration, and workspace-local empty or degraded states remain explicit in the screen code and do not depend on hidden preload caches or daemon-wide disconnect semantics.

### Scenario 3: User-triggered async work adopts shared resource and worker conventions

Given Inbox or Contacts launches async follow-up work such as delete, search, sync, resolve, or auto-reply actions
When that work is scheduled after the migration
Then the screen uses callable worker scheduling and screen-local resource ownership for timers or cleanup-sensitive state instead of eagerly creating coroutine objects or relying on ad hoc teardown.

## Falsifiability

- This design is wrong if migrating these screens still requires inventing another standalone-screen helper because `StyreneScreen` cannot represent their actual refresh lifecycle.
- This design is wrong if the migration hides local placeholder or degraded-state behavior behind preload assumptions, auxiliary lanes, or screen-owned caches.
- This design is wrong if Provision-specific flash and disk-detect workflow ownership has to be mixed into the same implementation slice for the aggregate refresh workspaces to make progress.

## Constraints

- Inbox, Contacts, and Comms remain the only screens in scope for this slice.
- The shared app bridge remains the control lane.
- No new screen-owned shadow caches are introduced.
- Async action scheduling must preserve the existing callable-worker testing convention.
