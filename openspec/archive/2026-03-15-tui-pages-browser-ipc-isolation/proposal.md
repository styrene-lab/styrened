# Isolate page browsing from control-plane IPC

## Intent

Fix the remaining Pages-tab lag by moving long-running page fetch traffic off the shared TUI IPC bridge. Preserve separated traffic classes so quick control/command work, bulk data refreshes, and long-running interactive page loads do not collapse onto one shared lane. Page-browser degradation must remain distinct from daemon liveness, and the fix must not increase baseline startup demand or reintroduce screen-owned caches.

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
