# Aggregate refresh surfaces lifecycle migration

## Intent

> Parent: [Remaining screen-surface lifecycle migration](screen-lifecycle-remaining-screen-surfaces.md)
> Spawned from: "How should the remaining aggregate standalone refresh surfaces (`InboxScreen`, `ContactsScreen`, `CommsScreen`) migrate onto the shared StyreneScreen/lifecycle helper contract?"

Narrow the remaining standalone screen lifecycle tail to the three aggregate refresh workspaces that still duplicate the old contract directly: `InboxScreen`, `ContactsScreen`, and `CommsScreen`. The design goal is to migrate those screens onto `StyreneScreen` and screen-local `WidgetResourceScope` ownership without inventing another intermediate helper layer, while keeping explicit UI bootstrap and local degraded-state rendering visible at each screen boundary.
