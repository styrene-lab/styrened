# Reusable screen-content lifecycle primitive — Tasks

## 1. src/styrened/tui/lifecycle/screen_content.py (new)

- [x] 1.1 Proposed parent-owned screen-content host/controller for named embedded panes and lifecycle fan-out.

## 2. src/styrened/tui/screens/exchange.py (modified)

- [x] 2.1 First proving ground: register tab panes with the screen-content host and forward tab/screen lifecycle transitions through it.

## 3. src/styrened/tui/screens/exchange_tabs.py (modified)

- [x] 3.1 Adapt Direct/Contacts embedded panes to explicit activate/deactivate/resume/suspend hooks rather than ad hoc mount/resume fetches.

## 4. tests/tui/screens/test_exchange_lifecycle.py (new)

- [x] 4.1 Regression coverage for lazy first activation, tab-switch deactivation ordering, and suspend/unmount cleanup fan-out.

## 5. Cross-cutting constraints

- [x] 5.1 The primitive must keep parent-screen ownership of tab navigation and the shared control bridge explicit; panes may use the bridge but must not become ambient bridge owners.
- [x] 5.2 Hidden panes must not eagerly fetch on parent mount unless they are the active content slot.
- [x] 5.3 Pane-local timers, workers, and auxiliary lanes should compose with `WidgetResourceScope` or equivalent local helpers instead of reintroducing ad hoc cleanup logic inside the host.
- [x] 5.4 The primitive must work with embedded widgets/panes; it must not require every live pane to become a full `Screen` subclass.
