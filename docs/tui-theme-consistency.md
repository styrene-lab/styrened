---
id: tui-theme-consistency
title: TUI Theme Consistency — Cascade Sync, Residual Hardcodes, and Structural Gaps
status: decided
parent: tui-specification
tags: [tui, theming, ux, color-cascade, css, rich-markup]
open_questions: []
branches: ["feature/tui-theme-consistency"]
openspec_change: tui-theme-consistency
---

# TUI Theme Consistency — Cascade Sync, Residual Hardcodes, and Structural Gaps

## Overview

Audit of TUI theming architecture after the cascade sync fix and bulk Rich markup migration. Identifies remaining color bleed sources, architectural tensions between the two theming systems (CSS variables vs ColorCascade), and concrete improvement opportunities.

## Research

### Current state: two parallel theming systems

The TUI has two color systems that must stay in sync:

**1. Textual CSS Variables** — `$primary`, `$surface`, `$success`, `$error`, `$warning`, `$background`, `$panel`, `$text-muted`
Used by: TCSS files (`styrene.tcss`), widget DEFAULT_CSS, Textual built-in widgets (Button, Switch, DataTable, Input, etc.)
Set by: The active Textual Theme (styrene brand, forge world presets, or tweakcn custom themes)
Coverage: ~1122 lines in styrene.tcss. All clean — zero hardcoded hex/named colors in TCSS.

**2. ColorCascade** — `cascade.bright`, `.medium`, `.dim`, `.dark`, `.color_success`, `.color_warning`, `.color_danger`
Used by: Rich markup in Python code — `f"[{cascade.bright}]text[/]"`
Set by: Module-level `_current_cascade` in highlighted_panel.py, updated via `set_color_cascade()`
Coverage: ~423 call sites across 16 files.

**The sync mechanism** (just added): `app.watch_theme()` → `_sync_cascade_to_theme()` → `ColorCascade.from_textual_theme(theme)` → `set_color_cascade()`. This derives cascade colors from the Textual theme's accent/primary/success/warning/error. Previously, cascade was set once at startup to the styrene brand colors and never updated.

**Architectural tension**: CSS variables are reactive — when the theme changes, all CSS re-evaluates automatically. Cascade is imperative — Rich markup bakes hex values into strings at render time. If a widget renders Rich markup during compose() and the theme changes later, that widget shows stale colors until it re-renders. Most widgets re-render naturally via Textual's reactive system, but Static widgets with pre-baked strings do not.

### Residual hardcoded colors (7 remaining)

After the bulk migration of 132 Rich `[color]` tags and 2 dynamic color variables, 7 hardcoded color references remain:

**chat_widget.py (4 instances)** — `[red bold]` and `[red italic]` for failed message status icons and failed message text. The original script searched for `[bold red]` but missed `[red bold]` (reversed word order).
- Line 420: `f"[red bold]{STATUS_ICONS['failed']}[/]"`
- Line 423: `f"[red italic]{child.raw_content}[/]"`
- Line 640: `f"[red bold]{STATUS_ICONS['failed']}[/]"`
- Line 873: `f"[red bold]{STATUS_ICONS['failed']}[/]"`

**home_status_bar.py (3 instances)** — Rich `Text()` objects with `style="bold yellow"` and `style="bold cyan"`. These use the Rich `style` kwarg on Text objects, not bracket markup — a different API surface the migration script didn't target.
- Line 74: `Text("HUB ○ lost", style="bold yellow")`
- Line 86: `Text("IPC ○", style="bold yellow")`
- Line 90: `Text(f"✉ {self.unread_count}", style="bold cyan")`

**Fix**: Trivial. Replace with cascade hex values:
- `style="bold yellow"` → `style=f"bold {get_color_cascade().color_warning}"`
- `style="bold cyan"` → `style=f"bold {get_color_cascade().medium}"`
- `[red bold]` → `[{cascade.color_danger} bold]`
- `[red italic]` → `[{cascade.color_danger} italic]`

