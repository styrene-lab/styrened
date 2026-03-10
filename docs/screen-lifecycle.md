---
id: screen-lifecycle
title: Screen Lifecycle Contract
status: implementing
parent: tui-specification
related: [tui-data-state-model]
tags: [tui, architecture, textual, lifecycle]
open_questions: []
---

# Screen Lifecycle Contract

## Overview

Define a consistent lifecycle contract for all styrene TUI screens: when to load data, how to handle async refresh, how to react to screen resume/suspend, how to degrade when IPC is unavailable, and how to clean up on pop.

## Research

### Textual's Built-in Lifecycle Events

Textual provides these lifecycle events for screens/widgets, in order:

1. **`Compose`** (internal) — Textual calls `compose()` to build the widget tree. Yields child widgets. **Pure structure, no side effects.** No async allowed. Called once unless `recompose=True` reactive triggers a rebuild.

2. **`Mount`** → `on_mount()` — Sent after widget is mounted into the DOM and can receive messages. Called **once** per mount. This is where initial data loading should happen. Can be async. Textual guarantees all composed children are mounted before the parent's `on_mount` fires.

3. **`Show`** → `on_show()` — Sent when a widget is first displayed. Similar timing to Mount but specifically about visibility.

4. **`ScreenResume`** → `on_screen_resume()` — Sent to a screen that was **inactive** (another screen was on top) and is now active again. This is the re-entry hook — use it to refresh stale data when the user navigates back. `refresh_styles = True` by default.

5. **`ScreenSuspend`** → `on_screen_suspend()` — Sent to a screen when it becomes inactive (another screen pushed on top, or mode switch). Use to pause timers, cancel workers, or save state.

6. **`Hide`** → `on_hide()` — Sent when a widget is hidden (display: none, or removed from view).

7. **`Unmount`** → `on_unmount()` — Sent when a widget is removed from the DOM. Cleanup hook — cancel workers, close connections.

**Key insight:** `compose()` and `on_mount()` run **once**. `on_screen_resume()`/`on_screen_suspend()` run **every time** the screen is pushed/popped over. There is no built-in \"refresh\" event — you must implement periodic or event-driven refresh yourself via timers (`set_interval`), workers, or message handlers."

### Textual's Data Loading Patterns

Textual provides three mechanisms for async data loading:

**1. Workers (`@work` decorator / `run_worker()`)**
- The primary mechanism for async/threaded work that touches the UI
- `exclusive=True` — cancels any previous worker in the same group before starting
- `group=\"name\"` — groups workers for cancellation/tracking
- `thread=True` — runs in a thread (for blocking I/O), must use `call_from_thread()` to touch widgets
- Worker state changes fire `Worker.StateChanged` messages for progress tracking
- **Pattern:** `on_mount` kicks off a worker, worker fetches data, worker updates widget reactives

**2. Reactive attributes with watchers**
- `reactive(default, recompose=True)` — rebuilds entire widget tree when value changes
- `watch_<attr>(self, new_value)` — called when reactive changes, can update specific widgets
- **Pattern:** Screen has `data: reactive[list] = reactive([])`, worker sets `self.data = fetched`, `watch_data` updates the table/tree

**3. Timers (`set_interval` / `set_timer`)**
- `set_interval(seconds, callback)` — periodic refresh
- Returns a `Timer` object that can be paused/resumed/stopped
- **Pattern:** `on_mount` starts interval, `on_screen_suspend` pauses, `on_screen_resume` resumes

**Recommended Textual patterns from docs and community:**
- `compose()` is **structure only** — yield placeholder/loading widgets
- `on_mount()` kicks off initial data load via `@work`
- Workers update reactives, watchers update widgets
- `exclusive=True` workers prevent duplicate fetches
- `on_screen_resume` refreshes stale data (another `@work` call)
- Never block the event loop — all I/O in workers"

### Current Styrene Screen Patterns (Inconsistency Audit)

Current screens use lifecycle hooks inconsistently:

**on_mount usage (16 screens/widgets):** All 13 screens implement `on_mount()`. Most do synchronous data loading directly in `on_mount`, which blocks the event loop. Only `ProvisionScreen.on_mount` is async.

**on_screen_resume usage (2 screens):**
- `DashboardScreen.on_screen_resume` — refreshes device table and hub status
- `InboxScreen.on_screen_resume` — refreshes conversation list
- 11 other screens have **no resume handler** — data goes stale when you navigate away and back

**on_screen_suspend usage: 0 screens.** No screen pauses timers or cancels workers when pushed under.

**on_unmount usage: 0 screens.** No cleanup of workers, timers, or subscriptions on pop.

**Worker usage:** Dashboard uses `run_worker` for hub status polling. Most other screens call IPC bridge methods directly in synchronous `on_mount` or event handlers without workers.

**Timer usage:** Dashboard has `set_interval` for periodic refresh. No other screen uses timers. No screen pauses/resumes timers on suspend/resume.

**Error handling in lifecycle:** Most `on_mount` methods have bare `try/except` around the entire body, silently swallowing failures. No loading state shown, no retry mechanism, no user feedback on failure."

