---
id: screen-lifecycle
title: Screen Lifecycle Contract
status: decided
parent: tui-specification
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

## Open Questions

*No open questions.*
