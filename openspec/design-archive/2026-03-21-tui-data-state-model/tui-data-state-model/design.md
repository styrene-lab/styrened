# TUI Data State Model — Design

## Architecture Decisions

### Decision: The TUI should consume canonical typed state objects, not raw IPC payloads or direct database reads

**Status:** decided
**Rationale:** Past IPC-boundary bugs came from each screen reshaping daemon data independently: treating dataclasses as dicts, mixing stored and live data ad hoc, and bypassing canonical daemon state through direct DB access. A thin presentation layer is only realistic if post-IPC normalization happens once in a shared typed state layer.

### Decision: State normalization belongs immediately above IPC and below screens/widgets

**Status:** decided
**Rationale:** The daemon/IPC layer should expose authoritative transport and persistence data, but the TUI still needs UI-oriented normalization: merging live node data with persisted history, deriving freshness/staleness, and shaping per-screen collections. Putting that logic in a shared TUI state layer avoids duplicating transforms in every screen while keeping daemon handlers free of presentation concerns.

### Decision: The shared UI-facing state layer should be frontend-agnostic, with the TUI as the first consumer rather than the only consumer

**Status:** decided
**Rationale:** styrened needs to support multiple UIs, not just Textual. The canonical state layer should therefore live above daemon/IPC and below any specific visual framework, producing typed state snapshots and projections that Textual, a web UI, or other clients can consume. TUI-specific screen/view models remain a thin adapter on top of that shared layer.

### Decision: The first canonical aggregates are node catalog, conversation index, config draft state, local daemon state, and page-browser session state

**Status:** decided
**Rationale:** These five aggregates cover the current instability hotspots: node deduplication and capability merging, unread/contact/block joins, settings save/reset semantics, local health/setup surfaces, and multi-transport page browsing. They also map cleanly to future non-TUI clients, forming a reusable UI-facing API rather than Textual-only screen state.

### Decision: Implementation starts with NodeCatalogState and LocalDaemonState, then ConfigDraftState, then ConversationIndexState and PageBrowserSessionState

**Status:** decided
**Rationale:** Node catalog and local daemon state unlock the broadest shared surfaces first while addressing the most error-prone post-IPC merges. Config draft state follows because settings correctness depends on explicit persisted-versus-editable semantics. Conversation and page-browser session state come next once the shared normalization and lifecycle patterns are established.

### Decision: NodeCatalogState should compose focused submodels for routes, overlays, link sessions, and authority metadata rather than becoming a monolith

**Status:** decided
**Rationale:** Nodes cover most infrastructure, but forcing every connection concern into one flat record would recreate the current ad hoc complexity in a typed form. The canonical node model should stay identity-centric while delegating transport routes, overlay addresses, direct-link/relay relationships, and source-authority metadata into smaller reusable submodels that other aggregates can also reference.

### Decision: Shared UI-facing state is capability-gated and snapshot-based, not a background state machine

**Status:** decided
**Rationale:** The shared UI-facing layer should construct immutable state snapshots from explicit IPC inputs when a frontend asks for them. It should not introduce its own always-on cache, polling loop, or persistence layer. Long-lived state tracking or databases remain daemon responsibilities and only exist when the corresponding daemon capability is enabled.

### Decision: Optional capability submodels are present in the schema but only populated when the daemon capability exists or is enabled

**Status:** decided
**Rationale:** To keep the API stable across frontends without paying runtime or storage cost for disabled features, canonical state types may contain optional capability-specific submodels (for example Yggdrasil, I2P, relay, page cache), but builders only populate them from authoritative inputs when that capability is enabled or the daemon advertises it. Disabled capabilities remain absent or marked unsupported rather than materializing synthetic state.

### Decision: Persistence belongs to daemon capability owners; ui_state keeps no independent database

**Status:** decided
**Rationale:** If a feature already has daemon-owned persistence, such as node_store or message/page cache, ui_state may consume snapshots of that state through IPC. If a capability is disabled, ui_state must not create shadow persistence or keep its own database just to satisfy a frontend. This keeps footprint minimal and avoids a second source of truth.

### Decision: Home/NodeInfoPanel composition should use panel-scoped snapshots as the widget contract

**Status:** decided
**Rationale:** Snapshots are the composability mechanism between DashboardScreen and NodeInfoPanel. Rather than mutating many widget fields directly, the parent should assemble a small panel-scoped projection object representing one coherent Home summary observation, then hand that snapshot to the widget for rendering. This preserves screen ownership of IPC/lifecycle while giving widgets a typed, reusable, testable contract.

## Research Context

### First-pass shared state package and interface layout

