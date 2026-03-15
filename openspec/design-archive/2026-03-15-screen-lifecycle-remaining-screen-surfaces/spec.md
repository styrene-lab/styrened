# Remaining screen-surface lifecycle migration — Design Spec

> This spec defines acceptance criteria for the design phase.

## Scenarios

### Scenario 1: The remaining screen-side tail is narrowed to the aggregate workspaces that still duplicate lifecycle logic

Given the shared lifecycle contract already absorbed Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel cleanup work
When the current screen inventory is reviewed
Then the active migration tail must be identified primarily in Inbox, Exchange, Contacts, Comms, embedded Exchange tab panes, and Provision rather than the mostly local wizard/settings screens

### Scenario 2: Exchange and its live tab panes migrate as one ownership cluster before helper extraction

Given Exchange currently spreads refresh ownership across `ExchangeScreen`, `ExchangeDirectTab`, and `ExchangeContactsTab`
When the follow-up migration is planned
Then the parent screen and its live tab panes should be normalized together first, with any reusable screen-content helper deferred until another real use case proves the abstraction

### Scenario 3: The migration order favors the highest-duplication workspaces first

Given not every remaining screen has the same lifecycle risk
When implementation is staged
Then aggregate mail/comms surfaces should be prioritized ahead of mostly local-form, wizard, or action-driven screens unless a new bug changes that ordering

## Falsifiability

- If the remaining screen-side work still treats static wizards and local forms as equally urgent with aggregate mail/comms workspaces, this design is wrong.
- If Exchange's embedded tab panes are ignored even though they still own screen-like refresh behavior, this design is wrong.
- If the plan reopens already-cleaned Dashboard, Exploration, MeshDeviceDetail, or NodeInfoPanel work without new evidence, this design is wrong.

## Constraints

- Do not reintroduce screen-owned shadow caches just to make migration easier.
- Keep the shared app bridge as the control lane; screen migration should compose with auxiliary-lane ownership rather than bypass it.
- Prefer converging duplicated mount/resume refresh logic before touching mostly static wizard or settings flows.
- Preserve splash-first startup and the newer cache-readiness/backpressure distinctions while migrating aggregate workspaces.
