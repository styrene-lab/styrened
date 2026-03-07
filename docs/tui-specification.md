---
id: tui-specification
title: Styrene TUI Specification
status: exploring
tags: [tui, ux, specification, textual]
open_questions:
  - What is the target user persona — solo operator managing their own node, or fleet admin managing many nodes, or both?
  - Should the TUI have a formal screen hierarchy / information architecture, or remain flat with global keybinding navigation?
  - Where should RBAC management live — its own screen, or embedded in settings, or a context menu on device nodes?
  - What is the relationship between the full TUI (StyreneApp) and the compact dashboard (LocalDashboardScreen) — are these separate products or modes of one?
  - How should relay sessions be surfaced — passive status indicator, dedicated screen, or per-device detail?
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

## Open Questions

- What is the target user persona — solo operator managing their own node, or fleet admin managing many nodes, or both?
- Should the TUI have a formal screen hierarchy / information architecture, or remain flat with global keybinding navigation?
- Where should RBAC management live — its own screen, or embedded in settings, or a context menu on device nodes?
- What is the relationship between the full TUI (StyreneApp) and the compact dashboard (LocalDashboardScreen) — are these separate products or modes of one?
- How should relay sessions be surfaced — passive status indicator, dedicated screen, or per-device detail?