### Structural gap: Static widgets with baked-in cascade values don't refresh on theme change

**The problem**: When a widget calls `compose()`, it builds `Static(f"[{cascade.bright}]text[/]")`. The hex value is baked into the string. If the theme changes later (Settings → Apply tweakcn theme), the Static's content still has the old hex. CSS-styled elements update automatically; Rich-markup elements do not.

**Affected patterns**:
- `compose()` methods that yield Static widgets with cascade-colored content (exchange.py compose-hint, inbox compose-hint, first_run_wizard headings)
- DataTable rows built with cascade values — these update on next `_rebuild_table()` call but not instantly
- Status lines set via `.update()` — these update naturally when next set

**Current mitigations**:
- `watch_theme()` calls `_refresh_themed_panels()` which refreshes NodeInfoPanel
- HighlightedPanel has `refresh_theme()` method called from watch_theme
- Most dynamic content (tables, status bars) re-renders on timers/events

**Remaining gap**: Static compose-time content (hints, labels, wizard text) bakes cascade values at mount time. If the operator changes theme while on the Exchange screen, the "Enter hash or name" hint retains old colors until screen remount.

**Assessment**: LOW PRIORITY. Theme changes are rare (settings only), and remounting the screen (navigating away and back) fixes it. Not worth adding a reactive refresh system for static hint text.

### Broader UX improvements identified in audit

Beyond color consistency, the deep dive revealed these UX/UI improvement opportunities:

**1. Switch widget visibility at height:1**
The Textual Switch at `height: 1` in styrene.tcss renders as two tiny colored blocks that are barely distinguishable, especially on dark themes. The Auto-Reply switch in Exchange is nearly invisible. Options: increase to height:2, or replace with a text-based toggle ("ON"/"OFF" Static that toggles on click).

**2. HomeStatusBar uses Rich Text() render — not CSS**
The entire HomeStatusBar renders via `def render() -> Text`, building a Rich Text object segment by segment with `style=` kwargs. This is the ONLY widget in the TUI that uses this pattern for status display — all others use either CSS-styled widgets or cascade Rich markup. This makes it immune to CSS theme changes. The fix from the prior assessment (SCADA-style anomaly-first status bar) would naturally resolve this since the proposed HomeStatusBar widget already exists and uses cascade.

**3. DataTable row colors are only cascade, never CSS**
DataTable cell content is Rich markup (cascade hex values baked in). The DataTable itself uses CSS variables for cursor/header/background. But the actual text colors in cells are cascade-derived. This means table row text colors are correctly theme-synced NOW (with the cascade sync fix) but were stale before. No action needed — the sync fix covers this.

**4. activity_feed.py uses cascade correctly (19 refs)**
The ActivityFeedWidget builds Rich markup with cascade. Already theme-correct post-sync fix.

**5. node_info_panel.py renders entirely via Rich markup (44 cascade refs)**
The two-column Rich markup layout in NodeInfoPanel is the most cascade-heavy widget. It re-renders via `refresh_data()` which is called from `_refresh_themed_panels()` in watch_theme. Theme-correct.

**6. device_status_widget.py (53 cascade refs)**
Heavy cascade usage for status indicators, connection quality, latency display. Renders via reactive properties that trigger re-render. Theme-correct post-sync.

**7. Exploration screen status summary line**
`● 20 active  ◐ 43 stale  ○ 335 lost` — uses cascade correctly. Was showing green/yellow when cascade was stale. Fixed by sync.

**8. MeshDeviceDetailScreen info panel**
Uses cascade for Name/Type/Identity/LastSeen labels. Lines 109-113 use `cascade.bright`/`cascade.medium` for Styrene/RNode name differentiation. Correct post-sync.

**9. No theme preview in Settings**
When the operator selects a forge-world preset or enters a tweakcn URL, there's no preview before committing. The color picker dialog helps for individual colors but there's no "preview this theme on actual content" capability.

### Architecture verdict: broader rules, not subclassing

**The question**: Do we need to fully subclass Textual widgets for theme consistency, or are broader-scoped rules and paradigms the fix?

