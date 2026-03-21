# TUI UX Assessment — Operator Interface Gaps (March 2026) — Design Spec (extracted)

> Auto-extracted from docs/tui-ux-assessment-2026-03.md at decide-time.

## Decisions

### Q1: Home gets a compact read-only node summary, not the full StyreneFleetTable (decided)

The existing tui-workspace-completion decision (Group 1) correctly moved full peer browsing to Nodes. The assessment asks for a COP, not a duplicate browser. A new HomeNodeSummaryTable widget (Name|Status|Recency|Unread, sorted abnormal-first, Enter-to-drill) gives situational awareness without duplicating ExplorationScreen. Replaces the COMMS panel on Home.

### Q2: Status bar shows all state dimmed with anomalies promoted, not anomaly-only (decided)

For mesh networking, positive confirmation of nominal state matters (operator needs to see RNS is online, not just that nothing is flagged). SCADA pattern: all fields present but dim/green; anomalies rendered bright with warning/error semantics. Compact horizontal bar replaces the current multi-line NodeInfoPanel.

### Q3: Implement the already-decided Exchange consolidation — hide c and b bindings (decided)

tui-navigation-ux already decided: x opens Exchange, m fast-paths to Mail tab, b and c removed. Current code doesn't match — all three still show=True. Implementing the existing decision drops footer from 10 to 6-7 visible bindings, fixing the overflow. No new architectural decision needed.

## Research Summary

### Reference frameworks: what works in field-proven operator interfaces

The gold standard for operator interfaces isn't modern consumer UI — it's systems designed for people who need to make decisions under uncertainty with incomplete information. The relevant patterns come from:

**NOC / Network Operations Center dashboards** (Nagios, Grafana NOC, SolarWinds): Status-first layout. The single most important question — 'is anything wrong right now?' — is answered in under 1 second by color/symbol at the top of the screen. Detail is progressive: summary → drill-down, …

### Gap 1: Home screen inverts the information hierarchy

**Current state:** The HOME STATUS panel consumes ~40% of the screen with SYSTEM (CPU, RAM, NET, STORAGE), DAEMON (IPC status, uptime), IDENTITY (name, alias, hash, security tier), RETICULUM (RNS status, interfaces), STYRENE (mode, hub, mesh count), TRAFFIC (message counts), and VERSION. The COMMS panel takes the remaining 60% with MAIL/DIRECT/CONTACTS summaries.

**The problem:** This layout answers 'who am I and what am I running?' before 'what's happening on my mesh?'. In every proven operato…

### Gap 2: Function-centric navigation instead of entity-centric

**Current state:** The footer shows: ? Help | ` Admin | n Nodes | x Exchange | m Mail | c Comms | b Contacts | p Provision | a Announce — nine top-level destinations, most of which are function-centric workspaces.

**The problem:** This navigation model asks the operator 'which function do you want?' before 'which entity are you dealing with?'. In practice, the operator's mental model is almost always entity-first: 'I want to check on node X' or 'I want to message peer Y' or 'What's happening wi…

### Gap 3: No common operating picture

**Current state:** The Home screen shows summary counts ('4 nodes', 'no unread') but not the actual entities. To see nodes, you press n to go to Nodes. To see messages, you press x/m to go to Exchange/Mail. The Home screen is a summary of summaries.

**The problem:** In every proven operator interface, the primary display IS the common operating picture — you can see the entities, their status, and their most important attributes at a glance. A NOC dashboard doesn't show '47 hosts monitored, 2 c…

### Gap 4: Nominal-dominant rendering — nothing is suppressed

**Current state:** Every field in HOME STATUS renders at the same visual weight whether it's nominal or abnormal. 'IPC: ● connected' takes the same space and visual prominence as 'HUB: ○ disconnected'. 'STORAGE: no removable' occupies a line even though it carries zero actionable information. 'ALIAS: not set' is displayed even though the operator may never set one.

**The problem:** In alarm-driven operator interfaces, the fundamental rendering principle is: nominal conditions are suppressed or …

### Gap 5: Footer is overloaded and bindings lack spatial logic

**Current state:** The app-level footer shows up to 10 bindings: ? ` n x m c b p a plus context-specific ones. At terminal widths under 123 columns (which is most real terminals), these overflow and are clipped. The bindings use mnemonic letters (n=Nodes, x=Exchange, m=Mail, c=Comms, b=Contacts, p=Provision, a=Announce) but have no spatial grouping or visual hierarchy.

**The problem:** Proven operator interfaces group actions by function and proximity. A radio console has physical buttons group…

### Gap 6: No alarm annunciation or activity feed on primary display

**Current state:** The Home screen has no mechanism to surface events that happened since the operator last looked. No 'new node discovered', no 'hub connection restored', no 'message from peer X'. The COMMS panel shows static state (unread count, contact count), not a timeline of what changed.

**The problem:** Every operator interface in the reference set has some form of event annunciation on the primary display:
- NOC dashboards have an event ticker or alarm panel showing recent state change…

### Proposed reorganization: COP-first Home

**Target layout at a glance — what the operator should see on launch:**

```
┌─ STYRENE ──────────────────────────────────────────────────────┐
│ ● RNS up (1 if) │ ○ Hub disconnected │ 4 mesh │ IPC ● 34s   │ ← compact status bar (1-2 lines)
├─ NODES ────────────────────────────────────────────────────────┤
│  NAME              STATUS    LAST SEEN    UNREAD  LINK        │ ← the mesh IS the primary display
│  casbah            ● online  12s ago      -       direct      │
│  relay-east        ● onl…

### Summary: ranked gaps by operator impact

**Ranked by how much each gap degrades an operator's ability to use the tool effectively:**

1. **No common operating picture (Gap 3)** — CRITICAL. The operator launches the TUI and sees metadata about their mesh, not the mesh itself. This is the single highest-impact change: put the node table on Home.

2. **Inverted information hierarchy (Gap 1)** — HIGH. Hardware specs and identity details dominate the screen while the operational state is buried in counts. Compress own-node status to a statu…