### Broader TUI/UI Lifecycle Patterns

Cross-framework lifecycle patterns that apply to Textual screens:

**Android Activity Lifecycle (gold standard for screen state):**
- `onCreate` → build UI (= compose)
- `onStart`/`onResume` → refresh data, start observers (= mount + screen_resume)
- `onPause`/`onStop` → pause work, save state (= screen_suspend)
- `onDestroy` → cleanup (= unmount)
- Key principle: **never assume data is fresh after resume** — always re-fetch or validate

**SwiftUI onAppear/onDisappear + .task:**
- `.task { }` — async work tied to view lifecycle, auto-cancelled on disappear
- `.onAppear` — refresh, re-subscribe
- `.onDisappear` — cancel, unsubscribe
- Key principle: **task cancellation is automatic** — the framework handles cleanup

**React useEffect cleanup pattern:**
- `useEffect(() => { fetch(); return () => cancel(); }, [deps])` 
- Cleanup function runs on unmount AND before re-run
- Key principle: **every side effect has a paired cleanup**

**Common principles across all frameworks:**
1. **Compose/render is pure** — no side effects, no I/O, just structure
2. **Mount kicks off initial load** — but always async/non-blocking
3. **Resume refreshes** — data may be stale, re-fetch or validate
4. **Suspend pauses** — stop timers, cancel non-essential workers
5. **Unmount cleans up** — cancel everything, release resources
6. **Loading states are explicit** — show skeleton/spinner during async load, not blank screen
7. **Errors are surfaced** — not swallowed — with retry affordance"

### Performance Analysis: Resume Refresh Strategies

**Cost of a full refresh per screen:**
Each screen's `_load_data()` makes 1-5 IPC round-trips over Unix socket. Each IPC call is ~1-5ms local (serialize → socket write → daemon handler → socket read → deserialize). So a full refresh is 5-25ms per screen transition — negligible for user-initiated navigation.

**But the real cost is periodic polling:**
Dashboard currently polls hub status on a `set_interval`. If every screen had its own timer polling its own data, we'd have N timers × M IPC calls running constantly, even on suspended screens. On a Pi Zero 2W (512MB, 1GHz quad-core), this adds up:
- 13 screens × ~3 IPC calls × every 30s = 39 IPC calls/30s = 1.3 calls/sec sustained
- Each call is small, but the async overhead (coroutine creation, worker scheduling, socket I/O) is non-trivial on constrained hardware
- More critically: the **daemon** handles every IPC request — polling from invisible screens wastes daemon cycles

**Centralized timer approach:**
- Single app-level timer (e.g. every 30s, configurable)
- Posts a custom `DataStale` message or calls `invalidate()` on the **active screen only**
- Suspended screens receive nothing — zero overhead when not visible
- Active screen's `_load_data()` runs via exclusive worker — at most 1 refresh in flight
- Timer pauses when app is suspended (Ctrl+Z), resumes on foreground
- TUIMode can influence interval: OPERATOR=30s, FLEET=15s, FIELD=120s, KIOSK=60s

**Experimental/debug full-refresh mode:**
- Config flag: `tui.debug_refresh: true` (or TUIMode-gated)
- Forces full `_load_data()` on every `on_screen_resume` regardless of staleness
- Useful for: debugging stale data bugs, validating that refresh logic is correct, CI testing
- Not on by default — it's a diagnostic tool

**Comparison:**
| Strategy | IPC load | Complexity | Data freshness | Edge-safe |
|----------|----------|------------|----------------|-----------|
| Full refresh every resume | Low (user-paced) | Low | Good | ✅ |
| Per-screen timers | High (N×M polling) | High | Best | ❌ |
| Centralized timer | Minimal (1 screen) | Low | Good | ✅ |
| Push-based (daemon events) | Minimal (event-driven) | High (needs pub/sub IPC) | Best | ✅ |

**Recommendation:** Centralized timer + full refresh on resume. The timer handles background staleness for the active screen. Resume always refreshes because the user explicitly navigated back (the 5-25ms cost is invisible in a screen transition). Push-based is architecturally cleaner but requires IPC pub/sub infrastructure we don't have yet — it's a future optimization, not a prerequisite."

### Unmount-time async cleanup should not allocate orphaned coroutines

ChatWidget unmount cleanup previously called `run_worker(bridge.unsubscribe(...))`, which could leave an un-awaited coroutine during shutdown/test teardown. The cleanup path now schedules unsubscribe with `asyncio.create_task()` and consumes completion safely, avoiding Python 3.14 unraisable coroutine warnings during screen teardown.

### Localized subscription scan found adjacent dashboard event-stream mismatch

After fixing ChatWidget unmount-time unsubscribe scheduling, a localized scan of neighboring TUI subscription code found DashboardScreen still using a non-existent `bridge.subscribe_events()` helper. The dashboard activity feed now uses the same explicit IPC lifecycle pattern as the bridge contract: `await bridge.subscribe_activity()` followed by `bridge.iter_events(IPCMessageType.EVENT_ACTIVITY)`. Added targeted tests to lock both the dashboard activity subscription path and chat-widget unmount unsubscribe behavior.

