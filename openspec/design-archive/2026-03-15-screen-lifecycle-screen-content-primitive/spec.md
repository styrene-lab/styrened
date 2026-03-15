# Reusable screen-content lifecycle primitive — Design Spec

> This spec defines acceptance criteria for the design phase.
> Add Given/When/Then scenarios that must be true before marking this node 'decided'.

## Scenarios

### Scenario 1: Initial mount activates only the visible pane

Given a parent workspace registers multiple embedded live content slots
When the screen mounts with one tab already active
Then the lifecycle host activates only that visible pane
And hidden panes do not start their first refresh just because they were mounted in the DOM

### Scenario 2: Tab switches deactivate the previous pane before activating the next one

Given one embedded pane is active and another pane becomes active through parent navigation
When the parent forwards the tab change to the lifecycle host
Then the previous pane receives a deactivation or suspend transition before the new pane begins its refresh
And the newly active pane receives an activation or refresh transition without requiring a full screen remount

### Scenario 3: Screen suspend and unmount fan out cleanup without stealing parent ownership

Given an embedded pane owns timers, workers, or auxiliary lanes
When the parent screen is suspended or unmounted
Then the lifecycle host forwards suspend or cleanup to the relevant pane content
And pane-owned resources are released locally
And the shared control bridge remains parent-owned rather than being disconnected by the helper

## Falsifiability

- This design is wrong if the helper only works by turning embedded panes into subclasses of a heavyweight universal screen base.
- This design is wrong if hidden panes still eagerly fetch on initial parent mount, reintroducing the startup pressure this helper is meant to avoid.
- This design is wrong if the helper obscures ownership so completely that parent navigation, shared-bridge access, and pane-local cleanup responsibilities are no longer obvious.

## Constraints

- The primitive must keep parent-screen ownership of tab navigation and the shared control bridge explicit; panes may use the bridge but must not become ambient bridge owners.
- Hidden panes must not eagerly fetch on parent mount unless they are the active content slot.
- Pane-local timers, workers, and auxiliary lanes should compose with `WidgetResourceScope` or equivalent local helpers instead of reintroducing ad hoc cleanup logic inside the host.
- The primitive must work with embedded widgets/panes; it must not require every live pane to become a full `Screen` subclass.
