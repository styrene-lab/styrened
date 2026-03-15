---
id: screen-lifecycle-lane-aware-ipc-ownership
title: Lane-aware IPC ownership for long-running UI work
status: exploring
parent: screen-lifecycle
related: [tui-pages-browser-ipc-head-of-line-blocking, screen-lifecycle-widget-resource-primitives]
tags: [tui, lifecycle, ipc, workers, pages]
open_questions:
  - How should StyreneScreen and screen-owned widgets expose a standard ownership pattern for auxiliary IPC lanes and the workers that depend on them?
issue_type: task
priority: 1
---

# Lane-aware IPC ownership for long-running UI work

## Overview

Define the lifecycle rules for screen/widget-owned auxiliary IPC lanes: when a surface may spawn a sibling bridge, how lane ownership composes with StyreneScreen worker cleanup, how lane-specific degradation stays local, and how long-running operator-driven work avoids monopolizing the shared control lane.

## Research

### Pages browser execution lane is the first concrete lifecycle-owned lane pattern

The `tui-pages-browser-ipc-head-of-line-blocking` fix established the first concrete lane-aware lifecycle pattern in the TUI. `PageBrowserWidget` keeps the shared bridge as the control lane, lazily spawns an `execution` sibling bridge only for long-running page work, and disconnects that lane on teardown. This proves lane isolation can solve operator-visible head-of-line blocking without broad server-side concurrency changes or extra startup demand.

## Open Questions

- How should StyreneScreen and screen-owned widgets expose a standard ownership pattern for auxiliary IPC lanes and the workers that depend on them?
