# TUI Theme Consistency — Cascade Sync, Residual Hardcodes, and Structural Gaps — Design Spec (extracted)

> Auto-extracted from docs/tui-theme-consistency.md at decide-time.

## Decisions

### Broader rules fix, not subclassing — cascade sync + migration stragglers (decided)

The root cause was a single missing sync call, not an architectural flaw. The two-system approach (CSS variables for layout/widgets, ColorCascade for Rich markup) is sound — they just weren't connected. Subclassing would add complexity with no benefit since all built-in widgets already use CSS variables and all custom widgets already use cascade. Fix: (1) cascade sync on theme change (done), (2) patch 7 residual hardcodes, (3) codify the convention as a linting rule.

### Switch widget needs height:2 or text-based toggle for visibility (exploring)

At height:1, Textual's Switch renders as two nearly-invisible colored blocks on dark themes. The Auto-Reply toggle in Exchange is the clearest example — user screenshot shows two tiny dark squares that are indistinguishable from the background. Either bump to height:2 (easy, standard Textual rendering) or replace with a styled text toggle.

## Research Summary

### Current state: two parallel theming systems

The TUI has two color systems that must stay in sync:

**1. Textual CSS Variables** — `$primary`, `$surface`, `$success`, `$error`, `$warning`, `$background`, `$panel`, `$text-muted`
Used by: TCSS files (`styrene.tcss`), widget DEFAULT_CSS, Textual built-in widgets (Button, Switch, DataTable, Input, etc.)
Set by: The active Textual Theme (styrene brand, forge world presets, or tweakcn custom themes)
Coverage: ~1122 lines in styrene.tcss. All clean — zero hardcoded hex/named colors in TCSS.

**2.…

### Residual hardcoded colors (7 remaining)

After the bulk migration of 132 Rich `[color]` tags and 2 dynamic color variables, 7 hardcoded color references remain:

**chat_widget.py (4 instances)** — `[red bold]` and `[red italic]` for failed message status icons and failed message text. The original script searched for `[bold red]` but missed `[red bold]` (reversed word order).
- Line 420: `f"[red bold]{STATUS_ICONS['failed']}[/]"`
- Line 423: `f"[red italic]{child.raw_content}[/]"`
- Line 640: `f"[red bold]{STATUS_ICONS['failed']}[/]"`
…

### Structural gap: Static widgets with baked-in cascade values don't refresh on theme change

**The problem**: When a widget calls `compose()`, it builds `Static(f"[{cascade.bright}]text[/]")`. The hex value is baked into the string. If the theme changes later (Settings → Apply tweakcn theme), the Static's content still has the old hex. CSS-styled elements update automatically; Rich-markup elements do not.

**Affected patterns**:
- `compose()` methods that yield Static widgets with cascade-colored content (exchange.py compose-hint, inbox compose-hint, first_run_wizard headings)
- DataTab…

### Broader UX improvements identified in audit

Beyond color consistency, the deep dive revealed these UX/UI improvement opportunities:

**1. Switch widget visibility at height:1**
The Textual Switch at `height: 1` in styrene.tcss renders as two tiny colored blocks that are barely distinguishable, especially on dark themes. The Auto-Reply switch in Exchange is nearly invisible. Options: increase to height:2, or replace with a text-based toggle ("ON"/"OFF" Static that toggles on click).

**2. HomeStatusBar uses Rich Text() render — not CSS**
T…

### Architecture verdict: broader rules, not subclassing

**The question**: Do we need to fully subclass Textual widgets for theme consistency, or are broader-scoped rules and paradigms the fix?

**Answer: Broader rules. No subclassing needed.** Here's why:

1. **Textual's built-in widgets (Button, Switch, DataTable, Input, Header, Footer, TabbedContent) are already theme-correct.** They use CSS variables internally. Our TCSS overrides also use CSS variables. No subclassing needed for any built-in widget.

2. **Our custom widgets (HighlightedPanel, Hom…
