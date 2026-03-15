---
id: screen-lifecycle-styrenescreen-migration-tail
title: Remaining StyreneScreen migration tail
status: decided
parent: screen-lifecycle
tags: [tui, lifecycle, migration, screens]
open_questions: []
issue_type: epic
priority: 2
---

# Remaining StyreneScreen migration tail

## Overview

Track the remaining screens and widgets that still rely on ad hoc mount/resume/suspend/unmount behavior instead of the shared StyreneScreen lifecycle contract so the umbrella architecture node can stop serving as the active implementation bucket.

## Research

### The remaining migration work is concentrated in a finite screen tail

The umbrella lifecycle node already landed the StyreneScreen base plus multiple ownership cleanups in Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel. The remaining migration tail is now a bounded set of surfaces that still rely on ad hoc mount/resume/suspend behavior or mixed widget-owned refresh logic rather than the shared contract; the earlier recommended order was Exploration, Inbox/Mail, Contacts, MeshDeviceDetail, Dashboard, then Settings, but recent work has already partially absorbed some of that list.

### Current repo scan shows the migration tail is split between screen surfaces and widget-owned refresh helpers

A fresh scan of `src/styrened/tui/screens` and `src/styrened/tui/widgets` shows no current screen class extends `StyreneScreen` on `main`, so the shared contract has not yet become the dominant implementation shape in the checked-in tree. The remaining screen-side tail is concentrated in Inbox, Exchange, Contacts, Comms, Conversation, Settings, Provision, DaemonSetup, FirstRunWizard, DeviceConsole, and smaller modal/support screens that still use ad hoc `on_mount`/`on_screen_resume` work launching. A parallel widget-side tail remains in helpers such as ChatWidget, CommandWidget, CommsSummary, MessageBubble, ForgeLog, and PageBrowserWidget, where timers, polling, image fetches, or auxiliary IPC-lane ownership still live below the screen layer.

## Decisions

### Decision: Track the remaining lifecycle debt as separate screen-surface and widget-support streams

**Status:** decided
**Rationale:** The fresh repo scan shows the remaining work is no longer one homogeneous migration list. Full screens still need the shared StyreneScreen contract applied consistently, while several lower-level widgets still own polling, event subscription, image loading, or auxiliary IPC-lane teardown. Splitting those streams keeps the epic actionable and prevents the umbrella lifecycle work from collapsing back into another catch-all bucket.

## Open Questions

*No open questions.*

## Acceptance Criteria

### Scenarios

#### Scenario 1: The remaining migration work is partitioned into actionable child streams

Given the umbrella `screen-lifecycle` node is already carrying the core contract and several landed cleanup passes  
When the remaining work is reviewed on the current repository state  
Then the residual implementation debt must be split into narrower child nodes instead of leaving the umbrella node as a catch-all implementation bucket

#### Scenario 2: The screen-side tail is identified separately from widget-owned refresh debt

Given some remaining surfaces are full screens and others are lower-level widgets  
When the migration tail is classified  
Then screen-surface migration work and widget-owned refresh or lane-ownership work must be tracked as distinct follow-up streams

#### Scenario 3: Recent IPC lane-isolation work is accounted for in the migration split

Given long-running Pages work now uses a dedicated lazy execution lane  
When the remaining lifecycle migration is partitioned  
Then the split must preserve space for lane-aware ownership and teardown patterns instead of treating all lifecycle debt as generic mount/resume cleanup

### Falsifiability

- This design is wrong if the remaining work still reads like one undifferentiated backlog after the repo scan.
- This design is wrong if screen-surface migration and widget-owned refresh/lane ownership remain mixed together with no clear ownership boundary.
- This design is wrong if the recent IPC lane-isolation pattern is ignored and the migration tail assumes only a single shared-bridge lifecycle model.

### Constraints

- Do not reopen `screen-lifecycle` as the generic active bucket for every remaining lifecycle concern.
- Keep the shared app bridge as the control lane; any auxiliary-lane work belongs in explicit follow-up lifecycle nodes.
- Preserve already-landed cleanup work in Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel instead of reclassifying them as unresolved without new evidence.
- Prefer child nodes that can later be implemented or assessed independently rather than one large migration umbrella.
