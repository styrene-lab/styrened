# tui-workspace-completion — Tasks (v0.16.1)

## Release gate
All tasks in groups 1–4 must be ✅ before merge to main and version bump.
Groups 5–6 are documentation/closure tasks that happen at the end.

---

## Group 1: Dashboard → Home (narrowing)

**Label:** `dashboard-home`
**Branch:** `feature/tui-workspace-completion`
**Files:** `src/styrened/tui/screens/dashboard.py`, `src/styrened/tui/screens/dashboard_projection.py`
**Tests:** `tests/tui/screens/test_dashboard_tui.py`

- [ ] 1.1 Remove `MeshDeviceTree` and the full peer-browsing tree from `DashboardScreen`
  - Move MY MESH / OTHER STYRENE NODES tree to `ExplorationScreen` (already partially there)
  - Replace tree area with: local node status card, unread counts summary, recent activity list, alerts panel
- [ ] 1.2 Remove transport-tab sections (Yggdrasil, I2P presence) from DashboardScreen
  - These belong in CommsScreen when capability-gated (Group 3)
- [ ] 1.3 `DashboardProjection` — add `recent_activity: list[ActivityItem]` and `alerts: list[AlertItem]` to the projection dataclass; wire from IPC data
- [ ] 1.4 Update `test_dashboard_tui.py` — remove tests that verify peer tree content; add tests for Home-scope widgets (status card, unread counts, alerts)

---

## Group 2: MeshDeviceDetailScreen → canonical peer workspace

**Label:** `peer-workspace`
**Files:** `src/styrened/tui/screens/mesh_device_detail.py`
**Tests:** `tests/tui/screens/test_device_detail_tui.py`

- [ ] 2.1 Add `PeerWorkspaceFocus` tab bar to `MeshDeviceDetailScreen`
  - Tabs: Status, Mail, Comms, Pages, Ops, Terminal
  - Default focus: `PeerWorkspaceFocus.STATUS` (existing detail content)
- [ ] 2.2 Implement origin-aware Back navigation
  - Accept `origin: WorkspaceId` constructor param (default `WorkspaceId.NODES`)
  - Back action pops to the appropriate screen based on `origin`
- [ ] 2.3 Mail tab: show peer-scoped thread list (reuse InboxScreen filtered to `identity_hash`)
  - Placeholder acceptable for 0.16.1 if InboxScreen can't be filtered yet; show message "Mail for this peer"
- [ ] 2.4 Terminal tab: hidden if caller has < OPERATOR role; shown if RBAC allows
- [ ] 2.5 Update all `push_screen(MeshDeviceDetailScreen(...))` call sites to pass `origin=WorkspaceId.X`
  - ExplorationScreen → NODES, InboxScreen → MAIL, ConversationScreen → COMMS or MAIL
- [ ] 2.6 Update `test_device_detail_tui.py` — add tab navigation tests, origin-aware back tests, terminal RBAC test

---

## Group 3: CommsScreen — capability-gated content

**Label:** `comms-capability`
**Files:** `src/styrened/tui/screens/comms.py`
**Tests:** `tests/tui/screens/test_comms.py`

- [ ] 3.1 Replace placeholder panels with capability-driven content
  - Direct: show active direct-link sessions (from bridge capability data)
  - Yggdrasil section: visible only when `daemon_caps.yggdrasil == True`
  - I2P section: visible only when `daemon_caps.i2p == True`
  - Active section: live session list or "No active sessions"
- [ ] 3.2 Add I2P URL entrypoint (satisfies i2p-integration tasks 6.4 + 6.5)
  - Input widget for `.i2p` address → opens page browser with I2P transport
  - Conditionally shown when I2P capability active
- [ ] 3.3 Wire capability data from `bridge` — call `bridge.get_daemon_capabilities()` or parse from hub status
- [ ] 3.4 Update `test_comms.py` — add capability-gated visibility tests; mock bridge capability response

---

## Group 4: Code cleanup

**Label:** `cleanup`
**Files:** multiple (tests + 2 source files)
**Tests:** affected test files

- [ ] 4.1 `src/styrened/tui/services/config.py:609` — replace `load_core_config()` with `bridge.get_core_config()` (async)
- [ ] 4.2 `src/styrened/tui/screens/settings.py` — replace `generate_rns_config()` call with `bridge.save_core_config()` (RNS config built server-side)
- [ ] 4.3 Scan for remaining `app._lifecycle.ipc_bridge` references in tests; replace with `services.bridge` pattern
- [ ] 4.4 Scan for remaining `load_core_config` / `get_node_store` direct calls in TUI screens/widgets; replace with bridge calls
- [ ] 4.5 Verify: `grep -rn "app._lifecycle.ipc_bridge\|load_core_config\|get_node_store" src/styrened/tui/screens/ src/styrened/tui/widgets/` → zero hits (reticulum.py announce handler excepted)

---

## Group 5: OpenSpec closure (after groups 1–4 pass)

**Label:** `openspec-closure`

- [ ] 5.1 Mark all 12 remaining `tui-structural-refactor` tasks as complete; run `/opsx:archive tui-structural-refactor`
- [ ] 5.2 Mark i2p-integration tasks 6.4+6.5 complete; run `/opsx:archive i2p-integration`
- [ ] 5.3 Mark yggdrasil-service tasks 7.1+7.2 as `[~]` (tracked in styrene-edge, out-of-repo); run `/opsx:archive yggdrasil-service` with note
- [ ] 5.4 Archive `provision-disk-detect-null-model-hotfix` (assessment already recorded)
- [ ] 5.5 Commit archived OpenSpec + docs

---

## Group 6: Release

**Label:** `release-0.16.1`

- [ ] 6.1 Run full unit test suite: `just test-unit` — must pass (≥ 3105)
- [ ] 6.2 Run TUI screen streams A/B/C/D — all must pass
- [ ] 6.3 Bump version: `0.16.0` → `0.16.1` in `src/styrened/__init__.py` and `VERSION`
- [ ] 6.4 Commit: `chore: bump version to 0.16.1`
- [ ] 6.5 Tag: `git tag -a v0.16.1 -m "Release v0.16.1"`
- [ ] 6.6 Push: `git push origin main && git push origin v0.16.1`
- [ ] 6.7 Publish: `just publish`

---

## Completion criteria

- `grep -rn "app._lifecycle.ipc_bridge" src/styrened/tui/` → 0 production hits
- `grep -rn "load_core_config\|get_node_store" src/styrened/tui/screens/ src/styrened/tui/widgets/` → 0 hits
- DashboardScreen contains no `MeshDeviceTree` class or peer-browsing tree
- `MeshDeviceDetailScreen` has `PeerWorkspaceFocus` tab bar
- `CommsScreen` shows Yggdrasil/I2P sections only when capability-active
- All 3 parent OpenSpec changes archived
- v0.16.1 tagged and on PyPI
