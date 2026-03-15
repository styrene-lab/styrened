---
id: screen-lifecycle-remaining-screen-surfaces
title: Remaining screen-surface lifecycle migration
status: decided
parent: screen-lifecycle-styrenescreen-migration-tail
open_questions: []
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

### Exchange should migrate with its embedded Direct and Contacts panes before introducing a generic screen-content lifecycle helper

There are two plausible directions for Exchange. A reusable helper would centralize mount/resume refresh kickoff, cancellation, and bridge access for embedded tab panes, but it would also freeze a new abstraction before the repo has multiple proven screen-with-live-tabs cases that need it. Today the concrete duplication is mostly inside one workspace (`ExchangeScreen` + `ExchangeDirectTab` + `ExchangeContactsTab`), and those panes are still tightly coupled to Exchange navigation, tab activation, and app-level bridge access. Migrating the parent screen and its live tab panes together keeps ownership visible, lets the team normalize refresh boundaries in one place, and preserves freedom to extract a helper later if Exchange and another aggregate workspace actually converge on the same contract.

### The repeated parent-plus-live-pane shape is now strong enough to justify a reusable screen-content primitive first

On reassessment, the cost/benefit tilts toward introducing a small reusable screen-content lifecycle primitive before finishing Exchange-specific migration. Exchange is the clearest hotspot, but it already exposes the recurring shape we care about: a parent screen owns workspace navigation and control-lane access while embedded live panes need standardized mount/resume activation, refresh kickoff, and cleanup. A helper extracted at this layer can make parent-vs-pane ownership explicit rather than hidden, provided it stays composable and narrow instead of becoming a monolithic base class for every screen.

### Exchange proving ground landed; remaining screen tail now narrows to standalone surfaces

`ScreenContentHost` has now landed in Exchange, so the highest-value remaining screen-side lifecycle work is no longer the parent-plus-live-pane shape. The next screen-side follow-up set is the standalone aggregate/workflow surfaces that still own ad hoc mount/resume logic directly, especially `InboxScreen`, `ContactsScreen`, `CommsScreen`, and `ProvisionScreen`.

## Decisions

### Decision: Prioritize aggregate mail/comms surfaces before local-form or wizard screens

**Status:** decided
**Rationale:** The main remaining contract violations are the screens that still duplicate mount/resume refresh behavior and bridge access across whole workspaces: Inbox, Exchange, Contacts, Comms, and the Exchange tab widgets that behave like embedded screens. These surfaces are where the shared lifecycle contract will eliminate the most duplicate refresh code and ownership ambiguity. Provision is a secondary lifecycle-heavy screen because of flash-worker ownership. Settings, DaemonSetup, FirstRunWizard, DeviceConsole, and Conversation can remain lower-priority cleanup until a concrete bug or refactor need appears.

### Decision: Migrate Exchange and its live tab panes together before extracting any reusable screen-content helper

**Status:** decided
**Rationale:** The Exchange parent screen and its Direct/Contacts tab panes are the current concrete hotspot for split lifecycle ownership. Solving that cluster directly gives the cleanest signal about the real parent-vs-tab contract, avoids introducing a speculative helper for a single known case, and still leaves the code free to extract a helper later if another aggregate workspace proves the abstraction.

### Decision: Start with a reusable screen-content lifecycle primitive before finishing Exchange-specific cleanup

**Status:** decided
**Rationale:** The repeated parent-screen plus live-pane shape is already concrete enough to justify a composable helper. A narrow screen-content primitive can standardize mount/resume activation, refresh kickoff, and cleanup for embedded live panes while still keeping ownership boundaries explicit. Exchange should become the proving ground for that helper rather than the reason to postpone it.

## Open Questions

*No open questions.*

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

## Acceptance Criteria

### Falsifiability

- This decision is wrong if: This design is wrong if the remaining screen-side work still treats static wizards and local forms as equally urgent with aggregate mail/comms workspaces.
- This decision is wrong if: This design is wrong if Exchange's embedded tab panes are ignored even though they still own screen-like refresh behavior.
- This decision is wrong if: This design is wrong if the plan reopens already-cleaned Dashboard, Exploration, MeshDeviceDetail, or NodeInfoPanel work without new evidence.
