---
id: tui-ux-assessment-2026-03
title: TUI UX Assessment — Operator Interface Gaps (March 2026)
status: decided
parent: tui-information-architecture
tags: [tui, ux, assessment, operator-interface, information-hierarchy]
open_questions: []
branches: ["feature/tui-ux-assessment-2026-03"]
openspec_change: tui-ux-assessment-2026-03
---

# TUI UX Assessment — Operator Interface Gaps (March 2026)

## Overview

Assessment of the current TUI from a field-operator UX perspective, benchmarked against proven operator interface patterns (NOC dashboards, military C2, radio dispatch consoles, SCADA/HMI). Focus: information hierarchy, cognitive load, situational awareness, and actionability — not visual aesthetics.

## Research

### Reference frameworks: what works in field-proven operator interfaces

The gold standard for operator interfaces isn't modern consumer UI — it's systems designed for people who need to make decisions under uncertainty with incomplete information. The relevant patterns come from:

**NOC / Network Operations Center dashboards** (Nagios, Grafana NOC, SolarWinds): Status-first layout. The single most important question — 'is anything wrong right now?' — is answered in under 1 second by color/symbol at the top of the screen. Detail is progressive: summary → drill-down, never the reverse. Navigation is flat: every major concern is one keypress away from the overview.

**Military C2 / Tactical displays** (GCCS-M, ATAK, CPOF): The primary display is a common operating picture (COP) — a spatial or tabular view of all known entities with their status. The operator's identity/own-ship status is always visible but small. The bulk of the screen is the operational picture. Actions are contextual: select entity → see options, not navigate-to-screen → find-entity → act.

**Radio dispatch consoles** (Motorola CommandCentral, Harris/L3): Channel-centric layout. The operator sees all channels simultaneously with activity indicators. The active channel is visually promoted. Talk/listen actions are immediate (one key), not buried in navigation.

**SCADA/HMI** (Wonderware, FactoryTalk): The primary display shows the process in a recognizable spatial layout with alarm annunciation. Alarms are hierarchical: critical → warning → info. The operator can dismiss/acknowledge alarms but cannot accidentally hide them. Every abnormal condition has a visible indicator somewhere on the primary display.

**Common principles across all of these:**
1. **Status before identity** — 'what's happening' beats 'who am I' for screen real estate
2. **Abnormal-first rendering** — problems are promoted, nominal is suppressed/dimmed
3. **One-glance situational awareness** — the primary display answers 'is everything OK?' without reading
4. **Flat navigation to action** — the thing you need to do is ≤2 keypresses from the overview
5. **Entity-centric, not function-centric** — you select a node/channel/device, then choose an action, rather than selecting a function (Mail, Comms) and then finding the entity
6. **Progressive disclosure** — summary → detail, never detail-first
7. **Persistent context** — own-ship/own-node status is always visible but doesn't dominate

### Gap 1: Home screen inverts the information hierarchy

**Current state:** The HOME STATUS panel consumes ~40% of the screen with SYSTEM (CPU, RAM, NET, STORAGE), DAEMON (IPC status, uptime), IDENTITY (name, alias, hash, security tier), RETICULUM (RNS status, interfaces), STYRENE (mode, hub, mesh count), TRAFFIC (message counts), and VERSION. The COMMS panel takes the remaining 60% with MAIL/DIRECT/CONTACTS summaries.

**The problem:** This layout answers 'who am I and what am I running?' before 'what's happening on my mesh?'. In every proven operator framework, the primary display prioritizes the operational picture — the mesh, the network, the nodes — not the operator's own hardware specs.

An operator launching this TUI already knows they're on an M1 Max with 64GB RAM. They don't need to be reminded every time they open the app. What they need to know instantly is:
- Are any of my nodes in trouble?
- Did anyone message me?
- Is my hub connection healthy?
- What changed since I last looked?

**What field-proven interfaces do instead:** Own-ship status is a compact status bar or small corner widget (like the GPS/battery/signal indicator on a tactical radio — always visible, never dominant). The primary display space goes to the operational picture: a table/list of entities with their current status, color-coded for abnormal conditions, with the most urgent items promoted to the top.

**Concrete gap:** The HOME STATUS panel should be compressed into a single-line or two-line status bar showing only anomalies (hub disconnected, RNS errors, pending messages). The freed space should show what the operator actually needs: the mesh — which nodes are up, which are alarming, which have unread messages.

### Gap 2: Function-centric navigation instead of entity-centric

