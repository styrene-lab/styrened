---
id: tui-keybinding-audit
title: TUI Keybinding Audit — Mnemonic Failures, Conflicts, Hidden Workspaces
status: implemented
tags: [tui, ux, keybindings, navigation]
open_questions: []
---

# TUI Keybinding Audit — Mnemonic Failures, Conflicts, Hidden Workspaces

## Overview

App-level nav keybindings have accumulated inconsistencies: mnemonic failures (x→Exchange, o→Sort), real key conflicts where the same letter does different things depending on active screen (n, a), and hidden workspace bindings that are either vestigial or should be promoted. Escape should universally mean Back.

## Decisions

### Decision: Fix set: mnemonic failures, conflicts, and dead aliases

**Status:** decided
**Rationale:** 1. x→Exchange renamed to e→Exchange (e is free at app level, mnemonic). 2. exploration n→Home removed — escape already handles back/home from every screen. 3. i→Mail alias removed — m is the canonical key. 4. c→Comms and b→Contacts promoted to show=True (workspaces exist, should be discoverable). 5. exchange/inbox o→Sort renamed to t→Sort (t for time-sort; s is taken by Sync). 6. g→Global COP added (new workspace). 7. a conflict (app Announce vs Contacts Add): screen-local Add moves to ctrl+a; app Announce keeps bare a. 8. n conflict (app Nodes vs Exchange/Inbox New): screen-local New compose moves to ctrl+n.

## Open Questions

*No open questions.*
