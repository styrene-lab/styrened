---
id: tui-pages-browser-ipc-head-of-line-blocking
title: Pages browser IPC head-of-line blocking
status: exploring
parent: tui-startup-ipc-backpressure
tags: [tui, pages, ipc, bug]
open_questions: []
openspec_change: tui-pages-browser-ipc-isolation
issue_type: bug
priority: 1
---

# Pages browser IPC head-of-line blocking

## Overview

The Exploration Pages tab still feels laggy on large meshes because page fetches run over the same shared IPC bridge used for summary/status work. A slow or timing-out NomadNet page request can monopolize the client connection and the daemon's per-client request loop, delaying unrelated UI requests and making the whole TUI feel stuck while a single page load is in flight.

## Research

### Live probing shows slow page fetches still monopolize the shared IPC lane

Direct probing against the dev daemon showed that the visible lag is not primarily in Exploration table rebuilds. Mounting Exploration with ~9.6k live devices and rebuilding all five tables in a headless Textual harness remained sub-second, and individual table `load_from_devices()` calls were on the order of 1–9 ms. By contrast, live `fetch_page('/page/index.mu')` calls for NomadNet nodes varied from ~0.01–1.22 s for warm/healthy active nodes, ~1.4–4.7 s for some stale-but-reachable nodes, and a full 30 s `link_failed`/timeout path for stale endpoints. While one slow `fetch_page` was in flight on the shared `IPCBridge`, an unrelated `get_status()` call issued on the same bridge took ~11.8 s to complete behind it, confirming head-of-line blocking on the shared client/server path rather than a pure rendering bottleneck.

### The IPC server currently dispatches requests sequentially per client connection

`ControlServer._handle_client()` awaits each handler and only sends the response before reading/dispatching the next request on that client. That means a long-lived `QUERY_PAGE` handler effectively blocks later requests arriving on the same socket, even though the client protocol supports multiple pending request IDs. A second `IPCBridge` connection remained responsive during the same slow page fetch, which suggests the immediate operator-visible problem is traffic-class sharing on one client connection.

### Dedicated execution lane prototype preserves control responsiveness in live probing

Implementation now uses `IPCBridge.spawn_lane('execution')` so `PageBrowserWidget` lazily creates a sibling bridge only when page work starts. A live probe against the dev daemon confirmed the intended behavior: while a stale-node page fetch continued for ~20.4 s on the execution lane, a control-lane `get_status()` returned immediately instead of queueing behind the page request.

### Unawaited coroutine warning came from eager coroutine creation before mocked run_worker calls

The remaining pytest warning was not another IPC regression. `PageBrowserWidget` was passing bare coroutine objects like `self._load_page(path)` directly into `run_worker(...)`. That is valid in production, but unit tests often patch `run_worker` with a plain mock, which means the coroutine object is created and never consumed. Refactoring the widget to pass the async callable (or `functools.partial`) into `run_worker` preserved runtime behavior and removed the warning across the broader 241-test batch.

### Implementation slice archived to OpenSpec baseline

The implementation change `tui-pages-browser-ipc-isolation` has been archived and merged into `openspec/baseline/tui/pages-browser-ipc.md`. No active OpenSpec changes remain. The design-tree node itself is still gated from `set_status(decided)` by the explicit `/assess design` requirement enforced by the design-tree workflow.

## Decisions

### Decision: Interactive page loads must not monopolize the shared control plane

**Status:** decided
**Rationale:** Home/status/device-cache traffic and operator actions such as navigation should stay responsive while a page fetch establishes an RNS link or times out. The remaining question is the narrow implementation mechanism—dedicated page bridge versus server-side concurrency—not whether latency isolation is needed for page browsing at all.

### Decision: Prefer a dedicated page-browsing IPC bridge before changing server-wide dispatch semantics

**Status:** decided
**Rationale:** Live probing showed that a second IPC connection stays responsive while a slow page fetch is in flight, which means the operator-visible stall can be resolved by isolating PageBrowserWidget traffic without immediately widening daemon-wide concurrency semantics. A dedicated page bridge/client has a smaller blast radius than changing ControlServer request scheduling for every IPC consumer, and it aligns with the earlier startup work: keep default startup demand lean, then isolate long-lived operator-driven traffic classes only where evidence shows it is necessary.

### Decision: Keep IPC traffic classes separated so QoS emerges from lane isolation rather than priority hacks

**Status:** decided
**Rationale:** We should keep tracking the earlier triplet split: fast control/command requests, bulk data hydration, and long-running interactive execution flows. The exact labels can evolve, but the property we need is separation of concern and isolation of latency. Page browsing belongs in the long-running lane so status, navigation, and critical commands remain responsive without inventing ad-hoc request priorities on a shared socket.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/page_browser.py` (modified) — Potentially isolate page loads onto a dedicated IPC client/bridge and surface cache/timeout state without freezing other UI actions.
- `src/styrened/ipc/server.py` (modified) — If the fix is server-side, revisit per-client sequential dispatch so long-running handlers do not block later control requests on the same socket.
- `src/styrened/ipc/bridge.py` (modified) — Potential home for an auxiliary page-browsing bridge or explicit traffic-class abstraction if the TUI isolates page fetches client-side.
- `tests/tui/widgets/test_page_browser.py` (modified) — Add regressions proving slow page fetches do not stall unrelated control-plane work or at least fail fast with truthful operator feedback.
- `src/styrened/ipc/bridge.py` (modified) — Added lane-cloning support (`spawn_lane`) and traffic-class metadata so the page browser can isolate long-running work onto an execution lane.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Page browsing now lazily creates and reuses a dedicated execution IPC lane for fetches, form submits, save-site, and crawl-site operations, and disconnects it on unmount.
- `tests/tui/services/test_ipc_bridge.py` (modified) — Covers sibling lane spawning and traffic-class propagation.
- `tests/tui/widgets/test_page_browser.py` (modified) — Covers dedicated execution-lane creation, preference over the shared bridge, and safe cleanup behavior.

### Constraints

- Do not reintroduce screen-owned fleet caches just to mask page latency.
- Keep daemon liveness and page-fetch backpressure distinct in operator-facing status.
- Prefer isolating long-lived page requests without increasing baseline startup demand on constrained hardware.
- Keep the shared app bridge as the control lane; page isolation must remain lazy so startup demand does not grow.
- A slow page fetch should be allowed to remain slow, but it must no longer monopolize the normal control/status lane.

## Acceptance Criteria

### Falsifiability

- This decision is wrong if: If a slow `fetch_page()` still delays unrelated status/control requests issued through the normal shared bridge, this design has failed.
- This decision is wrong if: If the fix requires broad server-wide request-scheduling changes to recover responsiveness for Pages browsing, the smaller-blast-radius client-side isolation decision was wrong or incomplete.
- This decision is wrong if: If the solution adds startup IPC demand or reintroduces screen-owned caches just to hide page latency, it violates the design intent.
