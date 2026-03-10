---
id: tui-specification
title: Styrene TUI Specification
status: exploring
tags: [tui, ux, specification, textual]
open_questions: []
---

# Styrene TUI Specification

## Overview

Define a comprehensive specification for the styrene TUI — screens, navigation, keybindings, data flow, theming, and interaction patterns. The TUI is ~23K LOC built on Textual with no formal spec. Recent backend additions (RBAC, relay, /meta, /info, block/ban, cross-enclave features) need UI surfaces.

## Research

### Current TUI Inventory

**~23K LOC**, built on Textual (Python), with `imperial_crt.tcss` theme and color cascade system.

**13 Screens:**
- `DashboardScreen` — Main fleet overview. MeshDeviceTree split into MY MESH (RBAC ≥ PEER) vs OTHER. Activity feed. Node info panel. Auto-queries /meta on unknown nodes.
- `DashboardLocalScreen` — Compact single-column local device status.
- `InboxScreen` — Conversation list for LXMF chat messages. Search, sort, sync, compose.
- `ConversationScreen` — Message thread for a single chat conversation.
- `ContactsScreen` — Manage contact aliases for mesh peers. Add/edit/delete/block.
- `MeshDeviceDetailScreen` — Tabbed peer detail: status, chat, RPC commands, terminal (PTY-over-RNS), page browser.
- `ExplorationScreen` — Reticulum network discovery.
- `SettingsScreen` — Configuration management (1264 LOC).
- `ProvisionScreen` — Edge device forge pipeline (disk detect → nix build → flash).
- `FirstRunWizardScreen` — Reticulum setup wizard.
- `DaemonSetupScreen` — Guides through starting/installing styrened.
- `UpgradeScreen` — Modal for upgrade confirmation.
- `ConfirmFlash` — Modal for destructive flash confirmation.

**15+ Widgets:** chat, command, terminal, device status, node info panel, page browser, micron parser, activity feed, config form, hardware panel, uptime panel, etc.

**Services:** IPC bridge (706 LOC), config, daemon manager, fleet, reticulum, hardware, changelog, update checker, app lifecycle, service installer.

**Forge subsystem:** disk detection, nix build, media writer, bundle builder (for edge device provisioning).