**Current state:** The footer shows: ? Help | ` Admin | n Nodes | x Exchange | m Mail | c Comms | b Contacts | p Provision | a Announce — nine top-level destinations, most of which are function-centric workspaces.

**The problem:** This navigation model asks the operator 'which function do you want?' before 'which entity are you dealing with?'. In practice, the operator's mental model is almost always entity-first: 'I want to check on node X' or 'I want to message peer Y' or 'What's happening with hub Z'. The current model forces them to decide whether that intent maps to Nodes, Exchange, Mail, Comms, or Contacts — five different places where they might find what they're looking for.

**What proven interfaces do:** A radio dispatch console doesn't have separate screens for 'Talk', 'Listen', 'Status', and 'Directory'. It shows all channels with their status, and when you select one, all actions for that channel are available in context. Military C2 doesn't separate 'Move', 'Fire', 'Status', and 'Intel' into tabs — you click a unit on the map and all relevant actions appear.

**The Exchange consolidation was a step in the right direction** (Mail/Direct/Pages/Contacts in one tabbed view), but it still puts function-selection (which tab?) before entity-selection (which peer?). The peer workspace (MeshDeviceDetailScreen) is actually the closest thing to the right model — it shows Status/Mail/Chat/Fleet Ops/Pages/Terminal all for one peer. But you have to navigate through two screens to get there.

**Concrete gap:** The primary navigation should be: (1) Overview/COP showing all entities, (2) Select entity → see everything about that entity in one place. The function-centric workspaces (Mail, Comms, Contacts) should be secondary aggregate views for when the operator wants to scan across all entities for one function — not the primary navigation path.

### Gap 3: No common operating picture

**Current state:** The Home screen shows summary counts ('4 nodes', 'no unread') but not the actual entities. To see nodes, you press n to go to Nodes. To see messages, you press x/m to go to Exchange/Mail. The Home screen is a summary of summaries.

**The problem:** In every proven operator interface, the primary display IS the common operating picture — you can see the entities, their status, and their most important attributes at a glance. A NOC dashboard doesn't show '47 hosts monitored, 2 critical' — it shows all 47 hosts color-coded by status with the 2 critical ones at the top. A tactical display doesn't show 'MESH: ● 4 nodes' — it shows the 4 nodes with their callsigns, status, and last-contact time.

The current Home screen gives you the metadata about the mesh (how many nodes, connected/disconnected) but not the mesh itself. The operator must navigate away from Home to get any actionable information about individual entities. This means Home is a launch pad, not an operating picture.

**Concrete gap:** Home should embed a compact node table as its primary content — even just a simple 4-column list (Name/Hash | Status | Last Seen | Unread) would transform the screen from 'status about your status' into an actual operational view. The HOME STATUS information should compress into a status bar above the table, not occupy half the screen.

### Gap 4: Nominal-dominant rendering — nothing is suppressed

**Current state:** Every field in HOME STATUS renders at the same visual weight whether it's nominal or abnormal. 'IPC: ● connected' takes the same space and visual prominence as 'HUB: ○ disconnected'. 'STORAGE: no removable' occupies a line even though it carries zero actionable information. 'ALIAS: not set' is displayed even though the operator may never set one.

**The problem:** In alarm-driven operator interfaces, the fundamental rendering principle is: nominal conditions are suppressed or dimmed; abnormal conditions are promoted. A SCADA display doesn't show 'Pump 1: running, Pump 2: running, Pump 3: running, Valve 1: open, Valve 2: open' — it shows a dim process diagram where everything is grey/green until something goes wrong, at which point the alarm annunciator flashes and the offending element turns bright red.

The current TUI gives equal weight to:
- 'CPU: Apple M1 Max (10c, 64.0GB)' — never changes, never actionable
- 'HUB: ○ disconnected' — potentially critical, immediately actionable
- 'STORAGE: no removable' — informational, rarely actionable
- 'RNS: ● online (1 if)' — nominal, only interesting when it's NOT online

**Concrete gap:** Adopt abnormal-first rendering. Nominal state should be a single dim indicator or absent entirely. Only display a field prominently when it's abnormal. A healthy system should have a nearly empty status bar with a dim 'all nominal' indicator. An unhealthy system should show ONLY the anomalies, prominently.

### Gap 5: Footer is overloaded and bindings lack spatial logic

**Current state:** The app-level footer shows up to 10 bindings: ? ` n x m c b p a plus context-specific ones. At terminal widths under 123 columns (which is most real terminals), these overflow and are clipped. The bindings use mnemonic letters (n=Nodes, x=Exchange, m=Mail, c=Comms, b=Contacts, p=Provision, a=Announce) but have no spatial grouping or visual hierarchy.

