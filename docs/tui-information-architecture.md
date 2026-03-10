---
id: tui-information-architecture
title: TUI Information Architecture Refresh
status: exploring
parent: tui-specification
tags: [tui, ux, navigation, ia]
open_questions: []
---

# TUI Information Architecture Refresh

## Overview

Reassess the current sprawl of screens, overlapping navigation paths, and conversation entrypoints. Explore a more modern, consolidated terminal-first UI architecture that preserves rich in-terminal rendering while reducing duplication and improving usability across current and future frontends.

## Research

### Existing Textual interaction tooling in-repo

The repo already has a practical non-code-reading path for TUI assessment: extensive Textual pilot tests using `app.run_test()` and `pilot.press()/pause()` across app-level navigation, inbox/conversation flows, settings, dashboard/device detail, and widget snapshot tests via `snap_compare`. This means IA exploration can use an existing in-process interaction harness rather than only static code inspection. The current harness is strongest for deterministic keyflow/state assertions and snapshot regression, but many tests are behavior-smoke oriented rather than asserting a coherent navigation model.

### Current navigation graph and duplication hotspots

Current top-level navigation centers on Dashboard with global pushes to Inbox (`i`), Contacts (`b`), Provision (`p`), and Settings (`` ` ``). Dashboard also pushes Exploration (`e`) and device detail (Enter), while both Dashboard and Exploration have `c` shortcuts that bypass a standalone conversation list and open `MeshDeviceDetailScreen(initial_tab="chat")`. In contrast, Inbox and Contacts open standalone `ConversationScreen(peer_hash=...)` directly, and Inbox also has a compose flow that resolves an arbitrary hash/contact into `ConversationScreen`. This creates at least four chat entry paths: Inbox → ConversationScreen, Inbox compose → ConversationScreen, Contacts → ConversationScreen, and Dashboard/Exploration → DeviceDetail(chat tab). The result is duplicated conversation surfaces, split back-navigation semantics, and overlapping discovery surfaces: Dashboard and Exploration both browse nodes and both open device detail/chat, while DeviceDetail itself also contains a Pages tab for NomadNet and a Chat tab. Exploration additionally embeds an inline page browser only on its Pages tab, creating a third peer interaction surface beside ConversationScreen and DeviceDetail.

### Candidate primary workspace model

A promising consolidation model is to reduce the TUI to a small set of primary workspaces: Home (local daemon health, activity, unread summaries), Nodes (canonical discovery/browsing surface replacing most Dashboard/Exploration overlap), Mail (conversation index, compose, search, sync for asynchronous store-and-forward correspondence), Comms (synchronous and session-oriented communication), Contacts (directory/alias management first, chat-launch secondary if retained), and Admin (Provision + Settings, either grouped or kept as separate utility spaces). Under this model, peer interaction should converge on one canonical peer workspace—likely MeshDeviceDetail evolved into a general node workspace with tabs/panes for status, mail, comms, pages, terminal, and ops. Dashboard becomes a true overview instead of another device browser, while Exploration either becomes the Nodes workspace or is absorbed into it.

### Workspace responsibility table draft

Draft responsibility boundaries: Home = operator overview only (daemon health, activity, unread/alerts, launch points) and should not duplicate full node browsing or deep messaging. Nodes = canonical node discovery/browsing workspace (filters, categories, capability-aware previews, page discovery) and owns entry into the peer workspace; it absorbs most Dashboard fleet browsing plus Exploration. Mail = asynchronous workspace (inbox, compose, cross-thread search, sync, unread triage) and should not become a second peer-operations surface or live-session dashboard. Comms = synchronous workspace for direct text, voice/video growth, presence, active sessions, and bridge-backed communication; it should expose transport-aware submodes such as Direct, Active, Bridges, and Presence instead of collapsing everything into a generic chat list. Contacts = identity/address-book management (aliases, notes, resolve, trust/block metadata later) with launch into Mail or Comms as secondary convenience, not primary purpose. Admin = settings, provisioning, daemon/service maintenance, upgrade/setup flows, conceptually grouped even if implemented as separate screens initially. Peer Workspace = canonical drill-down surface for a selected peer/node, likely evolved from MeshDeviceDetailScreen, owning status/mail/comms/pages/ops/terminal tabs so that communication and page interaction stop being split across standalone ConversationScreen, device detail, and inline exploration browser.

### Future comms parity changes the top-level workspace map

The earlier five-workspace model underestimates Styrene's near-term scope. If Styrene aims for feature parity with other LXMF clients and then extends beyond them with native Yggdrasil, WireGuard, Batman, and Styrene-specific protocols, communication is broader than text messaging. The IA should reserve first-class space for both Mail and Comms rather than overfitting around today's Inbox. Mail should remain the asynchronous correspondence surface, while Comms should cover voice/video calls, presence, session invites, direct/live communication, file/session transfer, and compatibility fallbacks to existing LXMF-client behaviors. This avoids baking text-chat assumptions into the primary workspace model and leaves room for transport-aware capabilities to surface cleanly as parity is achieved and extended.

### Navigation contract draft for primary workspaces

Proposed navigation contract: Home is the default landing workspace with summary panels and directional shortcuts only; Enter drills into the focused summary's natural destination (for example unread summary -> Mail, active sessions -> Comms, alerting peer -> Peer Workspace). Nodes is the canonical discovery workspace; Enter opens Peer Workspace, Back returns Home unless dismissing inline search/filter first. Mail is the asynchronous workspace; Enter on a thread opens either the peer workspace with Mail-focused context or a dedicated mail thread view that remains structurally aligned with the peer workspace, while Back returns to the thread index before leaving the workspace. Comms is the synchronous workspace with submodes Direct, Active, Bridges, and Presence; Enter opens the relevant live session or peer workspace Comms context, while Back first exits transient submodes/invites/search before returning to the Comms index. Contacts opens contact detail/editing affordances and can deep-link into Mail or Comms rather than owning primary conversation surfaces. Admin groups settings, provisioning, and setup/maintenance flows; Back dismisses local forms/modals before returning to the prior admin subsection or Home. Peer Workspace is a drill-down, not a primary top-level workspace; it should preserve the originating context (Nodes, Mail, or Comms) so Back returns to the right aggregate workspace instead of always collapsing to Home.

### Migration map from current screens to target workspaces

Incremental migration plan: DashboardScreen narrows into Home by retaining local daemon health, activity, alerts, and launch summaries while moving mesh browsing responsibilities out. ExplorationScreen becomes the nucleus of Nodes, absorbing canonical peer discovery, filtering, page discovery, and entry into Peer Workspace. InboxScreen becomes Mail, keeping async thread index, compose, search, sync, and unread triage. ConversationScreen should stop being a standalone long-term destination; first it can be wrapped as a Mail-thread surface, then later merged into Peer Workspace/Mail-focused context once origin-aware navigation exists. MeshDeviceDetailScreen evolves into Peer Workspace, expanding from status/chat/pages/ops/terminal into a peer-centric surface with distinct Mail and Comms affordances plus transport/capability visibility. Current chat-first entrypoints from Dashboard/Exploration should be redirected toward Peer Workspace Comms context instead of bespoke chat flows. ContactsScreen remains Contacts but should launch into Mail or Comms explicitly rather than acting as a primary conversation surface. SettingsScreen and ProvisionScreen stay separate initially but are treated as Admin subsections conceptually. A future Comms workspace should be introduced as a new aggregate screen rather than hidden inside Inbox or Peer Workspace; initial submodes can be Direct, Active, Bridges, and Presence, with bridge-backed networks like Meshtastic, Yggdrasil, and I2P surfaced there when authoritative daemon support exists.

### Prioritized implementation plan for workspace migration

Recommended implementation order: (1) establish navigation and state primitives before large visual rewrites by introducing origin-aware Peer Workspace routing and explicit workspace identifiers in shared `ui_state`; (2) migrate existing Inbox semantics into a Mail vocabulary/spec surface without breaking behavior, treating ConversationScreen as compatibility-only for async thread viewing; (3) define and scaffold a new Comms aggregate workspace with transport-aware submodes Direct, Active, Bridges, and Presence, initially backed by existing direct-chat capabilities plus placeholder/empty-state capability panels for future voice/video and bridge integrations; (4) redirect existing Dashboard/Exploration chat launch paths toward Peer Workspace Comms context rather than standalone conversation flows; (5) narrow Dashboard into Home and strengthen Exploration into Nodes; (6) reposition Contacts to launch explicitly into Mail or Comms; (7) only after those routing/state changes, collapse or supersede ConversationScreen and inline exploration browser duplications. This sequence reduces churn by stabilizing navigation contracts and canonical destinations before visual consolidation.

### Dashboard as live-biased Home projection

Dashboard tree refactor now uses canonical NodeCatalogState plus a thin dashboard-specific projection adapter (`dashboard_projection.py`) instead of reshaping merged node payloads inline. During this slice, Dashboard was intentionally kept live-biased (current discovery only, with very old LOST nodes filtered) so Home remains a current-visibility surface while broader stored/history-oriented browsing continues migrating into the Nodes/Exploration workspace.

### Exploration as live-biased Nodes migration slice

Exploration now uses a thin projection adapter (`exploration_projection.py`) for the Styrene fleet table so canonical `NodeCatalogState` remains the source of identity-centric normalization while screen-specific representative row selection lives outside the screen body. During this migration slice, Exploration was also made live-biased (ignoring stored daemon history caches) to align with the emerging Nodes workspace role: current discovery and browsing first, broader historical state later via explicit canonical browsing flows.

### Home surface narrowed further during workspace migration

DashboardScreen now presents itself more explicitly as the Home workspace: the fleet-browsing panel title changed from 'MESH DEVICES' to 'CURRENT NODES', Dashboard gained an explicit `n` binding labeled `Nodes`, and its exploration action now delegates to the app-level Nodes workspace opener instead of constructing the screen directly. This keeps current live visibility on Home while making canonical browsing ownership clearer.

### Dashboard panel language now reflects Home semantics

Dashboard panel titles were narrowed to Home-oriented summary language: 'NODE INFO' became 'HOME STATUS', 'MESH DEVICES' became 'CURRENT NODES', and 'ACTIVITY' became 'RECENT ACTIVITY'. This keeps the Dashboard useful for immediate situational awareness while clarifying that canonical browsing belongs in Nodes, not Home.

### Exploration now more explicitly carries Nodes semantics

ExplorationScreen terminology and bindings now reflect its role as the canonical Nodes workspace. Its module/class docstrings describe discovery and peer browsing rather than generic exploration, it exposes an `n` binding labeled Home for returning from Nodes, and row-selection routing now consistently marks `origin_workspace=WorkspaceId.NODES` for peer-workspace drill-downs. During this slice, an unrelated Python 3.14 annotation issue in device_status_widget.py was also fixed by enabling postponed evaluation via `from __future__ import annotations`.

### Review pass found no new IA/security regressions in Home vs Nodes wiring

A cleanup/error-path review of the recent Home vs Nodes migration slice did not find any new obvious security regressions in the workspace routing itself: bindings remain internal, there is no new shell/path interpolation surface, and Home/Nodes navigation continues to route through explicit workspace actions/screens. The primary issues found were lifecycle/robustness concerns in Home state refresh and local identity snapshot fallback rather than information-architecture logic.

### Nodes and peer-workspace cleanup preserved the Home → Nodes → peer drill-down contract

The latest cleanup pass did not change the workspace map, but it reinforced it operationally. `ExplorationScreen` continues to behave as the canonical Nodes workspace rather than a one-off discovery utility because its refresh lifecycle is now screen-owned and resumable instead of being partly fire-and-forget. `MeshDeviceDetailScreen` likewise remains the peer drill-down workspace with origin-aware back-navigation, while operator-triggered actions like link establishment, speedtests, and contact-save are now explicitly scoped to the peer workspace lifecycle instead of continuing in an unowned way after the user leaves that drill-down.

### Mail and Comms aggregate surfaces now have broader behavioral coverage

A broader TUI test pass added explicit coverage for the new aggregate workspace surfaces rather than only app-level routing. `CommsScreen` now has direct tests for its aggregate shell contract (escape/back binding, default Direct mode, and the Direct/Active/Bridges/Presence tabs with stable placeholders). `InboxScreen` / Mail also gained focused behavior tests for layered escape semantics and resume refresh behavior, reinforcing that Mail is an aggregate workspace with its own local interaction stack instead of a thin conversation-list alias.

### Contacts aggregate surface now has broader form-layering and routing coverage

A follow-on test pass expanded coverage beyond Home, Nodes, Mail, and Comms into Contacts as its own aggregate workspace. `ContactsScreen` now has explicit tests for row-selection routing into conversations with `origin_workspace=CONTACTS`, layered escape behavior that hides edit/resolve affordances before popping the workspace, add/edit form state, and focused validation/resolve behavior. This reinforces the intended IA boundary: Contacts remains a directory-management workspace with secondary launch paths into communication surfaces rather than an unstructured alternate chat index.

### Conversation and placeholder communication surfaces now have direct compatibility coverage

The communication-cluster test pass now reaches beyond aggregate workspace shells into the compatibility surfaces that still sit between the old and target IA. `ConversationScreen` gained direct tests for default origin/focus semantics, path-info header rendering, and delete/block confirmation routing. The dedicated group-thread and forum placeholder screens also now have direct render tests for policy/reachability/topic metadata. This strengthens regression coverage around the migration boundary where Mail still opens compatibility destinations while the broader peer-workspace unification remains in progress.

### Whole-suite perimeter currently breaks outside the communication workspace cluster

After broadening Mail/Comms/Contacts/conversation coverage, a full `pytest -q` run shows the next perimeter is not in the newly tested communication cluster itself but in adjacent test infrastructure and legacy compatibility edges. The current communication/navigation slice is green under a broad targeted batch, while full-suite collection is blocked by (1) a k8s pytest option conflict, (2) a mesh harness import drift (`poll_for_status`), and (3) a legacy TUI IPCBridge compat-shim test importing private relocation-era constants that no longer exist. In practical precedence order for the next passes: unblock suite collection first at the repo/test-harness boundary, then reconcile stale compat-shim tests, then run the larger suite again to reveal the next true behavioral perimeter.

## Decisions

### Decision: The primary workspace model should split asynchronous Mail from synchronous Comms

**Status:** decided
**Rationale:** The UI should target communication feature parity first, then support richer Styrene-native communication modes without another top-level IA reshuffle. A narrow Messages workspace is too text-thread-centric for the planned scope, but a single umbrella Comms workspace would blur incompatible time models. Mail should own inbox-style, store-and-forward correspondence, while Comms should own direct/live communication, active sessions, presence, bridge-backed routes, and future multi-protocol communication features.

### Decision: Communication UI must preserve cross-client interoperability while exposing Styrene-native enhancements opportunistically

**Status:** decided
**Rationale:** The communication model should start from feature parity and interoperability with current LXMF ecosystem behaviors, using external client semantics as the baseline/fallback where needed. Styrene-specific Yggdrasil, WireGuard, Batman, or future protocol paths should appear as additive capabilities when authoritative daemon support exists, not as UI-only forks that break compatibility expectations.

## Open Questions

*No open questions.*
