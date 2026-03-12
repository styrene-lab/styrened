---
id: tui-operator-sharp-edges
title: TUI Operator Flow Sharp Edges — Preemptive Fixes
status: decided
parent: tui-ux-assessment-2026-03
tags: [tui, ux, operator-flow, sharp-edges]
open_questions: []
---

# TUI Operator Flow Sharp Edges — Preemptive Fixes

## Overview

Systematic walk-through of operator user flows identifying friction points, dead ends, missing affordances, and confusing states. Prioritized by impact on daily operator workflow.

## Research

### Flow 1: Home → Nodes → Device Detail — sharp edges

**The golden path**: operator sees NODES panel on Home → presses `n` → ExplorationScreen → selects device → MeshDeviceDetailScreen → tabs through Status/Chat/Fleet Ops/Pages/Terminal.

**Sharp edges found**:

**1a. No loading indicator when entering Exploration from Home** — if the IPC bridge is slow to return devices, the table is empty with no feedback. Operator might think the mesh is empty.
FIX: Show a "Loading mesh devices..." placeholder while the first IPC fetch is in flight.

**1b. "Device not found" on detail screen is a dead end** — if the device was in the table but evicted from live cache by the time you enter detail, you see a red error panel with no way to recover. No retry button, no "wait for announce" option.
FIX: Add a "Retry" button to the error panel, and auto-retry once with a brief delay.

**1c. Link→Speedtest prerequisite is a UX trap** — pressing `t` (speedtest) without pressing `l` (link) first gives "No active link — press L to establish first". But this assumes the operator knows links exist. The footer shows both keybindings equally but speedtest silently requires link.
FIX: Either auto-establish link when speedtest is requested, or group them visually so the dependency is obvious (e.g., "Link / Speedtest" as a single footer entry).

**1d. Status tab auto-fetches but has no progress indicator** — the status tab starts fetching RPC status on mount but shows nothing until the response arrives (could be seconds over multi-hop). Operator sees an empty tab.
FIX: Show a spinner or "Querying node..." placeholder in DeviceStatusWidget during fetch.

**1e. Mail tab is a permanent placeholder** — shows "Full per-peer mail view coming in a future release." Operator navigates here expecting functionality and finds nothing. This is a daily friction point if they have active conversations with this peer.
FIX: At minimum, filter and show existing conversation messages with this peer. The data exists (ChatWidget already works) — just redirect to the conversation.

### Flow 2: Exchange / Messaging — sharp edges

**The golden path**: operator presses `x` → ExchangeScreen → Direct tab → enter hash in compose input → conversation opens → type message → send.

**Sharp edges found**:

**2a. "Enter hash or name" compose input has no autocomplete** — the operator must know or paste an identity hash (64 hex chars) or exact name. No fuzzy search, no dropdown of known devices. This is the SINGLE BIGGEST friction point in daily usage — discovering a peer in Exploration, going back to Exchange, typing/pasting a hash.
FIX: Tab-completion or dropdown from contacts + discovered devices. Or even better: let the operator press `c` (Chat) directly from Exploration's device row, which already works but isn't obvious.

**2b. OOO (Out of Office) switch state is ephemeral** — toggling the Auto-Reply switch sets it for the session but there's no visual confirmation of what message will be sent, and the state isn't persisted across TUI restarts.
FIX: Show the auto-reply message text near the switch. Persist the toggle state to config.

**2c. Inbox tab shows conversations but "unread" count is not visually prominent** — unread conversations look nearly identical to read ones. The unread count column exists but it's just a number in a table cell.
FIX: Bold the row or use cascade.bright for unread conversations. Add a visual indicator (● dot) to rows with unread messages.

**2d. Search across tabs is non-obvious** — the search input only searches within the active tab's context. Pressing `/` in Exploration searches devices, but in Exchange it searches messages. Same key, different scope. No indicator of what scope is being searched.
FIX: Add a search scope label next to the input (e.g., "Search messages:" or "Search devices:").

**2e. Delete conversation (ctrl+d) has no undo** — immediate deletion with a notify toast. For a destructive action on what could be months of message history, this is insufficient.
FIX: Add a confirmation dialog ("Delete conversation with [name]? This cannot be undone.").

### Flow 3: Settings — sharp edges