### Second-ring lifecycle scan found timer cleanup gaps beyond chat/dashboard

A broader scan of nearby lifecycle code found two more localized cleanup issues in the same surfaced area: TerminalWidget unmount used `asyncio.get_event_loop().create_task(...)` for terminal_close, and ForgeLog started a 1s mesh-watch interval without tracking/stopping it on reset or unmount. TerminalWidget now uses `asyncio.create_task()` with completion consumption, matching ChatWidget teardown. ForgeLog now stores its timer and stops it on reset, successful node detection, and unmount. Remaining larger-pattern hotspots still exist in screens like Dashboard, Exploration, and LocalDashboard where intervals are started but not yet paired with suspend/unmount cleanup.

### Third-ring lifecycle scan normalized screen-level periodic refresh ownership

A focused pass over screen-level refresh hotspots normalized timer ownership for Home, Nodes, and the compact local dashboard. DashboardScreen now stores device/hub timers, pauses them on ScreenSuspend, resumes them on ScreenResume, and stops them on unmount. ExplorationScreen now tracks its periodic refresh timer and applies the same pause/resume/stop contract. LocalDashboardScreen now tracks its 5s refresh timer and suspends/resumes/stops it explicitly. This moves the remaining lifecycle debt away from orphaned timers and toward broader worker/subscription cancellation patterns.

### Fourth-ring scan found long-lived dashboard worker ownership gap

A further localized scan shifted from timers to long-lived workers. DashboardScreen's activity subscription worker was previously started on mount/resume without explicit ownership, which allowed duplicate subscription loops across screen transitions and left no suspend/unmount cancellation path. The screen now stores the worker handle, cancels it on ScreenSuspend and unmount, and restarts it on resume using an exclusive `dashboard-activity` worker group. This narrows the remaining lifecycle debt toward other screens with repeated `run_worker()` calls but no explicit in-flight worker ownership semantics.

### Peer workspace scan: MeshDeviceDetail has tractable worker ownership wins and broader migration opportunities

A focused scan of MeshDeviceDetailScreen found an easy lifecycle normalization win: status refresh and device-resolution work were launched via ad hoc `run_worker()` calls from mount, resume-adjacent paths, manual refresh, and post-link flows without explicit ownership. The screen now tracks device-load and status-refresh workers, restarts them through `_start_device_load()` / `_start_status_refresh()` helper methods using exclusive worker groups, and cancels them on ScreenSuspend/unmount. Additional intel from the scan: (1) this screen is a strong candidate for early migration to the eventual StyreneScreen base because it already has a natural `_load_data()` split (`_async_load_device` + `_auto_fetch_status`), (2) link establishment, speedtest, and contact-save actions still use fire-and-forget workers without in-flight ownership semantics, which is acceptable for operator-triggered commands today but remains a future cleanup opportunity, and (3) `_load_device()` still performs synchronous discovery + direct notify during `__init__`, which is a structural gap that should move fully into lifecycle-managed async loading.

### Peer workspace follow-up: removed synchronous device discovery from MeshDeviceDetail initialization

MeshDeviceDetailScreen no longer performs synchronous `discover_devices()` lookup or `notify()` during `__init__`. Initialization now leaves unresolved peers in a loading state (`_device_lookup_complete=False`), composes a LOADING panel for unresolved peers, and resolves them via `_async_load_device()` under lifecycle-managed workers. When live or stored IPC node inventory resolves the peer, the screen recomposes and schedules status refresh after paint; when resolution fails, it transitions to an explicit error state and only then notifies. This removes a key `__init__`-time side effect and makes the screen materially closer to the intended StyreneScreen lifecycle contract.

### NodeInfoPanel scan: low-risk widget-level worker ownership cleanup

NodeInfoPanel was a good low-risk follow-on from the peer workspace work. It already delegated bridge-backed identity and mesh-count refreshes to async coroutines, but `_load_styrene_data()` launched them via bare `run_worker()` calls with no ownership semantics or unmount cleanup. The widget now owns `_identity_worker` and `_mesh_count_worker`, starts them through exclusive helper methods, and cancels them on unmount. Intel from the scan: NodeInfoPanel remains a mixed local/IPC widget (hardware + config local, identity/mesh via bridge), which is workable today but marks it as a future migration hotspot if the project wants a stricter `TUIServices`-only boundary for dashboard state.

### NodeInfoPanel follow-up: local/bridge split and expansion seams are now explicit

NodeInfoPanel's remaining async/sync blending was reduced by separating synchronous local reads from bridge-backed refresh scheduling. `_load_all_data()` now delegates to `_load_local_data()` and `_refresh_bridge_data()`, while `_load_styrene_local_data()` handles config-only state and `_refresh_identity_via_bridge()` / `_refresh_mesh_count_via_bridge()` schedule async work independently. Two explicit integration seams were added for future dashboard/state-model expansion: `_apply_identity_snapshot()` and `_apply_mesh_catalog_count()`, allowing app-level normalized state to be pushed into the widget without invoking worker logic. This keeps the current mixed local/IPC widget workable while making the eventual transition to a stricter shared state model more incremental.

