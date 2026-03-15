# Composable widget lifecycle resource primitives — Design Tasks

## 1. Design exploration

- [x] 1.1 Decide that widget lifecycle reuse should be composition-first rather than a heavyweight shared base
- [x] 1.2 Define the first helper set as owned timers, owned subscriptions, owned workers, and owned auxiliary IPC lanes
- [x] 1.3 Constrain the helper layer so local widget degradation remains visible and test-safe worker scheduling conventions are preserved