**The golden path**: operator presses `` ` `` → SettingsScreen → tabs through Identity/Network/Fleet/Security/System/Appearance → modifies settings → Ctrl+S saves.

**Sharp edges found**:

**3a. Save is silent on success — operator doesn't know what was saved** — Ctrl+S triggers _save_settings() which writes config and shows a brief notify toast. But if saving fails silently for some fields (e.g., network config requires daemon restart to take effect), the operator has no way to know.
FIX: After save, show which settings require a daemon restart to take effect. The status bar already shows version mismatch — extend this pattern to config changes.

**3b. Network tab peer rows truncate community hub names** — the host field for `rns.styrene.io` is truncated despite available horizontal space. Known issue from memory.
FIX: Adjust fr proportions — peer name gets 1fr while host gets 3fr, since the host is the critical identifier.

**3c. No validation on peer host/port inputs** — operator can type garbage in the host field or leave port empty. No feedback until daemon restart fails.
FIX: Validate hostname/IP format on blur. Validate port is 1-65535.

**3d. Cancel (Escape) doesn't warn about unsaved changes** — if the operator has modified settings and presses Escape, the screen closes immediately. No "You have unsaved changes" confirmation.
FIX: Track dirty state. If dirty on Escape, show confirmation dialog.

**3e. Color editor theme preview is indirect** — selecting forge world presets or editing colors applies them live, which is good. But if the operator doesn't like the result, there's no "revert to previous" without remembering what it was.
FIX: Store the previous theme state before applying changes. Add a "Revert" button that restores it.

### Flow 4: Contacts management — sharp edges

**The golden path**: operator navigates to Contacts → sees table → press `a` to add → fills hash + alias → saves. Or: in Device Detail, press `a` to add contact.

**Sharp edges found**:

**4a. Adding a contact from Device Detail doesn't let you customize the alias** — `action_add_contact()` auto-saves with `device.name` as the alias. No prompt for a custom name. If the node's announce name is "Styrene Node 3a8f", that becomes the contact alias.
FIX: Show a quick input dialog asking for alias before saving, pre-filled with device.name.

**4b. Contacts table shows hash/alias/notes but not online status** — operator has to mentally correlate contacts with the Exploration table to know which contacts are online.
FIX: Cross-reference contacts with live device discovery and show a status indicator (●/◐/○) in the contacts table.

**4c. No way to navigate from Contact → Device Detail** — selecting a contact opens chat, but there's no way to see the contact's device status, establish a link, or run a speedtest.
FIX: Add a "Detail" action (e.g., `d` binding) that pushes MeshDeviceDetailScreen for the selected contact.

**4d. "Resolve" action (r) is mysterious** — the Contacts screen has a "Resolve" binding but it's not clear what it does until you read the code. It resolves a Reticulum name to a hash. No tooltip or help text.
FIX: Rename to "Lookup" or add help text explaining what name resolution means.

### Flow 5: Error states and recovery — sharp edges

**Sharp edges found across flows**:

**5a. Daemon disconnected state is a silent cliff** — when the IPC bridge loses connection, the status bar shows "IPC ○" but every action silently fails with toast notifications. The operator has to know to check status bar for the tiny ○ indicator. No modal or prominent warning.
FIX: After N consecutive bridge failures, show a dismissible banner (like the version mismatch banner) saying "Daemon connection lost — check service status or press R to restart".

**5b. RNS initialization failure is cryptic** — when RNS fails (port conflict, config error), the status bar shows "RNS ○ offline" and the NodeInfoPanel shows the error title. But the recovery suggestion is often truncated. The operator needs to know whether to edit config, restart, or investigate.
FIX: On RNS error, the Home screen should show the full error + recovery in the activity feed or a dedicated error panel, not just truncated text in the status bar.

**5c. Hub reconnection has no feedback cycle** — hub disconnect shows "HUB ○ lost" in status bar. The 30-second retry timer is silent. Operator doesn't know if reconnection is being attempted, how many attempts have been made, or when to give up and investigate.
FIX: Show retry count or last attempt time. "HUB ○ lost (retry 3)" or "HUB ○ lost (12s ago)".

**5d. Page browser timeout on first attempt is a false negative** — known issue: first page request fails because NomadNet destination path isn't cached. Subsequent attempts succeed. But the operator sees "Page request timed out" and might give up.
FIX: Auto-retry once with a brief message "Path not cached, retrying..." before showing the timeout error.

**5e. No graceful degradation for cross-enclave peers** — when two nodes share only a hub (no direct path), pressing L (Link), T (Speedtest), or opening Terminal silently fails or hangs. The operator doesn't know these features require a direct path.
FIX: When DirectLink fails, show "This peer is reachable only through a hub. Chat and Fleet Ops work; Link/Speedtest/Terminal require a direct path." This is the cross-enclave gap from memory.

### Flow 6: First launch and onboarding — sharp edges

**The golden path**: first `styrened` launch → First Run Wizard → choose interface type → daemon starts → Home screen.

**Sharp edges found**:

**6a. Wizard "Skip Setup" leads to offline mode with no explanation** — the skip button says "(Offline Mode)" but doesn't explain what that means. The operator lands on a Home screen with everything showing disconnected/offline. No guidance on what to do next.
FIX: When skipping wizard, show a brief explanation: "You can configure networking later in Settings (` key). The TUI will run in local-only mode until an RNS interface is configured."

**6b. No post-wizard success confirmation** — after the wizard completes, the operator is dropped at the Home screen. There's no "Setup complete! Your node is now reachable at [hash]. Waiting for mesh peers..." context.
FIX: Show a one-time welcome banner on first successful daemon connection after wizard completion.