### Architectural direction chosen for NodeInfoPanel: parent-owned state, widget-as-presentation

The preferred expansion path is now explicit: NodeInfoPanel should migrate away from being a mixed local/IPC widget and toward a presentation-only role. DashboardScreen or a small dashboard-state adapter should own bridge access, refresh cadence, and canonical `ui_state` normalization, then push snapshots into the panel through explicit seams. This keeps worker/timer ownership at the screen level, aligns with the broader Screen Lifecycle Contract, and matches the TUI Data State Model decision that normalization belongs above widgets.

### Dashboard now owns the first NodeInfoPanel daemon-state slice

The first implementation step toward the presentation-only NodeInfoPanel boundary is now in place. In IPC-managed Home, NodeInfoPanel no longer schedules its own bridge refreshes; `_refresh_bridge_data()` returns early when `ipc_managed=True`. DashboardScreen now fetches status, identity, hub, config, and live Styrene devices, builds a canonical `LocalDaemonState`, and pushes state into the panel via explicit seams (`_apply_identity_snapshot()` and `_apply_mesh_catalog_count()`) plus direct presentation fields for uptime, transport, and RNS summaries. This moves bridge ownership and refresh cadence upward to the screen while keeping non-IPC/local panel behavior intact.

### Snapshots chosen as the screen-to-widget composability mechanism

The preferred screen/widget boundary is now more specific: parent-owned state should flow into widgets as small panel-scoped snapshots, not just ad hoc direct field assignment. For NodeInfoPanel, DashboardScreen remains responsible for IPC access, refresh timing, retries, and degradation, while the widget consumes a coherent Home summary snapshot. This keeps widget APIs explicit, avoids update-order coupling across many reactive fields, and lets the same summary contract feed other Home surfaces later.

### NodeInfoPanel now has explicit presentation vs fallback refresh modes

The remaining NodeInfoPanel compatibility logic is now structurally separated instead of being interleaved. `_load_all_data()` dispatches to `_refresh_ipc_managed_presentation()` for screen-owned Home presentation mode and `_refresh_local_fallback_mode()` for the historical widget-owned path. The fallback branch further separates synchronous local reads from bridge-backed fallback refresh. This does not remove the compatibility path yet, but it makes the mode split explicit and keeps the IPC-managed Home contract aligned with the screen-owned lifecycle model.

### ProvisionScreen disk detection crash is not superseded by Home/Nodes refactor

Assessment of a user-reported ProvisionScreen traceback shows an active bug outside the current Home/Nodes snapshot refactor. `ProvisionScreen._detect_disks()` still runs disk detection inside a worker, but `styrened.tui.forge.disk_detect._detect_linux()` assumes `lsblk --json` always returns a string model value and calls `dev.get("model", "").strip()`. Real Linux output can return `null` for devices such as `mmcblk0` or `zram`, producing `AttributeError: 'NoneType' object has no attribute 'strip'` inside the worker. This is a data-normalization bug, not a superseded architectural issue. It aligns with the lifecycle contract insofar as worker failures should degrade gracefully, but the immediate defect is in forge disk parsing and needs a defensive normalization fix plus regression coverage.

### ProvisionScreen hotfix: Linux disk detection now normalizes nullable model values

Applied a targeted hotfix for the reported ProvisionScreen worker crash. `styrened.tui.forge.disk_detect._detect_linux()` now normalizes `lsblk --json` `model` values with `(dev.get("model") or "").strip()` before constructing `DiskInfo`, so removable devices with `model: null` or whitespace fall back to `Unknown` instead of raising `AttributeError`. Added regression coverage for both null and whitespace model values and verified `tests/tui/forge/test_disk_detect.py` plus `tests/tui/screens/test_provision.py`.

### ProvisionScreen hotfix prepared for release extraction

The Linux disk-detection hotfix was committed on the active TUI branch as `c441706` with targeted regression coverage and version/changelog updates for `0.15.5`. Releasing it safely now requires extraction onto `main` because the working feature branch carries substantial unrelated in-flight TUI refactor changes.

### Provision disk-detect null-model hotfix released as v0.15.5

The Linux forge disk-detection hotfix was extracted from the active TUI branch onto the latest tagged release line, pushed to `main`, tagged `v0.15.5`, and published to PyPI. Verification for the release slice used `tests/tui/forge/test_disk_detect.py` and `tests/tui/screens/test_provision.py` (35 passing). This preserves the ongoing workspace-architecture refactor branch while shipping the user-visible crash fix immediately.

### NodeInfoPanel fallback path now also flows through a local snapshot builder

The remaining non-IPC compatibility path in NodeInfoPanel was tightened further without changing user-visible behavior. `_load_local_fallback_state()` no longer mutates hardware/config fields ad hoc; it now builds a coherent `HomeNodeLocalState` via `_build_local_fallback_snapshot()` and applies that snapshot before loading local Reticulum state. The fallback path still exists in the same class, but local compatibility behavior is now structurally closer to the IPC-managed Home presentation contract: both modes flow through explicit snapshot application rather than interleaved field mutation.