**The problem:** Proven operator interfaces group actions by function and proximity. A radio console has physical buttons grouped by type: channel selection on the left, volume in the center, emergency on the right. A tactical display groups actions by urgency: critical actions are closest to the operator's primary hand, informational functions are further away.

The current footer mixes:
- Navigation (n, x, m, c, b — 5 different destinations)
- Actions (a=Announce, p=Provision)
- Meta (?, `)

There's no visual separation between these groups, and the mnemonics don't form a spatial pattern on the keyboard. An operator must memorize or scan the footer every time.

**Concrete gap:** Reduce the top-level navigation footprint. The Exchange consolidation was the right instinct — fewer top-level destinations. Consider: Home (default), Nodes (the mesh), Exchange (all communication), Admin (settings + provision). That's 4 destinations, not 9. Actions (Announce, Refresh) should be contextual to the current view, not global. The footer becomes manageable at any terminal width.

### Gap 6: No alarm annunciation or activity feed on primary display

**Current state:** The Home screen has no mechanism to surface events that happened since the operator last looked. No 'new node discovered', no 'hub connection restored', no 'message from peer X'. The COMMS panel shows static state (unread count, contact count), not a timeline of what changed.

**The problem:** Every operator interface in the reference set has some form of event annunciation on the primary display:
- NOC dashboards have an event ticker or alarm panel showing recent state changes
- C2 displays flash new contacts/tracks and maintain a track history
- SCADA has an alarm banner that shows the most recent alarms with timestamps
- Radio consoles have activity LEDs and a recent-calls log

The current Home screen is a snapshot of current state with no temporal context. The operator cannot tell whether 'HUB: ○ disconnected' has been disconnected for 5 seconds or 5 hours. There's no way to know if anything happened while they were away.

**Concrete gap:** Home needs a compact activity/event feed showing recent state changes with timestamps. This doesn't need to be large — even 3-5 lines showing the most recent events (node discovered, message received, hub connected/disconnected, announce sent) would transform situational awareness. The Diagnostics tab in Exploration already has an ActivityFeedWidget — a compact version of this belongs on Home.

### Proposed reorganization: COP-first Home

**Target layout at a glance — what the operator should see on launch:**

```
┌─ STYRENE ──────────────────────────────────────────────────────┐
│ ● RNS up (1 if) │ ○ Hub disconnected │ 4 mesh │ IPC ● 34s   │ ← compact status bar (1-2 lines)
├─ NODES ────────────────────────────────────────────────────────┤
│  NAME              STATUS    LAST SEEN    UNREAD  LINK        │ ← the mesh IS the primary display
│  casbah            ● online  12s ago      -       direct      │
│  relay-east        ● online  45s ago      2 ✉     hub         │
│  nomad-pi          ◐ stale   3m ago       -       -           │
│  fieldkit-02       ○ lost    2h ago       -       -           │
│                                                               │
│                                                               │
│                                                               │
├─ ACTIVITY ─────────────────────────────────────────────────────┤
│  08:23  ● casbah discovered via Styrene Community Hub         │ ← recent events, 3-5 lines
│  08:20  ✉ relay-east: 2 new messages                          │
│  08:15  ○ Hub connection lost                                 │
├────────────────────────────────────────────────────────────────┤
│ Enter: open node │ n: Nodes │ x: Exchange │ `: Admin │ ?: Help│ ← 4-5 bindings, not 10
└────────────────────────────────────────────────────────────────┘
```

**Key differences from current layout:**

1. **Status bar replaces HOME STATUS panel** — 1-2 lines showing only anomalies and key counters, not full hardware inventory. Nominal items suppressed.

2. **Node table IS the primary display** — the mesh is the COP. Entity-first. Each row shows name, status symbol, recency, unread count, and link type. Color/symbol semantics from existing SemanticSymbols. Abnormal nodes sort to top.

3. **Activity feed replaces COMMS summary** — temporal context. What happened recently. MAIL/DIRECT/CONTACTS static counts are replaced by an event timeline that naturally surfaces unread messages, node changes, and connection events.

4. **Enter on a node opens MeshDeviceDetailScreen** — the peer workspace. All actions (chat, mail, pages, ops, terminal) are one keypress from the overview. Entity-centric, not function-centric.

5. **Footer is 4-5 items** — Enter (contextual), Nodes (full table), Exchange (aggregate comms), Admin, Help. No Provision/Announce/Comms/Contacts as separate destinations.

**This is not a redesign — it's a reorganization.** Every component already exists in the codebase:
- Compact status rendering: NodeInfoPanel already knows all the state
- Node table: StyreneFleetTable and ReticumAnnounceTable exist in ExplorationScreen
- Activity feed: ActivityFeedWidget exists in ExplorationScreen's Diagnostics tab
- Peer workspace: MeshDeviceDetailScreen already has Status/Mail/Chat/Ops/Pages/Terminal tabs
- Footer bindings: just reducing the set

### Summary: ranked gaps by operator impact

**Ranked by how much each gap degrades an operator's ability to use the tool effectively:**

1. **No common operating picture (Gap 3)** — CRITICAL. The operator launches the TUI and sees metadata about their mesh, not the mesh itself. This is the single highest-impact change: put the node table on Home.

2. **Inverted information hierarchy (Gap 1)** — HIGH. Hardware specs and identity details dominate the screen while the operational state is buried in counts. Compress own-node status to a status bar.

3. **Nominal-dominant rendering (Gap 4)** — HIGH. Everything renders at equal weight. The operator must read every field to find the one that matters. Suppress nominal, promote anomalies.

4. **No activity feed (Gap 6)** — MEDIUM-HIGH. No temporal context. The operator can't tell what changed. Add a compact event feed.

5. **Function-centric navigation (Gap 2)** — MEDIUM. The workspace model asks 'what function?' before 'which entity?'. Enter-on-node from Home bypasses this, but the footer still encourages function-first thinking.

6. **Footer overload (Gap 5)** — MEDIUM. Too many bindings for the terminal width. Reduce to 4-5 top-level destinations.

**Implementation order should follow this ranking.** Gap 3 (COP on Home) delivers the most operator value with the least structural risk — the widgets already exist, they just need to be composed onto the Home screen.

## Decisions

### Decision: Q1: Home gets a compact read-only node summary, not the full StyreneFleetTable

**Status:** decided
**Rationale:** The existing tui-workspace-completion decision (Group 1) correctly moved full peer browsing to Nodes. The assessment asks for a COP, not a duplicate browser. A new HomeNodeSummaryTable widget (Name|Status|Recency|Unread, sorted abnormal-first, Enter-to-drill) gives situational awareness without duplicating ExplorationScreen. Replaces the COMMS panel on Home.

### Decision: Q2: Status bar shows all state dimmed with anomalies promoted, not anomaly-only

**Status:** decided
**Rationale:** For mesh networking, positive confirmation of nominal state matters (operator needs to see RNS is online, not just that nothing is flagged). SCADA pattern: all fields present but dim/green; anomalies rendered bright with warning/error semantics. Compact horizontal bar replaces the current multi-line NodeInfoPanel.

### Decision: Q3: Implement the already-decided Exchange consolidation — hide c and b bindings

**Status:** decided
**Rationale:** tui-navigation-ux already decided: x opens Exchange, m fast-paths to Mail tab, b and c removed. Current code doesn't match — all three still show=True. Implementing the existing decision drops footer from 10 to 6-7 visible bindings, fixing the overflow. No new architectural decision needed.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/home_status_bar.py` (new) — New HomeStatusBar widget — compact horizontal SCADA-style status bar
- `src/styrened/tui/widgets/home_node_summary.py` (new) — New HomeNodeSummaryTable widget — DataTable, abnormal-first sort, Enter-to-drill
- `tests/tui/widgets/test_home_status_bar.py` (new) — Unit tests for HomeStatusBar rendering and anomaly promotion
- `tests/tui/widgets/test_home_node_summary.py` (new) — Unit tests for HomeNodeSummaryTable sort, columns, navigation
- `src/styrened/tui/screens/dashboard.py` (modified) — Rewire compose() to COP layout, wire data to new widgets, handle NodeSelected
- `src/styrened/tui/styles/styrene.tcss` (modified) — CSS for new panels: status-bar-panel height:auto, nodes-panel 1fr, activity-panel compact
- `src/styrened/tui/app.py` (modified) — Hide c/b/p footer bindings (show=False)
- `tests/tui/screens/test_dashboard_tui.py` (modified) — Update existing tests, add COP layout order and interaction tests

### Constraints

- NodeInfoPanel.py must not be modified — LocalDashboardScreen still uses it
- CommsSummaryWidget must not be deleted — may have other consumers
- All 3137+ existing unit tests must continue to pass
- Status bar must fit within 80-column terminal without horizontal scroll
- Node data comes from existing discovery/node store APIs — no new IPC commands
