# Reusable screen-content lifecycle primitive — Design

## Architecture Decisions

### Decision: Model the primitive as a parent-owned screen-content host with explicit pane hooks

**Status:** decided
**Rationale:** The reusable part of the problem is the parent-to-pane lifecycle translation, not a new universal screen base. A small host/controller attached to the parent screen can register embedded live panes and forward activation, deactivation, resume, suspend, and cleanup transitions while keeping tab ownership and shared-bridge ownership explicit.

### Decision: Keep pane loading lazy and scoped to the active content slot

**Status:** decided
**Rationale:** Hidden panes should not add startup demand or background refresh load just because they are mounted inside a workspace. The primitive should activate only the initially visible pane on mount, refresh the newly active pane when tabs change or the screen resumes, and suspend/deactivate inactive panes so startup backpressure and lane ownership stay localized.

## Research Context

### Embedded live panes need an activation lifecycle distinct from screen resume

`ExchangeDirectTab` and `ExchangeContactsTab` are mounted as widgets inside `ExchangeScreen`'s `TabbedContent`, so they inherit screen resume indirectly but do not have a first-class notion of active-tab entry, active-tab exit, or parent-driven suspension. Today they bootstrap themselves in `on_mount()` and `on_screen_resume()`, which means hidden panes can still fetch on initial screen mount, and the parent screen must special-case other pane refreshes like Pages separately. The missing abstraction is not another full screen base; it is a way for the parent workspace to translate tab activation and screen suspend/resume into explicit lifecycle hooks for embedded live content.

### A parent-owned content host keeps ownership explicit while enabling reusable pane hooks

The clearest reusable shape is a small parent-owned lifecycle host or controller that registers named content slots and forwards `activate`, `deactivate`, `resume`, `suspend`, and final `cleanup` transitions to the currently relevant pane. This keeps tab selection, workspace navigation, and shared control-bridge ownership at the parent screen, while each pane keeps its own rendering and resource ownership. The host can standardize lazy first activation, cancellation/deactivation ordering when tabs switch, and screen-suspend cleanup without forcing embedded panes to masquerade as full `Screen` subclasses.

## File Changes

- `src/styrened/tui/lifecycle/screen_content.py` (new) — Proposed parent-owned screen-content host/controller for named embedded panes and lifecycle fan-out.
- `src/styrened/tui/screens/exchange.py` (modified) — First proving ground: register tab panes with the screen-content host and forward tab/screen lifecycle transitions through it.
- `src/styrened/tui/screens/exchange_tabs.py` (modified) — Adapt Direct/Contacts embedded panes to explicit activate/deactivate/resume/suspend hooks rather than ad hoc mount/resume fetches.
- `tests/tui/screens/test_exchange_lifecycle.py` (new) — Regression coverage for lazy first activation, tab-switch deactivation ordering, and suspend/unmount cleanup fan-out.

## Constraints

- The primitive must keep parent-screen ownership of tab navigation and the shared control bridge explicit; panes may use the bridge but must not become ambient bridge owners.
- Hidden panes must not eagerly fetch on parent mount unless they are the active content slot.
- Pane-local timers, workers, and auxiliary lanes should compose with `WidgetResourceScope` or equivalent local helpers instead of reintroducing ad hoc cleanup logic inside the host.
- The primitive must work with embedded widgets/panes; it must not require every live pane to become a full `Screen` subclass.
