---
id: home-cop-node-summary-overflow-affordance
title: Home COP Node Summary Overflow Affordance
status: exploring
parent: tui-home-cop
tags: [tui, cop, ux, dashboard, nodes, overflow]
open_questions: []
---

# Home COP Node Summary Overflow Affordance

## Overview

Investigate operator confusion when the Home COP NODES panel visually shows only 1-2 rows at smaller terminal heights while the status bar reports a much larger mesh count. Determine whether Home should indicate that it is a viewport-limited summary rather than the full node set, and what affordance best communicates overflow without duplicating the Nodes workspace.

## Research

### Observed operator confusion in current Home COP layout

Current implementation uses HomeNodeSummaryTable inside DashboardScreen as a compact summary surface, while the full peer browser lives in ExplorationScreen. The data path does not intentionally filter the Home table to two peers: DashboardScreen._fetch_daemon_status() passes the full device list into HomeNodeSummaryTable.update_nodes(), which sorts and renders all non-LOST nodes. However, the dashboard CSS constrains #dashboard-container to height: 1fr and #activity-panel to max-height: 8, leaving the NODES panel with whatever vertical remainder exists. On shorter terminals this can leave only ~2 visible rows in the Home panel. Because the panel title is simply 'NODES' and there is no explicit overflow indicator, operators can reasonably infer that only two peers are known even while the status bar reports MESH styrene/total counts and the Nodes workspace shows many more entries.

## Decisions

### Decision: Home NODES panel should advertise overflow explicitly instead of pretending the viewport is the full mesh

**Status:** decided
**Rationale:** The Home COP is intentionally a compact summary, not a duplicate of the full Nodes workspace, but the current presentation fails to communicate that distinction at smaller terminal heights. The least noisy fix is an inline summary/overflow affordance on the table itself: track the total visible candidate count after filtering and render a compact hint such as 'showing 2 of 64 • press n for full list' whenever the viewport cannot display the full set. This preserves the summary role of Home, avoids panel-title churn, and directly answers the operator question raised by the mismatch between the Home panel and the Nodes workspace.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/home_node_summary.py` (modified) — Track filtered node count and render viewport overflow hint when fewer rows fit than exist.
- `tests/tui/widgets/test_home_node_summary.py` (modified) — Cover overflow metadata and hint rendering behavior.
- `tests/tui/screens/test_dashboard_tui.py` (modified) — Cover Home summary affordance expectations at the screen level.
- `~/.config/styrene/config.yaml` (modified) — Sync live daemon config with desired dev adapter setup so direct daemon launches enable adapter registration.

### Constraints

- Home remains a compact summary surface; do not duplicate the full Nodes workspace on Dashboard.
- Overflow cue should appear only when the viewport truncates the filtered non-lost set.
- Direct daemon launches read ~/.config/styrene/config.yaml via paths.config_file(); dev adapter setup must update that file, not only legacy or TUI-specific configs.