**6c. Doctor command exists but isn't surfaced in TUI** — `styrened doctor` has `--fix` and `--setup` flags that diagnose and fix installation issues. But there's no way to trigger this from the TUI. If the operator is having trouble, they have to know about the CLI command.
FIX: Add a "Diagnostics" action in Settings → System tab that runs the doctor check and displays results inline.

**6d. Identity creation isn't guided** — new users have no identity set. The Settings → Identity tab shows empty fields. There's no prompt or suggestion to set a display name. The operator discovers this only when their messages appear as anonymous hashes to recipients.
FIX: If identity display_name is empty, show a soft nudge on the Home screen: "Set your identity name in Settings to be recognizable on the mesh."

### Flow 7: Daily monitoring — unsurfaced operational data

**What the operator sees on Home**: STATUS bar (one line), NODES table (name/status/last seen/unread/link), ACTIVITY feed (scrolling event log).

**What's available but not surfaced**:

**7a. Interface health is invisible** — the status bar shows "IF 3" (interface count) but not which interfaces are up/down. If one of three interfaces drops, the count stays at 3 (it's from daemon status, not live health). The operator needs to go to Settings → Network to see interface details, which doesn't even show live status.
FIX: When an interface goes down, it should appear in the activity feed as an event. Or: show interface names and states in the NodeInfoPanel RETICULUM section (which already shows interface_count).

**7b. Announce staleness isn't visible per-interface** — in multi-interface setups, an operator might receive announces on one interface but not another. The per-device `discovered_via` field tells which interface heard the announce, but there's no aggregate "interface X hasn't seen an announce in 10 minutes" alert.
FIX: Future — interface-level health tracking. For now, the `discovered_via` column in Exploration is sufficient for diagnosis.

**7c. Message delivery failures are buried in chat** — if a message to a peer fails, the failure icon appears in the chat widget but there's no aggregate "2 messages failed delivery" counter on Home or in the activity feed.
FIX: Add "delivery_failed" events to the activity feed. Or: show a "⚠ N failed" indicator in the status bar next to unread count.

**7d. No total mesh count on Home** — the status bar shows "MESH 15" but this is Styrene nodes only. The exploration screen shows generic devices too (RNodes, LXMF peers, NomadNet nodes, propagation nodes). An operator managing a mixed mesh needs the full device count.
FIX: Show both counts: "MESH 15/62" (styrene/total) or separate "STY 15 │ ALL 62".

**7e. Uptime is formatted but not contextualized** — "IPC ● 4h12m" is useful but doesn't tell the operator if the daemon has restarted recently. No restart history.
FIX: If daemon uptime < 5 minutes, highlight it (it just restarted). Use cascade.color_warning for recently-restarted daemon: "IPC ● 2m" in warning color.

### Priority triage — implementable now vs future

**Implement NOW (small changes, high impact, no new architecture)**:

1. **1d. Status tab loading indicator** — add placeholder text to DeviceStatusWidget
2. **2c. Unread conversation visual prominence** — bold/bright unread rows in inbox table  
3. **2e. Delete conversation confirmation** — add confirmation dialog before ctrl+d
4. **5c. Hub reconnection retry feedback** — show retry count in status bar
5. **5d. Page browser auto-retry** — retry once before showing timeout
6. **7d. Total mesh device count on Home** — show both styrene and all-device counts
7. **7e. Recently-restarted daemon highlight** — warning color for uptime < 5 minutes
8. **6d. Identity nudge** — soft prompt if display_name is empty

**Implement SOON (moderate effort, clear value)**:

9. **1b. Device not found retry** — add retry button to error panel
10. **1c. Auto-establish link for speedtest** — remove the prerequisite trap
11. **4b. Contact online status** — cross-reference contacts with live discovery
12. **5a. Daemon disconnected banner** — prominent warning after repeated failures
13. **5e. Cross-enclave peer messaging** — explain limitations when link fails

**Future (significant architecture or design work)**:

14. **2a. Compose input autocomplete** — requires fuzzy search dropdown
15. **1e. Mail tab per-peer filter** — needs filtered InboxScreen variant
16. **3d. Unsaved changes warning** — needs dirty-state tracking across all settings
17. **6c. In-TUI diagnostics** — needs doctor output piped to TUI widget
18. **7a. Interface health events** — needs daemon-side interface monitoring

## Decisions

### Decision: Implement 8 quick-win sharp edge fixes; defer 10 more for future

**Status:** decided
**Rationale:** Prioritized by impact × effort. The 8 quick wins are all small code changes (< 10 lines each) that address daily operator friction. The deferred items require new UI components (autocomplete dropdown, confirmation dialogs for settings, in-TUI diagnostics) or daemon-side changes (interface health events, delivery failure aggregation).

## Open Questions

*No open questions.*
