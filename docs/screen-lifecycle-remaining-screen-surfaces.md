---
id: screen-lifecycle-remaining-screen-surfaces
title: Remaining screen-surface lifecycle migration
status: exploring
parent: screen-lifecycle-styrenescreen-migration-tail
open_questions:
  - "Should Exchange's embedded Direct and Contacts tab widgets migrate together with ExchangeScreen or behind a reusable screen-content lifecycle helper?"
issue_type: epic
priority: 1
---

# Remaining screen-surface lifecycle migration

## Overview

> Parent: [Remaining StyreneScreen migration tail](screen-lifecycle-styrenescreen-migration-tail.md)
> Spawned from: "Which remaining screens and widgets still materially deviate from the StyreneScreen lifecycle contract after the recent Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel cleanups?"

*To be explored.*

## Research

### The material screen-side tail is concentrated in aggregate workspaces and screen-like tab panes, not the static wizards

`InboxScreen`, `ExchangeScreen`, `ContactsScreen`, and `CommsScreen` still subclass `Screen` directly and each manually reimplement the same lifecycle shape the shared contract was meant to absorb: mount-time table bootstrapping, explicit `app.services.bridge` lookups, ad hoc `run_worker(...)` load kicks, and separate `on_screen_resume()` refresh paths. `ExchangeDirectTab` and `ExchangeContactsTab` duplicate the same refresh logic inside embedded widgets, so the Exchange workspace currently has lifecycle work split between the parent screen and child tab panes. `ProvisionScreen` is also still lifecycle-heavy because it performs async mount bootstrap and owns a long-running flash worker, but its provisioning-specific flow is narrower than the aggregate mail/comms surfaces. By contrast, `SettingsScreen`, `DaemonSetupScreen`, `FirstRunWizardScreen`, `DeviceConsoleScreen`, and `ConversationScreen` are presently lighter: they are mostly local-form, wizard, or action-driven screens whose screen-level lifecycle work is limited to UI setup, focus changes, or a single lightweight fetch delegated to widgets.

## Decisions

### Decision: Prioritize aggregate mail/comms surfaces before local-form or wizard screens

**Status:** decided
**Rationale:** The main remaining contract violations are the screens that still duplicate mount/resume refresh behavior and bridge access across whole workspaces: Inbox, Exchange, Contacts, Comms, and the Exchange tab widgets that behave like embedded screens. These surfaces are where the shared lifecycle contract will eliminate the most duplicate refresh code and ownership ambiguity. Provision is a secondary lifecycle-heavy screen because of flash-worker ownership. Settings, DaemonSetup, FirstRunWizard, DeviceConsole, and Conversation can remain lower-priority cleanup until a concrete bug or refactor need appears.

## Open Questions

- Should Exchange's embedded Direct and Contacts tab widgets migrate together with ExchangeScreen or behind a reusable screen-content lifecycle helper?

## Acceptance Criteria

### Scenarios

#### Scenario 1: The remaining screen-side tail is narrowed to the aggregate workspaces that still duplicate lifecycle logic

Given the shared lifecycle contract already absorbed Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel cleanup work  
When the current screen inventory is reviewed  
Then the active migration tail must be identified primarily in Inbox, Exchange, Contacts, Comms, embedded Exchange tab panes, and Provision rather than the mostly local wizard/settings screens

#### Scenario 2: Exchange lifecycle ownership is left explicit instead of hidden across parent and tab panes

Given Exchange currently spreads refresh ownership across `ExchangeScreen`, `ExchangeDirectTab`, and `ExchangeContactsTab`  
When the follow-up migration is planned  
Then the design must keep the parent-vs-tab ownership boundary as an explicit question instead of silently treating those embedded panes as already normalized

#### Scenario 3: The migration order favors the highest-duplication workspaces first

Given not every remaining screen has the same lifecycle risk  
When implementation is staged  
Then aggregate mail/comms surfaces should be prioritized ahead of mostly local-form, wizard, or action-driven screens unless a new bug changes that ordering

### Falsifiability

- This design is wrong if the remaining screen-side work still treats static wizards and local forms as equally urgent with aggregate mail/comms workspaces.
- This design is wrong if Exchange's embedded tab panes are ignored even though they still own screen-like refresh behavior.
- This design is wrong if the plan reopens already-cleaned Dashboard, Exploration, MeshDeviceDetail, or NodeInfoPanel work without new evidence.

### Constraints

- Do not reintroduce screen-owned shadow caches just to make migration easier.
- Keep the shared app bridge as the control lane; screen migration should compose with auxiliary-lane ownership rather than bypass it.
- Prefer converging duplicated mount/resume refresh logic before touching mostly static wizard or settings flows.
- Preserve splash-first startup and the newer cache-readiness/backpressure distinctions while migrating aggregate workspaces.

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/inbox.py` (modified) — Inbox still owns ad hoc mount/resume conversation refresh and confirmation-timer state.
- `src/styrened/tui/screens/exchange.py` (modified) — Exchange duplicates mail refresh, pages refresh, and parent-screen lifecycle ownership across tab content.
- `src/styrened/tui/screens/contacts.py` (modified) — Contacts still performs direct mount-time bridge loading outside the shared screen base.
- `src/styrened/tui/screens/comms.py` (modified) — Comms reimplements mount/resume capability refresh and direct bridge fan-out.
- `src/styrened/tui/screens/exchange_tabs.py` (modified) — Embedded Direct/Contacts tab widgets currently behave like mini-screens with their own refresh lifecycle.
- `src/styrened/tui/screens/provision.py` (modified) — Provision owns async mount bootstrap plus flash-worker lifecycle that should align with shared cleanup semantics.

### Constraints

- Do not reintroduce screen-owned shadow caches just to make migration easier.
- Keep the shared app bridge as the control lane; screen migration should compose with auxiliary-lane ownership rather than bypass it.
- Prefer converging duplicated mount/resume refresh logic before touching mostly static wizard or settings flows.
- Preserve splash-first startup and the newer cache-readiness/backpressure distinctions while migrating aggregate workspaces.
