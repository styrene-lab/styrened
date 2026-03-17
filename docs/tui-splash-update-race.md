---
id: tui-splash-update-race
title: "Splash Screen / Update Check Race Condition"
status: implemented
parent: tui-specification
tags: [tui, bug, lifecycle, splash, update, race-condition]
open_questions: []
issue_type: bug
priority: 2
---

# Splash Screen / Update Check Race Condition

## Overview

on_mount fires _check_for_updates() and push_screen(SplashScreen) concurrently. Both can push screens onto the stack simultaneously — SplashScreen, UpgradeScreen, and DashboardScreen all compete for the screen stack. Operator reported: splash drops into update screen, then dashboard appears, pressing 'r' brings update back, attempting upgrade crashes.\n\nRoot cause: _check_for_updates is a @work(exclusive=True) that may push UpgradeScreen before SplashScreen dismisses. SplashScreen's callback then switches to dashboard, leaving UpgradeScreen orphaned or buried. Re-triggering it via 'r' hits stale state.\n\nThe fix needs to sequence these: splash completes first, then update check runs (or update check result is held until splash dismisses).

## Decisions

### Decision: Defer update check until after splash completes

**Status:** decided
**Rationale:** Move _check_for_updates from on_mount to _post_dashboard_init (called via call_after_refresh from _proceed_after_daemon). This sequences: splash → dashboard paint → cache prime → update check. No concurrent screen pushes.

## Open Questions

*No open questions.*
