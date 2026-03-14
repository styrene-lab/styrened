# tui-device-cache-regression-fixes — Tasks

## 1. Cache-backed node consumers tolerate unprimed cache state

- [x] 1.1 Add regression coverage for empty/unprimed cache behavior in Nodes and peer-detail flows
- [x] 1.2 Repair runtime fallback semantics in `ExplorationScreen` and `MeshDeviceDetailScreen`

## 2. Bare-screen or test contexts do not report false daemon disconnects

- [x] 2.1 Add dashboard status wiring coverage for cache-backed reads in bare-screen unit contexts
- [x] 2.2 Guard dashboard cache access so successful bridge calls do not masquerade as daemon disconnects

## 3. Startup and navigation tests reflect current Home and splash ownership

- [x] 3.1 Update app startup tests to expect `SplashScreen` first
- [x] 3.2 Retire or rewrite legacy dashboard tree imports in navigation and integration tests
- [x] 3.3 Reconcile dashboard / activity-routing tests with current screen-local event posting behavior