### NodeInfoPanel compatibility loader is now isolated behind a fallback builder helper

The remaining widget-owned compatibility path in `NodeInfoPanel` now has a single explicit helper boundary. A private `_NodeInfoPanelFallbackStateBuilder` owns local hardware/config reads and construction of `HomeNodeLocalState` for non-IPC mode, while the panel itself applies snapshots and owns only presentation state plus bridge worker lifecycles. This puts a cleaner bow on the migration: IPC-managed Home is presentation-only, and the legacy fallback path is visibly boxed off as a compatibility helper instead of being spread through the widget body.

### Cleanup/security pass found two concrete hardening fixes in Home panel paths

A focused cleanup and security-style pass over the recent Home/Nodes/NodeInfoPanel slice did not reveal obvious injection or path/process safety issues, but it did surface two concrete robustness gaps worth fixing immediately. First, `NodeInfoPanel._apply_identity_snapshot()` previously called `load_config()` without a guard, so a local config-read failure could break snapshot application from the parent screen; it now defaults safely to the file-backed/X25519 tier when config loading fails. Second, `DashboardScreen._fetch_daemon_status()` launched multiple concurrent IPC tasks and could return early on a core-status failure without cancelling the remaining background requests; it now cancels and drains pending tasks in a `finally` block to avoid orphaned background work during degraded Home refreshes.

### Next outward lifecycle pass tightened Nodes and peer-workspace worker ownership

A focused pass over `ExplorationScreen` and `MeshDeviceDetailScreen` found two more small but worthwhile ownership gaps. `ExplorationScreen` already tracked its periodic refresh timer, but it still launched node-refresh and deferred stored-node hydration via untracked `run_worker()` calls; it now owns `_node_refresh_worker` and `_stored_nodes_worker`, routes refreshes through explicit helper methods, and cancels those workers on ScreenSuspend/unmount before restarting refresh on resume. `MeshDeviceDetailScreen` already owned device-load and status-refresh workers, but operator-triggered direct-link, speedtest, and contact-save actions were still fire-and-forget; the screen now tracks those action workers too, starts them through exclusive helper methods, and clears them through the same suspend/unmount cleanup path so repeated keypresses and navigation transitions do not leave overlapping background jobs running against an inactive peer workspace.

### Full-suite run is currently blocked at collection by three perimeter issues outside the recent TUI communication slice

A full `pytest -q` run on the current TUI branch did not reach execution because collection stops on three independent perimeter failures. First, `tests/k8s/conftest.py` now conflicts on `--run-slow` option registration, which blocks all k8s collection before any scenario tests run. Second, `tests/mesh/test_conversation.py` imports `poll_for_status` from `tests.mesh.conftest`, but that symbol is no longer present, indicating a mesh-test harness drift issue. Third, `tests/tui/services/test_ipc_bridge.py` still imports private shim-era symbols such as `_MAX_RECONNECT_ATTEMPTS` from `styrened.tui.services.ipc_bridge`, but the compat shim no longer exports them after the IPCBridge relocation. These failures define the next outward perimeter: repository-level test harness reconciliation, then legacy compat-test updates, then broader behavioral execution once collection is unblocked.

### Collection blockers reconciled for k8s, mesh, and IPC bridge compat coverage

The first full-suite perimeter blockers have been reconciled locally. `tests/k8s/conftest.py` now registers `--run-slow` idempotently so mixed subtree collection no longer fails when another suite already defined the shared option. `tests/mesh/conftest.py` now re-exports `poll_for_status` from the shared harness helpers so `tests/mesh/test_conversation.py` collects again. `tests/tui/services/test_ipc_bridge.py` was updated to target `styrened.ipc.bridge` directly instead of the deprecated TUI shim's private internals, restoring alignment between compat-era tests and the current public implementation boundary.

### Bare-metal suites now degrade when lab hostnames are unavailable locally

After unblocking collection, the next whole-suite footprint was bare-metal execution failing immediately on unresolved `device-*.local` SSH targets. The test registry/conftest path now filters unresolved lab hosts up front, and the SSH harness excludes unresolvable devices when loading `tests/bare-metal/devices.yaml`. This preserves explicit bare-metal coverage when the lab is reachable, but makes generic laptop/full-suite runs degrade to skips instead of failing the entire suite before reaching broader software-only coverage.

### Legacy bare-metal mesh scenarios are now skipped when their named lab pair is absent

A second bare-metal footprint appeared after unresolved-host filtering: older bare-metal mesh/scenario tests still assume a specific legacy pair (`styrene-node` and `t100ta`) and an older `discover_devices(wait=...)` keyword. The SSH harness now accepts `wait` as a backward-compatible alias, and the legacy mesh/scenario suites explicitly skip when that named pair is not present in the currently loaded lab registry. This keeps those historical scenarios runnable in the intended lab while preventing generic full-suite runs from failing on stale environment assumptions.

### Next post-bare-metal perimeter is mostly stale test-contract drift, not new TUI architecture fallout