Proposed package layout: `src/styrened/ui_state/{base,nodes,sessions,daemon,config,conversations,page_browser}.py`. The first implementation wave should define canonical dataclasses plus pure builder functions that accept authoritative IPC payload snapshots and return normalized state aggregates. Builders remain frontend-agnostic and avoid Textual dependencies; frontend layers may add thin projection adapters on top.

### Interface boundary contract

The shared `ui_state` layer sits between authoritative daemon IPC snapshots and any visual frontend. It is a pure normalization layer: no Textual dependencies, no IPC clients, no database access, no background tasks, and no shadow persistence. Its public surface consists of typed canonical aggregates, focused submodels, explicit input bundles, and pure builder functions. Frontends may keep in-memory current/previous snapshots for presentation, but long-lived state tracking remains with daemon capability owners.

### Capability and footprint contract

Every capability-specific submodel must be zero-cost when the corresponding daemon capability is absent. Stable schema presence is acceptable, but builders only populate capability state from authoritative inputs. Disabled capabilities remain unsupported or absent; they do not cause `ui_state` to create synthetic peers, runtime trackers, pollers, or persistence. Yggdrasil should therefore already exist in the shared interface as optional overlay/runtime submodels, but it must remain unpopulated unless daemon inputs provide Yggdrasil data.

### First-pass constructed interfaces

First-pass shared interfaces:

- `base.py`: `LoadState`, `CapabilityState`, `KnowledgeState`, `DataIssue`, `FieldAuthority`, `RefreshMeta`
- `nodes.py`: `RouteAspect`, `OverlayAddressState`, `PeerRelationshipState`, `NodeAuthorityState`, `NodeRecord`, `NodeCatalogState`, `NodeCatalogInputs`, `build_node_catalog()`
- `sessions.py`: `SessionKind`, `SessionStatus`, `SessionRecord`, `SessionIndexState`, `SessionIndexInputs`, `build_session_index()`
- `daemon.py`: `OverlayRuntimeState`, `LocalDaemonState`, `LocalDaemonInputs`, `build_local_daemon_state()`
- `config.py`: `ConfigSnapshot`, `ConfigDraft`, `ConfigDraftState`, `build_config_draft()`, `apply_config_edit()`, `reset_config_draft()`, `validate_config_draft()`, `serialize_config_draft()`

Constructor rule: builders accept explicit authoritative input bundles and return immutable snapshots. They do not reach back into IPC or services themselves.

### Settings now consumes shared config-draft state

`SettingsScreen` now uses the shared `ConfigDraftState` contract operationally in its save path: it snapshots persisted core config, builds an editable draft from current form inputs, validates that draft before mutating the live `StyreneConfig`, and updates shared draft state for saving/validation/save-error/save-success semantics. This keeps persisted-vs-editable semantics explicit while preserving the historical behavior that the caller's original config object reflects successful saves.

### NodeInfoPanel migration should consume canonical dashboard-owned snapshots

The NodeInfoPanel cleanup clarified an important application point for the shared state model: dashboard-level canonical snapshots should be constructed outside the widget and pushed into it, rather than letting the widget call the bridge directly. For this slice, identity and mesh-count are the first candidate fields. Near-term migration can use the existing `_apply_identity_snapshot()` and `_apply_mesh_catalog_count()` seams as compatibility adapters while DashboardScreen or a dedicated dashboard adapter begins owning snapshot construction.

### Implemented panel-scoped HomeNodeInfoState snapshot for Home composition

The first concrete panel-scoped snapshot is now implemented as `HomeNodeInfoState` in `ui_state.daemon`. DashboardScreen computes normalized mesh count, builds the panel snapshot with `build_home_node_info_state(...)`, and hands that object to `NodeInfoPanel.apply_home_snapshot(...)`. This replaces multi-field direct mutation as the primary composition path for the Home summary panel while keeping a narrow, panel-focused contract instead of introducing a giant dashboard-wide state object.

### HomeNodeInfoState now carries Home comms summary as part of the same panel snapshot

The Home panel snapshot now covers the adjacent comms summary as well as daemon/runtime status. `build_home_node_info_state(...)` accepts authoritative conversation/contact/auto-reply payloads and derives unread count, conversation count, contact count, message totals, and auto-reply state. DashboardScreen now reapplies NodeInfoPanel from a coherent panel snapshot after those payloads resolve, instead of mutating the comms presentation fields directly. This keeps the Home summary contract panel-scoped while widening it just enough to cover the full rendered surface.

### HomeNodeLocalState now carries local hardware/config for Home panel composition

