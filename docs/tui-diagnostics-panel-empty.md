---
id: tui-diagnostics-panel-empty
title: Diagnostics Panel Empty — No Backfill, Lazy Subscription
status: implemented
parent: tui-global-cop-surface
tags: [tui, diagnostics, bug, activity-feed, nodes]
open_questions: []
---

# Diagnostics Panel Empty — No Backfill, Lazy Subscription

## Overview

The Diagnostics tab in ExplorationScreen (Nodes workspace) contains only an ActivityFeedWidget. The IPC activity subscription fires lazily on first tab activation — so the panel is always empty on first view. Worse, there's no historical backfill: even after activating, you only see events from that moment forward. The fix needs two things: (1) subscribe at screen mount, not on tab click, and (2) seed the feed with recent activity history from the daemon on connect.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/exploration.py` (modified) — Subscribe to activity at screen mount (not on Diagnostics tab click). Remove _diagnostics_subscribed lazy flag.
- `src/styrened/ipc/handlers.py` (modified) — Add GET_ACTIVITY_HISTORY handler that returns the last N activity events from a ring buffer maintained by the daemon.
- `src/styrened/ipc/bridge.py` (modified) — Add get_activity_history() method.
- `src/styrened/tui/widgets/activity_feed.py` (modified) — Add backfill_history(events) method to seed feed with historical events on connect.

### Constraints

- Activity subscription should start at screen mount so the feed is live before the operator ever clicks the tab.
- Daemon should maintain a fixed-size ring buffer (e.g. last 200 activity events) so backfill is available without unbounded memory growth.
- Backfill events should be visually distinguished (dimmer) from live events so the operator knows what's historical vs real-time.