Once collection and environment-gated bare-metal suites were reconciled, the next revealed failures were largely stale test assumptions in adjacent integration layers: IPC integration mocks were feeding unserializable `MagicMock` enum values, config API tests were asserting an exact pre-expansion section set instead of a stable subset, and k8s scenarios still expected a subprocess-style `returncode` field even though the harness standardizes on `return_code`. Adding a compatibility alias on `CommandResult` and updating stale expectations/mocks shifts the remaining perimeter away from compatibility drift and toward any true behavioral regressions that survive after those adjustments.

### After harness and compat cleanup, the next whole-suite perimeter is a real k8s LXMF discovery/send behavior failure

With collection fixed, bare-metal suites degraded appropriately, and stale integration/compat tests reconciled, the next revealed failure is no longer a harness-contract issue but an actual k8s scenario behavior gap. `tests/k8s/scenarios/test_e2e_integration.py::TestLXMFMessagePassing::test_peer_to_peer_message_delivery` now reaches runtime and fails because Pod A waits for Pod B's destination hash to announce, but the test currently extracts Pod B's operator identity hash (`identity.hash.hex()`) rather than the announced LXMF destination seen by `styrened send`. Logs show Pod A discovering a different announced destination (`lxmf_dest=...`) while the CLI waits unsuccessfully for the identity hash. This suggests the scenario is mixing identity hash and sendable LXMF destination semantics; the next cleanup pass should inspect the intended CLI contract and update the scenario to use the correct destination identifier before re-running broader k8s smoke coverage.

### K8s smoke failure narrowed further: standalone pod A only discovers itself, so the scenario is likely invalid at the topology assumption level

Further narrowing on `tests/k8s/scenarios/test_e2e_integration.py::TestLXMFMessagePassing::test_peer_to_peer_message_delivery` shows the issue is deeper than just choosing identity hash versus LXMF destination hash. Even after extending startup/discovery waits substantially, `styrened devices -w 60 --json` inside Pod A only reports Pod A itself; Pod B never appears in discovery from Pod A's view. That means the current smoke scenario's assumption that two `mode="standalone"` pods will discover each other quickly in this k8s topology is likely invalid or under-provisioned. The next pass should inspect the `styrened_stack`/Helm defaults and decide whether this test should (a) use a hub/peer topology for deterministic discovery, (b) explicitly seed peer endpoints, or (c) switch from CLI-process discovery to daemon-side observable state if the standalone sidecar process is the wrong vantage point.

### Next revealed non-k8s perimeter after environment gating is a flaky TUI integration harness path, not core Home/Nodes logic

After degrading Docker-dependent mesh suites and absent-SSH lab scenarios to skips, a broader `pytest -x -q -k 'not k8s'` run now reaches a TUI integration failure in `tests/tui/integration/test_chat_dashboard_flow.py`. The failing surface is not the Home/Nodes workspace semantics directly; it is the integration harness path that boots a full `StyreneApp` under `run_test()` with partially mocked lifecycle startup. The current failure mode is Textual `HeaderTitle` lookup / screen-startup instability during app mount, plus earlier test assumptions that relied on implicit tree selection and non-hex peer hashes. Targeted fixes already updated the fixture data to valid hex hashes and made the chat-flow tests explicitly select a node before opening detail. The remaining failure appears to need either a stronger async lifecycle stub for `StyreneApp` startup or a tighter test boundary that pushes deterministic screens directly instead of relying on the full app bootstrap path.

### Non-k8s perimeter moved past bootstrap/header-era chat/dashboard tests

Stabilized additional TUI test rings by updating stale full-app assumptions to current screen/service boundaries. In `tests/tui/screens/test_chat_edge_cases.py` and `tests/tui/screens/test_dashboard_chat_integration.py`, app bootstrap is now stubbed through `styrened.tui.app.StyreneLifecycle` and `styrened.tui.app.find_reticulum_config` (not just service-layer imports), dashboard/device-detail navigation uses deterministic `MeshDeviceTree._select_by_identity(...)` or direct action invocation instead of brittle key-driven tree traversal, and dashboard chat-indicator expectations were aligned to the current projection contract where OTHER nodes remain anonymized by default even when unread metadata exists.

### Scenario-matrix SSH perimeter now degrades when registered lab nodes are unreachable

The broader non-k8s sweep revealed another environment-shaped perimeter outside core TUI logic: `tests/scenarios/test_matrix.py` connectivity cases could still hard-fail when a named lab node was present in the loaded SSH registry but unreachable from the current machine (for example, timeout to `t100ta`). The matrix suite now applies the same environment-degradation principle used elsewhere: connectivity tests first reuse `_require_registered_ssh_nodes(...)`, and named lab-node connectivity failures with transport-style errors (timeout, connection refused, no route, host down, etc.) skip with an explicit 'not reachable from this environment' message instead of failing the whole non-k8s pass.

### Non-k8s perimeter now mostly reflects stale test contracts outside core widget semantics