The remaining mixed-local responsibility in NodeInfoPanel has been reduced by adding a second panel-scoped snapshot: `HomeNodeLocalState`. DashboardScreen now gathers local hardware/config inputs (system info, primary interface, removable media count, mode, identity presentation/provider) and pushes them into the widget via `apply_home_local_snapshot(...)`. This removes widget-owned local refresh in IPC-managed Home and leaves NodeInfoPanel closer to a pure presentation role, with only legacy/non-IPC local refresh paths still using the old internal loaders.

### NodeInfoPanel fallback/local mode now reuses the same panel-scoped local snapshot shape

The Home snapshot boundary is no longer just an IPC-managed path. NodeInfoPanel's non-IPC fallback/local mode now constructs and applies `HomeNodeLocalState` through `_build_local_fallback_snapshot()` before handling legacy Reticulum reads. This keeps the local compatibility path aligned with the panel-scoped snapshot decision and reduces the number of code paths that mutate Home presentation fields directly.

### NodeInfoPanel now treats fallback/local loading as an adapter around HomeNodeLocalState

The local compatibility path is now explicitly adapter-shaped. `NodeInfoPanel` delegates non-IPC local reads to a private fallback builder helper that returns `HomeNodeLocalState`, then applies that snapshot through the same widget contract used by IPC-managed Home. This means the panel now consistently consumes panel-scoped local snapshots in both modes, with the fallback loader acting as an implementation adapter rather than a second competing state model.

### Adversarial audit: hash space confusion across TUI boundaries

Audit date: 2026-03-10. Scope: mesh_device_detail.py, exploration.py, dashboard.py, contacts.py, chat_widget.py, conversation_service.py, ipc/client.py, models/mesh_device.py, ui_state/nodes.py.

## File Changes

- `src/styrened/ui_state/` (new) — Shared frontend-agnostic canonical state package sitting above IPC and below specific visual frontends. Houses node catalog, conversation index, config draft, local daemon state, and page-browser session state types plus normalization helpers.
- `src/styrened/tui/` (modified) — Consumes shared canonical state via thin Textual-specific projection layers and view models rather than raw IPC payload shaping.
- `openspec/changes/tui-structural-refactor/` (modified) — OpenSpec change extended to capture shared UI-facing state model requirements and tasks so the refactor does not remain TUI-only in design.
- `src/styrened/ui_state/base.py` (new) — Shared load/degradation metadata, issue reporting, provenance, and common enums used by all canonical state aggregates.
- `src/styrened/ui_state/nodes.py` (new) — Identity-centric node catalog models, route aspects, overlay state, peer relationship state, authority metadata, and normalization/build functions.
- `src/styrened/ui_state/sessions.py` (new) — Ephemeral connection/session models for direct links, relay sessions, terminals, VPN handshakes, and other edge-like live state that should not be flattened into NodeRecord.
- `src/styrened/ui_state/daemon.py` (new) — Canonical local daemon state aggregate combining daemon status, identity, hub status, and overlay runtime summaries.
- `src/styrened/ui_state/config.py` (new) — Persisted snapshot versus editable draft state, dirty-field tracking, validation results, and save/reset semantics for UI configuration editors.
- `src/styrened/ui_state/mail.py` (new) — Canonical async Mail state aggregate with conversation scope kinds, thread/message records, group/forum metadata, and pure mail-index normalization builder.
- `src/styrened/tui/screens/inbox.py` (modified) — Inbox is now acting as the initial Mail workspace compatibility screen and consumes canonical MailIndexState instead of rendering raw conversation dicts directly.
- `src/styrened/tui/app.py` (modified) — App-level navigation now includes Mail-first language and action_open_mail(), with action_open_inbox() preserved as a compatibility alias during migration.

## Constraints

- The shared state layer must not depend on Textual classes or screen/widget lifecycle hooks.
- IPC remains the authoritative daemon boundary; the shared state layer normalizes and projects but does not replace daemon truth.
- Identity-centric node normalization must happen once in shared state, not separately in each screen.
- Config editing must use typed draft state with explicit persisted/editable/save/reset semantics rather than raw dict mutation in visual layers.
- Builder functions should accept explicit input snapshots rather than reaching back into IPC clients or services.
- NodeRecord remains identity-centric and composes route, overlay, relationship, and authority submodels instead of flattening all concerns.
- Ephemeral connection state belongs in sessions.py so node models do not absorb relay/terminal/direct-link/VPN runtime details.
- Shared state modules should expose deterministic pure transforms suitable for unit tests and reuse by future non-TUI frontends.
- MailIndexState currently covers direct/group/forum scope typing and normalization, but scope-aware screen routing beyond direct-thread compatibility remains unfinished.
- Inbox/Mail still relies on some legacy conversation metadata such as attachment counts until the canonical mail state surface is expanded further.
