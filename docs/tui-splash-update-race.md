---
id: tui-splash-update-race
title: "Splash Screen / Update Check Race Condition"
status: exploring
parent: tui-specification
tags: [tui, bug, lifecycle, splash, update, race-condition]
open_questions:
  - Should _check_for_updates defer its UpgradeScreen push until after _on_splash_complete, or should it stash the result and let _on_splash_complete check for a pending upgrade?
  - "Does the 'r' refresh keybinding need guards against pushing UpgradeScreen when one is already in the stack?"
issue_type: bug
priority: 2
---

# Splash Screen / Update Check Race Condition

## Overview

on_mount fires _check_for_updates() and push_screen(SplashScreen) concurrently. Both can push screens onto the stack simultaneously — SplashScreen, UpgradeScreen, and DashboardScreen all compete for the screen stack. Operator reported: splash drops into update screen, then dashboard appears, pressing 'r' brings update back, attempting upgrade crashes.\n\nRoot cause: _check_for_updates is a @work(exclusive=True) that may push UpgradeScreen before SplashScreen dismisses. SplashScreen's callback then switches to dashboard, leaving UpgradeScreen orphaned or buried. Re-triggering it via 'r' hits stale state.\n\nThe fix needs to sequence these: splash completes first, then update check runs (or update check result is held until splash dismisses).

## Open Questions

- Should _check_for_updates defer its UpgradeScreen push until after _on_splash_complete, or should it stash the result and let _on_splash_complete check for a pending upgrade?
- Does the 'r' refresh keybinding need guards against pushing UpgradeScreen when one is already in the stack?