Continuing the post-bootstrap sweep surfaced a series of stale test-contract assumptions rather than new lifecycle regressions. Updated tests to align with current behavior in several adjacent areas: `tests/tui/services/test_app_lifecycle.py` now patches `styrened.ipc.bridge.IPCBridge` (matching the live import path), `tests/tui/services/test_config_persistence.py` now treats reticulum/api state as core-config-backed and expects the current well-known hub set, `tests/tui/services/test_node_store.py` expects the expanded node schema (discovered_via/hops/nomadnet/ygg/b32 fields), `tests/tui/services/test_rpc_server.py` replay coverage now explicitly authorizes the source so the test exercises replay protection instead of RBAC denial, `tests/tui/test_dashboard_app.py` supplies newly required CLI args, `tests/tui/widgets/test_chat_widget.py` stubs the app-level lifecycle/bootstrap path and matches the current retry fallback semantics, and `tests/tui/widgets/test_micron_parser.py` now accepts styled heading markup that includes theme color tokens in addition to bold/italic tags.

### Services/widgets/unit tranche now green; remaining debt is warning-tier coroutine cleanup

The broad post-screen sweep over `tests/tui/services`, `tests/tui/widgets`, `tests/tui/test_dashboard_app.py`, `tests/tui/test_navigation_workflows.py`, and `tests/unit` now completes successfully: 3872 passed, 18 skipped. The remaining signal from this tranche is warning-tier lifecycle debt rather than hard failures. Current warnings cluster around un-awaited coroutine scheduling in tests or teardown paths (for example `DaemonManager._monitor_health`, `ChatWidget._stage_attachment_from_path`, `PageBrowserWidget._load_page`, `AutoReplyHandler._async_chatbot_reply`, terminal PTY/idle loops, and `_bootstrap_ygg_peer`). Separately, several micron-render tests were stale because rich markup now includes themed color tokens; those expectations were relaxed to assert semantic style prefixes (`[bold`, `[dim`, `[underline`) rather than exact colorless tags.

### Parallelized non-k8s screen-tail strategy

To avoid another monolithic `-k 'not k8s'` timeout in the remaining TUI screen-heavy tail, the non-k8s screen slice is being split into parallelizable pytest streams by surface affinity and approximate test count. Current file counts from `--collect-only -q`: settings(27), provision(18), daemon_setup(9), dashboard_tui(31), device_detail_tui(35), exploration(28), contacts(15), inbox(11), inbox_navigation(11), conversation(10), conversation_lifecycle(10), chat_edge_cases(9), dashboard_chat_integration(6), group_forum_placeholders(6), comms(2), confirm_flash(2). Proposed parallel streams: (A) settings/provision/daemon-setup, (B) dashboard + device-detail, (C) exploration/contacts/comms/confirm-flash, (D) conversation + inbox + compatibility/chat-edge surfaces. This should expose the next real failure faster while preserving workspace-local debugging context per stream.

### Parallel screen-tail execution validated across four streams

The non-k8s TUI screen-heavy tail was successfully decomposed into four parallel pytest streams and exercised independently. Results: (A) settings/provision/daemon-setup = green after isolating `test_settings_tui.py` and fixing stale IPC bootstrap mocks for bridge-backed save/generate-page tests (`27 passed` for settings; `27 passed` for provision+daemon-setup), (B) dashboard/device-detail/dashboard-chat = `72 passed`, (C) exploration/contacts/comms/confirm-flash = `47 passed`, and (D) conversation/inbox/chat-edge/group-forum = `57 passed`. This confirms the remaining screen-heavy tail is no longer a single opaque timeout blob; it can be run as balanced, parallelizable streams to expose future failures quickly.

### StyreneScreen base class implemented — consolidation checkpoint

All pre-screen-overhaul scaffolding is now in place (commit 8ca0070, branch feature/tui-workspace-architecture):\n\n**StyreneScreen base class** (`src/styrened/tui/screens/base.py`):\n- Abstract `_load_data()` — subclasses implement, base handles when/how\n- Optional hooks: `_cleanup()`, `_on_error(error, attempt)`, `_loading_message() -> str`\n- `self.bridge` property — returns `IPCBridge`, raises `BridgeUnavailableError` if None\n- 3-attempt exponential-backoff retry (0.5s / 1s / 2s)\n- `StyreneLoadingIndicator` shown before first load, hidden after\n- Stale data preserved on error (no blank screen)\n- Worker ownership: suspend cancels `_load_worker`, unmount cancels + cleanup\n- `on_mount` and `on_screen_resume` both call `_start_load()` (always refresh on re-entry)\n- All lifecycle events logged at DEBUG with screen class name + attempt count\n- 11 tests in `tests/tui/screens/test_screen_base.py`, all green\n\n**WorkspaceId** (`src/styrened/ui_state/workspace.py`): HOME/NODES/MAIL/COMMS/CONTACTS/ADMIN\n\n**app.py hardening**: `action_open_admin()` added, `grave_accent`→`open_admin` binding, `action_open_mail` uses `self.services.bridge` not `self._lifecycle.ipc_bridge`, `action_push_screen_settings` kept as backward-compat alias\n\n**Test mocks**: 6 test files updated from `get_node_store` daemon patches to `bridge.get_nodes()` bridge patches\n\n**Next step**: Begin screen-by-screen migration to `StyreneScreen`. Recommended order:\n1. `ExplorationScreen` (Nodes workspace) — clear `_load_data()` split already exists\n2. `InboxScreen` / `MailScreen` — has `on_screen_resume` already, straightforward\n3. `ContactsScreen` — small, low risk\n4. `MeshDeviceDetailScreen` (peer workspace) — most complex, do last\n5. `DashboardScreen` (Home) — large but well-understood after NodeInfoPanel work\n6. `SettingsScreen` — largest (1264 LOC), split into sub-screens as part of migration"

