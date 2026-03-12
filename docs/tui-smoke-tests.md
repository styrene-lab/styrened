---
id: tui-smoke-tests
title: TUI Automated Smoke Tests — First-Operator Coverage
status: decided
parent: pre-release-qa-gate
tags: [tui, testing, smoke, textual, pilot, qa]
open_questions: []
---

# TUI Automated Smoke Tests — First-Operator Coverage

## Overview

Automated Textual Pilot tests that simulate the first-time operator experience for each major screen. Complement to operator visual review — catch crashes, missing widgets, and broken navigation before the human ever looks at the TUI. Run as part of `just test-tui` and as a blocking step in the CI smoke tier. Cover: app startup, screen mounting, tab navigation, key widget presence, basic interactions (send a message, open settings, navigate to a peer). Not a visual diff tool — a structural correctness check.

## Research

### Textual Pilot API capabilities

Textual ships `textual.testing.Pilot` for async test automation. Key methods:
- `app.run_test()` — async context manager that mounts the app and yields a Pilot
- `pilot.press(key)` — fire a key event
- `pilot.click(selector)` — click a widget by CSS selector
- `app.query_one(selector)` — assert widget exists and is visible
- `app.screen` — access current screen
- `app.screen_stack` — inspect navigation state

Limitations:
- Cannot render to a real terminal — Textual uses a headless compositor
- Layout reflow at specific terminal sizes not testable
- Theme color cascade not exercised
- IPC bridge must be mocked (or a real daemon socket provided)

Pattern for IPC mock: inject a mock `TUIServices` protocol implementation via `StyreneApp(services=MockServices())` — already possible since TUIServices is a Protocol. No daemon needed for structural smoke tests.

### First-operator interaction model

What a first-time operator does in the first 5 minutes:
1. Launch `styrene` — sees Home screen with daemon starting
2. Check node info panel — own identity hash, daemon status, version
3. Navigate to Nodes tab — see device list (empty or with local node)
4. Navigate to Comms — see direct link / overlay status
5. Open Settings — check Network tab, set a peer, save
6. Navigate to Mail/Inbox — empty state, compose button present
7. Open doctor / run diagnostics (via `styrened doctor`)
8. Back to Home — activity feed shows startup events

The smoke tests should cover steps 1-6: app mounts, Home screen renders, each top-level tab is reachable, Settings opens and key panels exist, Inbox renders empty state. Steps 7-8 are daemon-dependent and belong in integration tests.

### IPC coverage gap — the critical missing path

**39 IPC commands defined in ipc/protocol.py. 2 tested against real daemon behavior.**

Current test landscape:
- `tests/integration/test_ipc_integration.py` (505 lines) — uses a `MagicMock()` daemon, not `StyreneDaemon`. Tests socket framing and client/server mechanics but not handler correctness.
- `tests/tui/integration/` (4 files) — tests TUI↔IPC socket lifecycle but also mocks the daemon.
- `tests/tui/e2e/` (3 files) — requires real brutus cluster network. Not runnable locally.
- `tests/integration/test_terminal_integration.py` — starts a real `StyreneDaemon` but only exercises `_terminal_service` attribute presence.

**Commands with zero real-daemon test coverage (37/39):**
- All QUERY_* commands (QUERY_DEVICES, QUERY_STATUS, QUERY_CONFIG, QUERY_CONVERSATIONS, etc.)
- All CMD_* write commands (CMD_SEND, CMD_SEND_CHAT, CMD_SET_CONTACT, SAVE_CORE_CONFIG, etc.)
- All SUB_* subscription commands
- All EVENT_* events
- All DATALINK_* commands
- GET_NODES, GET_CORE_CONFIG, GET_HUB_STATUS

**Consequence:** The IPC contract between daemon handlers and TUI consumers is verified only by type annotations and human inspection. Shape mismatches (missing keys, wrong types, None vs empty list) only surface at runtime when a user runs the TUI against a real daemon. This is the root cause of bugs found in the adversarial review (e.g., _device_info_to_mesh treating DeviceInfo as dict).

## Decisions

### Decision: Three-tier testing architecture: mock smoke / daemon contract / real-daemon TUI

**Status:** decided
**Rationale:** Tier 1 — Mock-services TUI smoke (tests/tui/smoke/): Textual Pilot + MockTUIServices, no daemon, fast (&lt;5s), runs on every PR. Catches structural regressions: screen mounts, widget presence, tab navigation, empty states. Tier 2 — Daemon IPC contract (tests/integration/test_ipc_contract.py): real StyreneDaemon (minimal config, no RNS), real IPCBridge, real socket. Covers all 39 IPC commands — currently 37 have zero real-daemon coverage. This is the critical missing layer. Module-scoped fixture so daemon starts once per file. Tier 3 — Daemon-connected TUI integration (tests/tui/integration/, existing): real daemon socket + Textual Pilot, no mocks. Slower, used for pre-release CI gate. Complements the visual operator review, doesn&apos;t replace it.

### Decision: Mock smoke tests live at tests/tui/smoke/, marked @pytest.mark.smoke

**Status:** decided
**Rationale:** Isolated from the 30-second IPC integration tests in tests/tui/integration/. `pytest tests/tui/smoke/` is a clean targeted command. Marker `@pytest.mark.smoke` allows `just test-tui` to include them without breaking the fast unit run. The smoke directory contains one file per major screen/flow: test_home_smoke.py, test_nodes_smoke.py, test_comms_smoke.py, test_settings_smoke.py, test_inbox_smoke.py, test_navigation_smoke.py.

## Open Questions

*No open questions.*
