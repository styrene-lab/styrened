# Reusable screen-content lifecycle primitive — Design Tasks

## 1. Lifecycle shape

- [x] 1.1 Identify why embedded live panes need a lifecycle distinct from whole-screen mount/resume semantics.
- [x] 1.2 Decide whether the reusable primitive should be parent-owned, pane-owned, or inheritance-based.
- [x] 1.3 Define how activation, deactivation, screen resume, screen suspend, and unmount should map onto embedded pane hooks.

## 2. Ownership boundaries

- [x] 2.1 Define how the helper keeps parent-screen ownership of tab navigation and shared bridge access explicit.
- [x] 2.2 Define how pane-local workers, timers, and auxiliary lanes compose with `WidgetResourceScope` rather than being hidden inside the host.
- [x] 2.3 Decide whether hidden panes should load eagerly or only when activated.

## 3. Proving ground and file scope

- [x] 3.1 Identify the first proving ground for the helper.
- [x] 3.2 Identify the initial file scope for implementation and regression coverage.
- [x] 3.3 Record falsifiability and design constraints needed before implementation.
