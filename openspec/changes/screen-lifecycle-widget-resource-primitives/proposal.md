# Composable widget lifecycle resource primitives

## Intent

> Parent: [Widget-owned refresh and lane-ownership tail](screen-lifecycle-widget-refresh-tail.md)
> Spawned from: "What composable widget lifecycle helper set should standardize timer, subscription, worker, and auxiliary-lane ownership without forcing a heavyweight shared base?"

Define the reusable helper layer that widget-owned live resources should use before further widget-by-widget cleanup proceeds. The goal is to normalize ownership semantics once, keep widget-local degradation visible, and avoid solving timers, subscriptions, worker launch, and auxiliary IPC-lane teardown in four different ad hoc ways.