**Navigation:** Global keybindings from app (?, `, i, b, p, a, ctrl+r, ctrl+c). Screen-level bindings vary per context.

**Missing UI for recent backend work:**
- RBAC management (view/edit roster, assign roles, grant capabilities)
- Relay status/management (active sessions, teardown)
- Cross-enclave features (clipboard, discovery)
- /meta and /info introspection (partially wired in dashboard)
- Block/ban (partially wired — ContactsScreen has block action)

### Structural Audit — Foundational Issues



### 1. Data Access Split-Brain (Critical)

The TUI has **two competing data paths** and uses them inconsistently:
- **IPC bridge** (27 calls from screens) — async calls to daemon via Unix socket. The intended architecture.
- **Direct service imports** (42 calls from screens) — `load_core_config()`, `get_node_store()`, `hub_connection()`, `_deduplicate_by_identity()`. These bypass the daemon, access files/DBs directly, and couple the TUI to daemon internals.

The direct path outnumbers IPC 42:27. Dashboard alone calls `load_core_config()` 4 times and `get_node_store()` 2 times. This means the TUI cannot run as a standalone client — it must share the same filesystem as the daemon, defeating the IPC architecture.

### 2. Implicit App Contract (`type: ignore` everywhere)

Every screen and widget accesses `self.app._lifecycle.ipc_bridge` with `# type: ignore[attr-defined]`. This means:
- No typed interface between screens and the app
- Screens reach deep into private attributes (`app._lifecycle`, `app._check_for_updates`, `app.db_engine`, `app.rpc_client`, `app.chat_protocol`)
- The "API" is whatever attributes StyreneApp happens to have
- Each screen duplicates the same `@property def _bridge` → `self.app._lifecycle.ipc_bridge` boilerplate

### 3. Database Engine Leak Into UI Layer

`app.db_engine` (SQLAlchemy Engine) is passed directly to screens and widgets. The dashboard creates SQLAlchemy `Session` objects directly. `node_info_panel.py` runs raw SQL queries via the engine. The TUI is acting as a database client rather than going through a service layer.

### 4. CSS Architecture Fragmented

- 1 central TCSS file (1076 lines: `imperial_crt.tcss`)
- 22 `DEFAULT_CSS` blocks scattered across widgets/screens
- No clear ownership of which styles live where
- Color cascade system exists (`color_cascade.py`, 513 LOC) but unclear when to use cascade vs TCSS vs DEFAULT_CSS

### 5. Keybinding Conflicts

Multiple keys bound to different actions across screens with no disambiguation strategy:
- `r` bound 6 times (refresh, resolve_name, refresh_disks, refresh_status)
- `a` bound 3 times (announce, add_contact)
- `c` bound 3 times (open_chat)
- `enter` bound 4 times, `escape` 9 times

Textual's binding resolution handles this by screen stack priority, but there's no documented keymap contract. Users hitting `r` get different behavior depending on invisible screen stack state.

### 6. Error Handling Inconsistency

258 try/except blocks across screens, 32 of which are bare `except Exception`. No consistent error surface — some errors are logged, some shown via `self.app.notify()`, some silently swallowed.

### 7. Legacy Mode Still Present

`LifecycleMode.LEGACY` allows the TUI to run its own RNS/LXMF stack directly (not via daemon). This doubles the initialization paths, creates conditional branches throughout lifecycle code, and means the TUI can operate in a mode that bypasses all the RBAC/relay/security work we just did. It's architectural debt from before the daemon existed.

### 8. Low Test Coverage for UI Logic

79 test files exist under `tests/tui/` but many are integration tests requiring a running daemon (30s socket timeouts). The CLAUDE.md explicitly warns not to glob `tests/tui/` into unit runs. Screen-level behavior is largely untested — settings (1264 LOC), exploration (1139 LOC), and dashboard (782 LOC) have minimal or no unit tests for their data transforms.

### 9. No Screen Lifecycle Contract

Screens don't follow a consistent pattern for:
- When to load data (on_mount? compose? push?)
- How to handle the IPC bridge being unavailable
- How to refresh when underlying data changes
- How to clean up subscriptions on pop

### 10. Settings Screen Complexity

Settings is 1264 LOC — the largest screen — doing config loading, saving, validation, RNS config generation, page regeneration, and core config mutation all in one screen with no sub-screens or delegation. It directly imports and calls `save_core_config()`.

### IPC Boundary Gap Analysis (post-adversarial)

The adversarial review found 6 critical bugs and 6 warnings in the TUI services migration. Root cause analysis:

**Category 1: Type mismatches (bugs #1, #2)**
- `_device_info_to_mesh` treats `DeviceInfo` (dataclass) as dict — calls `.get()` which doesn't exist
- `RBACPolicy.from_dict()` doesn't exist — the model has no deserialization from serialized config dict
- Fix: `DeviceInfo` already has all fields as attributes — use attribute access. Add `RBACPolicy.from_dict()` using the same logic as `_parse_rbac` in services/config.py.

**Category 2: Variable ordering (bug #3)**
- `_format_my_mesh_line` early return references `last_seen`/`unread_text` before assignment
- Fix: Move variable declarations before the rbac guard, or restructure the guard.

**Category 3: Nullability contract (bug #4)**
- `bridge` property typed as `IPCBridge` but `_lifecycle.ipc_bridge` can be `None`
- Fix: Return type should be `IPCBridge | None`, or raise a clear error. Callers must handle None.

**Category 4: Missing merge logic (bug #5, #6)**
- Settings save reads config from daemon and writes it back unchanged — no TUI→CoreConfig merge
- Config reset sends empty dict which the handler rejects
- Fix: The save handler needs to convert TUI config changes to core config dict mutations. Reset needs a dedicated IPC command or a `get_default_core_config` IPC call.

**Category 5: Data loss from removed lookups (warnings #7, #8, #9)**
- `stored_nodes = []` everywhere — historical device data dropped
- `clear_nodes` button became a no-op lie
- Identity save silent failure when IPC disconnected
- Fix: Use `bridge.get_nodes()` for stored data (IPC exists, just type conversion was wrong). Add `clear_nodes` IPC or disable the button. Add disk-write fallback for identity save or show clear error.

**Summary**: The IPC commands exist for most operations. The problems are: (a) wrong type handling at the TUI↔IPC boundary, (b) missing deserialization helpers on model classes, (c) incomplete or no-op replacements where the old logic was complex.

### TUIMode Enum — Initial Values and Future Candidates

```python
class TUIMode(str, Enum):
    OPERATOR = "operator"    # Solo node management. Default.
    FLEET = "fleet"          # Full admin — all screens, panels, management surfaces.
    KIOSK = "kiosk"          # Read-only display. Wall-mounted Pi, public status board.
    FIELD = "field"          # Bandwidth-constrained. Minimal IPC, essential ops only.
    HEADLESS = "headless"    # No TUI — daemon-only with status via API/IPC.
```

**Gating model:** Screens/widgets check `app.tui_mode` to determine visibility. Not a hierarchy (FLEET > OPERATOR) — modes are profiles, not permission levels. Each mode defines which surfaces are visible, which keybindings are active, and how aggressively the TUI polls for data.

**Config:** `tui.mode: operator` in core-config.yaml. Changeable at runtime from settings (except HEADLESS which implies no TUI).

### Planning checkpoint after Yggdrasil and I2P reconciliation

The next TUI planning slice should build on the existing structural refactor and screen-lifecycle decisions. Immediate design targets: (1) repair OpenSpec parsing/bookkeeping for tui-structural-refactor so it reflects real completed work, (2) define the remaining migration plan around typed services, lifecycle base classes, and user-visible entrypoints such as explicit external docs browsing, and (3) choose the next thin vertical slice for implementation so design and OpenSpec stay aligned.

### Refactor planning emphasis: data state before presentation

The next refactor pass should treat the TUI's underlying state model as the primary design target, not just widget migration. IPC boundary bugs are symptoms of inconsistent post-IPC shaping: dicts vs dataclasses, direct DB reads bypassing canonical state, and screen-local transforms that each reinterpret daemon data. The planning goal is to define stable typed state objects and projection helpers shared across screens so presentation becomes a thin layer over a coherent model.

## Decisions

### Decision: Introduce typed TUIServices protocol as the screen/widget API contract

**Status:** decided
**Rationale:** All screens and widgets currently reach into `self.app._lifecycle.ipc_bridge` with type:ignore. A typed Protocol class (`TUIServices`) defines the complete API surface: IPC bridge access, config operations, identity, unread counts, etc. Screens depend on the protocol, not the app class. Eliminates all type:ignore annotations and provides a testable seam.

### Decision: Migrate all direct daemon imports in screens/widgets to IPC bridge calls

**Status:** decided
**Rationale:** 42 direct imports (load_core_config, get_node_store, hub_connection, _deduplicate_by_identity, generate_rns_config, get_operator_identity) bypass the daemon IPC. Requires adding 5 missing IPC commands: get_nodes (node_store), get_core_config/save_core_config (config), get_hub_status (hub), get_rbac_policy (RBAC). _deduplicate_by_identity is a pure function that can move to a shared util.

### Decision: Remove LifecycleMode.LEGACY — TUI is IPC-only

**Status:** decided
**Rationale:** Legacy mode allows TUI to bypass daemon, running its own RNS/LXMF stack. This skips all RBAC, relay, and security enforcement. It doubles initialization paths and creates untested conditional branches. The daemon is the only supported runtime. Remove LEGACY enum, use_ipc config field, CoreLifecycle usage in TUI, and AUTO fallback.

### Decision: Document keymap contract with screen-scoped binding ownership

**Status:** decided
**Rationale:** Keys like r/a/c are bound 3-6 times across screens. Textual resolves by stack priority which is correct, but there's no spec for which screen owns which key. A KEYMAP.md documents the contract: global keys (always work), per-screen keys (active when that screen is focused), and modal keys. Makes collisions intentional rather than accidental.

### Decision: IPC command set is the shared contract; IPCBridge moves to styrened.ipc in follow-up

**Status:** decided
**Rationale:** Three consumers need daemon data: TUI (Textual), embedded web API, and planned web bridge. The IPC command set is the canonical shared API. IPCBridge is the Python async client. TUIServices is a Textual-specific typed accessor. IPCBridge will move from styrened.tui.services to styrened.ipc as a follow-up so web bridge and embedded API can import it without depending on the TUI package. Current migration proceeds with IPCBridge in place; screens import through TUIServices protocol which abstracts the location.

### Decision: TUIServices Protocol — typed interface boundary

**Status:** decided
**Rationale:** Created TUIServices Protocol at tui/services/protocol.py. StyreneApp implements it. All 13 screens + 7 widgets migrated from direct daemon imports to app.services.bridge. Results: 42→4 direct imports (data models only), 19→2 type:ignore[attr-defined], 0 _lifecycle.ipc_bridge references in screens/widgets.

### Decision: IPCBridge relocated to styrened.ipc.bridge

**Status:** decided
**Rationale:** IPCBridge moved from styrened.tui.services.ipc_bridge to styrened.ipc.bridge. Zero TUI/Textual dependencies confirmed — clean move. Re-export shim at old location for backward compatibility. All 4 direct importers updated. Any consumer (TUI, web API, web bridge) can now import from styrened.ipc without pulling in Textual.

### Decision: Primary persona: solo operator managing their own node

**Status:** decided
**Rationale:** Default UX optimized for a single operator managing their own node — minimal chrome, direct actions, no fleet abstractions in the way. Fleet admin path exists but is exercised organically by the developer through daily use rather than designed up-front. This means: dashboard defaults to local node status, device list is secondary, RBAC/relay management are power-user surfaces not prominent in navigation.

### Decision: Flat navigation with progressive disclosure via "Advanced Mode" toggle

**Status:** decided
**Rationale:** Navigation stays flat (global keybindings jump between screens). No formal IA hierarchy. Design for fleet admin UX first to capture all granular details, then reduce via an "Advanced Mode" toggle in settings. Default (off) = solo operator view with sensible defaults and hidden fleet surfaces. Advanced (on) = full fleet admin UX with all screens, panels, and management surfaces visible. This ensures nothing is architecturally missing — the simple view is a curated subset, not a separate code path.

### Decision: TUI mode is an enum, not a boolean toggle

**Status:** decided
**Rationale:** Instead of a binary advanced_mode bool, use a TUIMode enum in config (`tui.mode`). Starting values: OPERATOR (solo, default) and FLEET (full admin surfaces). Enum is extensible — a future KIOSK mode (read-only display), MINIMAL mode (headless status only), or FIELD mode (low-bandwidth optimized) can be added without refactoring the gating logic. Screens check `app.tui_mode` to determine which panels, bindings, and surfaces to expose. Each mode defines a visibility profile, not a separate code path.

### Decision: LocalDashboardScreen is OPERATOR default; DashboardScreen is FLEET default — same app, different landing

**Status:** decided
**Rationale:** No separate products. TUIMode determines the landing screen: OPERATOR → LocalDashboardScreen, FLEET → DashboardScreen. User can always navigate between them. LocalDashboardScreen gets a cheeky easter-egg-style mode toggle — a small icon/emoji tucked in a corner that switches to FLEET mode. Discoverable but not prominent. 50/50 whether the user finds it there or in settings. Either path works. The toggle writes to config so it persists.

### Decision: Relay surfacing: passive badge in OPERATOR, full panel in FLEET

**Status:** decided
**Rationale:** OPERATOR mode: relay status is a passive indicator on the dashboard — "relay: 2 active" badge, invisible when no sessions exist. Clickable for a summary tooltip. FLEET mode: dedicated relay panel with session list (requester, target, bytes forwarded, duration, permanent flag), teardown actions, and config. No dedicated relay screen in either mode — it's a dashboard panel that scales with TUIMode.

### Decision: RBAC management: settings subsection in OPERATOR, expanded panel in FLEET

**Status:** decided
**Rationale:** Same progressive disclosure as relay. OPERATOR: RBAC is a settings subsection — view/edit your roster and roles, minimal surface. FLEET: expanded RBAC panel with full roster management, role assignment, capability grants, and per-device role view in MeshDeviceDetailScreen. No dedicated RBAC screen in either mode.

## Open Questions

*No open questions.*
