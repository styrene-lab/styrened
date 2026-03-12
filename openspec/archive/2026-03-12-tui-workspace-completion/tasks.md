# tui-workspace-completion — Tasks (v0.16.1)

## Release gate
All tasks in groups 1–4 must be ✅ before merge to main and version bump.
Groups 5–6 are documentation/closure tasks that happen at the end.

---

## Group 1: Dashboard → Home (narrowing) ✅

**Label:** `dashboard-home`
**Commit:** `21e0973`
**Files:** `src/styrened/tui/screens/dashboard.py`
**Tests:** `tests/tui/screens/test_dashboard_tui.py`

- [x] 1.1 Remove `MeshDeviceTree` and the full peer-browsing tree from `DashboardScreen`
  - MeshDeviceTree class (~475 lines) removed from dashboard.py entirely
  - CURRENT NODES panel removed; Home is now status + activity only
- [x] 1.2 Remove transport-tab sections from DashboardScreen
  - Completed (they were not present in current codebase)
- [x] 1.3 Home status panel wired: NodeInfoPanel (HOME STATUS) + ActivityFeedWidget (RECENT ACTIVITY)
  - daemon status, conversations, contacts, auto_reply all fetched in _fetch_daemon_status()
- [x] 1.4 Update `test_dashboard_tui.py` — removed tree tests; added Home-scope tests (20 tests)
  - test_home_has_no_peer_tree asserts NoMatches on #mesh-device-tree
  - test_home_panels_have_correct_titles asserts titles; no CURRENT NODES

---

## Group 2: MeshDeviceDetailScreen → canonical peer workspace ✅

**Label:** `peer-workspace`
**Commit:** `a9d0dce`
**Files:** `src/styrened/tui/screens/mesh_device_detail.py`
**Tests:** `tests/tui/screens/test_device_detail_tui.py`

- [x] 2.1 PeerWorkspaceFocus tab bar already present (Status, Chat, Fleet Ops, Pages, Terminal)
- [x] 2.2 Origin-aware Back navigation already implemented (origin_workspace constructor param + pop_screen)
- [x] 2.3 Mail tab added (id="mail") — placeholder content for 0.16.1; maps to PeerWorkspaceFocus.MAIL
- [x] 2.4 Terminal tab visible always for 0.16.1 (RBAC gating deferred to v0.17.0 styrene-auth)
- [x] 2.5 All push_screen call sites already pass origin_workspace=WorkspaceId.NODES
- [x] 2.6 test_device_detail_tui.py updated — tab now includes "mail"; 3 new tests (37 total)

---

## Group 3: CommsScreen — capability-gated content ✅

**Label:** `comms-capability`
**Commit:** `3463163`
**Files:** `src/styrened/tui/screens/comms.py`
**Tests:** `tests/tui/screens/test_comms.py`

- [x] 3.1 Replaced placeholder panels with capability-driven content
  - Direct: shows active_links count from DaemonStatus
  - Yggdrasil section: visible when config.yggdrasil.mode != disabled
  - I2P section: visible when config.i2p.mode != disabled
  - Active: "No active sessions." default
- [x] 3.2 I2P URL entrypoint added (#comms-i2p-url-input Input widget)
  - Satisfies i2p-integration tasks 6.4 + 6.5
- [x] 3.3 Capability data from bridge.get_core_config() + bridge.get_status()
- [x] 3.4 test_comms.py updated — 12 tests including capability-gated visibility tests

---

## Group 4: Code cleanup ✅

**Label:** `cleanup`

- [x] 4.1 `src/styrened/tui/services/config.py:609` — load_core_config() is a sync disk read in
  _overlay_core_config(); async bridge path (bridge.get_core_config()) is used in all
  screen-level fetch workers. No change needed — screens are already clean.
- [x] 4.2 settings.py already uses bridge.save_core_config() — no generate_rns_config() calls found
- [x] 4.3 Tests use lifecycle.ipc_bridge = bridge pattern (canonical; app.services.bridge reads it)
- [x] 4.4 No direct load_core_config / get_node_store calls in screens/widgets
- [x] 4.5 Verified: grep returns zero hits for target patterns in src/styrened/tui/screens/ + widgets/
- [x] 4.6 Retired dead test_dashboard_chat_integration.py (MeshDeviceTree tombstone)

---

## Group 5: OpenSpec closure ✅

**Label:** `openspec-closure`

- [x] 5.1 tui-structural-refactor archived (12 remaining tasks absorbed into this change)
- [x] 5.2 i2p-integration archived (tasks 6.4+6.5 satisfied by Group 3 I2P URL input)
- [x] 5.3 yggdrasil-service archived (tasks 7.1+7.2 tracked in styrene-edge repo)
- [x] 5.4 provision-disk-detect-null-model-hotfix archived
- [x] 5.5 Committed archived OpenSpec + docs

---

## Group 6: Release

**Label:** `release-0.16.1`

- [x] 6.1 Run full unit test suite: `just test-unit` — passed (3053+)
- [x] 6.2 Run TUI screen streams A/B/C/D — passed
- [x] 6.3 Bump version: `0.16.0` → `0.16.1` in `src/styrened/__init__.py` and `VERSION`
- [x] 6.4 Commit: `chore: bump version to 0.16.1` (e7d3438)
- [x] 6.5 Tag: `git tag -a v0.16.1 -m "Release v0.16.1"`
- [x] 6.6 Push: `git push && git push origin v0.16.1`
- [x] 6.7 Publish: released via Argo release-build workflow
