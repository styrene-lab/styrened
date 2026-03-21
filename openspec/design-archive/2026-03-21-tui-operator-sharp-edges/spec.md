# TUI Operator Flow Sharp Edges — Preemptive Fixes — Design Spec (extracted)

> Auto-extracted from docs/tui-operator-sharp-edges.md at decide-time.

## Decisions

### Implement 8 quick-win sharp edge fixes; defer 10 more for future (decided)

Prioritized by impact × effort. The 8 quick wins are all small code changes (< 10 lines each) that address daily operator friction. The deferred items require new UI components (autocomplete dropdown, confirmation dialogs for settings, in-TUI diagnostics) or daemon-side changes (interface health events, delivery failure aggregation).

## Research Summary

### Flow 1: Home → Nodes → Device Detail — sharp edges

**The golden path**: operator sees NODES panel on Home → presses `n` → ExplorationScreen → selects device → MeshDeviceDetailScreen → tabs through Status/Chat/Fleet Ops/Pages/Terminal.

**Sharp edges found**:

**1a. No loading indicator when entering Exploration from Home** — if the IPC bridge is slow to return devices, the table is empty with no feedback. Operator might think the mesh is empty.
FIX: Show a "Loading mesh devices..." placeholder while the first IPC fetch is in flight.

**1b. "Devi…

### Flow 2: Exchange / Messaging — sharp edges

**The golden path**: operator presses `x` → ExchangeScreen → Direct tab → enter hash in compose input → conversation opens → type message → send.

**Sharp edges found**:

**2a. "Enter hash or name" compose input has no autocomplete** — the operator must know or paste an identity hash (64 hex chars) or exact name. No fuzzy search, no dropdown of known devices. This is the SINGLE BIGGEST friction point in daily usage — discovering a peer in Exploration, going back to Exchange, typing/pasting a has…

### Flow 3: Settings — sharp edges

**The golden path**: operator presses `` ` `` → SettingsScreen → tabs through Identity/Network/Fleet/Security/System/Appearance → modifies settings → Ctrl+S saves.

**Sharp edges found**:

**3a. Save is silent on success — operator doesn't know what was saved** — Ctrl+S triggers _save_settings() which writes config and shows a brief notify toast. But if saving fails silently for some fields (e.g., network config requires daemon restart to take effect), the operator has no way to know.
FIX: After…

### Flow 4: Contacts management — sharp edges

**The golden path**: operator navigates to Contacts → sees table → press `a` to add → fills hash + alias → saves. Or: in Device Detail, press `a` to add contact.

**Sharp edges found**:

**4a. Adding a contact from Device Detail doesn't let you customize the alias** — `action_add_contact()` auto-saves with `device.name` as the alias. No prompt for a custom name. If the node's announce name is "Styrene Node 3a8f", that becomes the contact alias.
FIX: Show a quick input dialog asking for alias bef…

### Flow 5: Error states and recovery — sharp edges

**Sharp edges found across flows**:

**5a. Daemon disconnected state is a silent cliff** — when the IPC bridge loses connection, the status bar shows "IPC ○" but every action silently fails with toast notifications. The operator has to know to check status bar for the tiny ○ indicator. No modal or prominent warning.
FIX: After N consecutive bridge failures, show a dismissible banner (like the version mismatch banner) saying "Daemon connection lost — check service status or press R to restart".

…

### Flow 6: First launch and onboarding — sharp edges

**The golden path**: first `styrened` launch → First Run Wizard → choose interface type → daemon starts → Home screen.

**Sharp edges found**:

**6a. Wizard "Skip Setup" leads to offline mode with no explanation** — the skip button says "(Offline Mode)" but doesn't explain what that means. The operator lands on a Home screen with everything showing disconnected/offline. No guidance on what to do next.
FIX: When skipping wizard, show a brief explanation: "You can configure networking later in Set…

### Flow 7: Daily monitoring — unsurfaced operational data

**What the operator sees on Home**: STATUS bar (one line), NODES table (name/status/last seen/unread/link), ACTIVITY feed (scrolling event log).

**What's available but not surfaced**:

**7a. Interface health is invisible** — the status bar shows "IF 3" (interface count) but not which interfaces are up/down. If one of three interfaces drops, the count stays at 3 (it's from daemon status, not live health). The operator needs to go to Settings → Network to see interface details, which doesn't even…

### Priority triage — implementable now vs future

**Implement NOW (small changes, high impact, no new architecture)**:

1. **1d. Status tab loading indicator** — add placeholder text to DeviceStatusWidget
2. **2c. Unread conversation visual prominence** — bold/bright unread rows in inbox table  
3. **2e. Delete conversation confirmation** — add confirmation dialog before ctrl+d
4. **5c. Hub reconnection retry feedback** — show retry count in status bar
5. **5d. Page browser auto-retry** — retry once before showing timeout
6. **7d. Total mesh de…