**Answer: Broader rules. No subclassing needed.** Here's why:

1. **Textual's built-in widgets (Button, Switch, DataTable, Input, Header, Footer, TabbedContent) are already theme-correct.** They use CSS variables internally. Our TCSS overrides also use CSS variables. No subclassing needed for any built-in widget.

2. **Our custom widgets (HighlightedPanel, HomeStatusBar, NodeInfoPanel, etc.) use the ColorCascade system.** The cascade is now synced to the active theme. These widgets re-render correctly because:
   - Widgets using reactive properties auto-re-render
   - `watch_theme()` explicitly refreshes HighlightedPanel and NodeInfoPanel
   - DataTable content rebuilds on timer/event refresh cycles

3. **The root cause of all color bleed was ONE missing call**: `set_color_cascade()` was never invoked when the theme changed. The cascade was frozen on the styrene brand at startup. The `_sync_cascade_to_theme()` fix resolves this for all 423 cascade call sites simultaneously.

4. **The 7 residual hardcodes are stragglers from the migration**, not a systemic pattern. Fixing them is a 5-minute patch, not an architectural change.

**The rules that prevent future regressions**:
- NEVER use named colors in Rich markup: no `[green]`, `[red]`, `[yellow]`, `[dim]`
- NEVER use named colors in Rich `style=` kwargs: no `style="bold yellow"`
- ALWAYS use cascade: `f"[{cascade.bright}]"` or `f"[{get_color_cascade().color_danger}]"`
- ALWAYS use CSS variables in TCSS: `$primary`, `$success`, `$error`, `$warning`
- For Button variants: use Textual's `variant="primary"/"success"/"warning"/"error"/"default"`
- The cascade syncs automatically via `watch_theme()` → `_sync_cascade_to_theme()`

**What WOULD require subclassing** (future, not needed now):
- If we wanted cascade colors to be CSS-reactive (change mid-render without re-render) — would need a custom widget that reads CSS variables and translates to Rich markup. Over-engineering for current needs.
- If Textual adds new built-in widgets that don't respect themes — unlikely, but would need CSS overrides in styrene.tcss.

## Decisions

### Decision: Broader rules fix, not subclassing — cascade sync + migration stragglers

**Status:** decided
**Rationale:** The root cause was a single missing sync call, not an architectural flaw. The two-system approach (CSS variables for layout/widgets, ColorCascade for Rich markup) is sound — they just weren't connected. Subclassing would add complexity with no benefit since all built-in widgets already use CSS variables and all custom widgets already use cascade. Fix: (1) cascade sync on theme change (done), (2) patch 7 residual hardcodes, (3) codify the convention as a linting rule.

### Decision: Switch widget needs height:2 or text-based toggle for visibility

**Status:** exploring
**Rationale:** At height:1, Textual's Switch renders as two nearly-invisible colored blocks on dark themes. The Auto-Reply toggle in Exchange is the clearest example — user screenshot shows two tiny dark squares that are indistinguishable from the background. Either bump to height:2 (easy, standard Textual rendering) or replace with a styled text toggle.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/home_status_bar.py` (modified) — Replaced all Rich Text style= hardcoded colors with cascade; added transport_enabled, propagation_enabled, active_links reactive props with T/P role indicators and LNK count in status bar
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Fixed 4 remaining [red bold]/[red italic] hardcodes to cascade.color_danger
- `src/styrened/tui/screens/mesh_device_detail.py` (modified) — Added hops, discovered_via, and lxmf_destination_hash to device detail view
- `src/styrened/tui/screens/dashboard.py` (modified) — Wired transport_enabled, propagation_enabled, active_links from DaemonStatus to HomeStatusBar
- `src/styrened/tui/styles/styrene.tcss` (modified) — Switch height: 1 → height: auto for better visibility on dark themes

### Constraints

- terminal_widget.py ANSI color map is exempt — those are terminal emulation, not theming
- color_picker.py white Style is exempt — intentional contrast for swatch rendering