## Decisions

### Decision: StyreneScreen base class with enforced lifecycle contract

**Status:** decided
**Rationale:** All 13 screens are internal to our TUI — no third-party consumers. A base class (StyreneScreen extends Screen) provides: enforced `_load_data()` coroutine that subclasses implement, automatic worker management for mount/resume/suspend/unmount, centralized error handling with retry+notify, and loading indicator orchestration. Screens declare *what* to load; the base handles *when* and *how*."

### Decision: StyreneLoadingIndicator subclass of Textual LoadingIndicator

**Status:** decided
**Rationale:** Follow the StyreneScreen pattern — subclass Textual's LoadingIndicator as StyreneLoadingIndicator. Allows theming with the imperial CRT cascade, consistent styling, and future customization (e.g. showing what's being loaded, retry count). Base class manages show/hide: compose yields the indicator, on_mount shows it before kicking off _load_data worker, worker hides it on completion or replaces with error state on failure."

### Decision: Graceful degradation: auto-retry with notification and thorough logging

**Status:** decided
**Rationale:** On IPC failure: (1) log the full error with context (screen name, IPC command, attempt count, traceback) to the internal logging system — these logs feed future debugging. (2) Auto-retry with exponential backoff (e.g. 1s, 2s, 4s, max 3 attempts). (3) If data was previously loaded, keep showing stale data with a visual staleness indicator. (4) After max retries, notify the user via app.notify() with a concise message. (5) Screen remains functional with whatever data it has — never blank, never crashed. The internal logging pipeline captures all failures for post-hoc analysis."

### Decision: Centralized app-level staleness timer + full refresh on resume + experimental debug mode

**Status:** decided
**Rationale:** Three-layer refresh strategy: (1) **on_screen_resume always calls _load_data()** — user explicitly navigated back, the 5-25ms IPC cost is invisible in a transition, and it guarantees fresh data on every screen entry. (2) **Single app-level timer** invalidates the active screen periodically — only the visible screen refreshes, suspended screens get zero overhead. Timer interval is TUIMode-aware (OPERATOR=30s, FLEET=15s, FIELD=120s, KIOSK=60s). Timer pauses on app suspend. (3) **`tui.debug_refresh: true`** experimental flag forces full _load_data on every timer tick with verbose logging — diagnostic tool for stale-data bugs and CI validation, not default behavior. This keeps edge device footprint minimal (1 timer, 1 active screen refreshing) while giving us a proper debug path. Push-based daemon events are a future optimization that doesn't need to gate this work."

### Decision: Full StyreneScreen API: _load_data, _cleanup, _on_error, _loading_message — all with robust logging

**Status:** decided
**Rationale:** Expose all four hooks as overridable methods with robust logging in the base implementation. `_load_data()` (required) — async coroutine, fetches screen data via IPC. `_cleanup()` (optional) — called on suspend/unmount, cancels screen-specific resources. `_on_error(error, context)` (optional) — called on IPC failure after retry exhaustion, default shows notification. `_loading_message()` (optional) — returns string for StyreneLoadingIndicator, default is screen-appropriate. Every hook logs entry/exit/duration/errors at DEBUG level in the base. Errors log full context (screen class, method, attempt count, traceback) at WARNING/ERROR. The internal logging pipeline captures everything for post-hoc debugging."

### Decision: self.bridge convenience property on StyreneScreen — delegates to TUIServices with None guard

**Status:** decided
**Rationale:** No security implications — the bridge is already accessible via self.app.services.bridge from every screen. The property is syntactic sugar, not a privilege escalation. Security enforcement is daemon-side (RBAC on every IPC handler, Unix socket filesystem permissions). The property adds a None guard: if bridge is unavailable (daemon disconnected), raises BridgeUnavailableError which the base class _on_error handler catches and feeds into the retry/notify/degrade pipeline. This is a robustness concern, not a security one."

### Decision: NodeInfoPanel should become a presentation widget fed by parent-owned canonical state, not a bridge-owning mixed data loader

**Status:** decided
**Rationale:** Option B is the correct boundary. NodeInfoPanel currently mixes synchronous local reads with bridge-backed refreshes, which keeps widget lifecycle and data authority tangled. The widget should instead render parent-provided canonical state snapshots, with DashboardScreen or a thin adapter owning refresh timing, IPC access, and normalization through ui_state builders. The new `_apply_identity_snapshot()` and `_apply_mesh_catalog_count()` seams support an incremental migration by letting parent-owned state flow into the widget before all direct fetch logic is removed.

## Open Questions

*No open questions.*
