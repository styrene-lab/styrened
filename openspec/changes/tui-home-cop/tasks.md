# tui-home-cop — Tasks

## Dependencies
- Group 1 (HomeStatusBar widget) and Group 2 (HomeNodeSummaryTable widget) are independent.
- Group 3 (Dashboard rewire + layout) depends on Groups 1 and 2.
- Group 4 (footer cleanup) is independent of all others.

---

## 1. HomeStatusBar Widget
<!-- specs: home-status-bar -->

New widget at `src/styrened/tui/widgets/home_status_bar.py`. Compact 1-2 line horizontal bar showing subsystem indicators with SCADA-style dim/bright rendering.

- [x] 1.1 Create `HomeStatusBar(Widget)` with reactive properties mirroring NodeInfoPanel's key fields: `rns_online: bool`, `interface_count: int`, `hub_status: HubStatus`, `styrene_mesh_count: int`, `daemon_connected: bool | None`, `daemon_uptime: int`, `unread_count: int`, `error_state: RNSErrorState | None`
- [x] 1.2 Implement `render()` method returning a single Rich Text line with pipe-delimited indicators: `● RNS (N if) │ ● Hub connected │ N mesh │ IPC ● Xs │ ✉ N unread`. Use `SemanticSymbols` for status icons and `get_color_cascade()` for dim/bright colors.
- [x] 1.3 Implement anomaly promotion: when `rns_online=False`, RNS indicator uses `cascade.bright` (error); when `hub_status != CONNECTED`, hub indicator uses `cascade.bright` (warning); when `unread_count > 0`, unread uses `cascade.bright`; all nominal indicators use `cascade.dim`.
- [x] 1.4 Set `DEFAULT_CSS` to `height: auto; width: 1fr;` — bar must not force vertical scroll.
- [x] 1.5 Ensure total rendered width ≤ 76 chars (fits 80-col terminal with panel border + padding).
- [x] 1.6 Create `tests/tui/widgets/test_home_status_bar.py` with unit tests: nominal-all-dim, hub-disconnected-bright, rns-offline-bright, unread-count-bright, width-within-80-cols. Test via `widget.render()` return value inspection (Rich Text object).

## 2. HomeNodeSummaryTable Widget
<!-- specs: home-node-summary -->

New widget at `src/styrened/tui/widgets/home_node_summary.py`. Read-only DataTable showing known mesh nodes, sorted abnormal-first.

- [x] 2.1 Create `HomeNodeSummaryTable(DataTable)` with columns: Name (str), Status (symbol + label), Last Seen (relative time string), Unread (int or "—"), Link (str). Set `cursor_type="row"`, `zebra_stripes=True`.
- [x] 2.2 Add `update_nodes(nodes: list[MeshDevice], unread_map: dict[str, int])` method that clears and repopulates the table. `unread_map` keys are identity hashes, values are unread counts.
- [x] 2.3 Implement abnormal-first sort: NodeStatus.LOST → STALE → PENDING → ONLINE. Within each status group, sort by last_seen descending (most recently seen first).
- [x] 2.4 Implement relative time formatting: `<60s → "Ns ago"`, `<60m → "Nm ago"`, `<24h → "Nh ago"`, `≥24h → "Nd ago"`.
- [x] 2.5 Render status column using `SemanticSymbols` (ONLINE/PENDING/OFFLINE) and cascade colors matching severity.
- [x] 2.6 Add empty-state: when `nodes` is empty, show a single dim row or Static placeholder: "No mesh nodes discovered yet."
- [x] 2.7 Store `identity_hash` as row key so Enter selection can resolve to a peer. Override `on_data_table_row_selected` to post a custom `NodeSelected` message containing the identity hash.
- [x] 2.8 Create `tests/tui/widgets/test_home_node_summary.py` with unit tests: column headers correct, abnormal-first sort order, relative time formatting, unread count rendering, empty-state placeholder, row key stores identity_hash.

## 3. Dashboard Rewire + COP Layout
<!-- specs: home-layout-nav, home-node-summary, home-status-bar -->

Modify `src/styrened/tui/screens/dashboard.py` and `src/styrened/tui/styles/styrene.tcss` to compose the new COP layout.

- [x] 3.1 Replace `compose()` body: remove NodeInfoPanel + CommsSummaryWidget panels. New structure: `HighlightedPanel(HomeStatusBar, title="STATUS")` → `HighlightedPanel(HomeNodeSummaryTable, title="NODES")` → `HighlightedPanel(ActivityFeedWidget, title="ACTIVITY")`. All inside `#dashboard-container`.
- [x] 3.2 Update CSS: `#node-info-panel` → new `#status-bar-panel` with `height: auto; overflow: hidden;`. Node table panel gets `height: 1fr;`. Activity panel gets `height: auto; max-height: 8;` (compact, ~5 visible lines).
- [x] 3.3 Wire `_fetch_daemon_status()` to update both HomeStatusBar properties (rns_online, hub_status, etc.) and HomeNodeSummaryTable via `update_nodes()`. Node list from bridge + node store; unread map from bridge conversations API.
- [x] 3.4 Handle `HomeNodeSummaryTable.NodeSelected` message in DashboardScreen: push `MeshDeviceDetailScreen(device_identity=event.identity_hash)`.
- [x] 3.5 Keep `start_discovery()` call in `on_mount()` — already there, feeds node store.
- [x] 3.6 Wire ActivityFeedWidget to daemon activity subscription (same pattern as ExplorationScreen Diagnostics tab — `bridge.subscribe_activity()`).
- [x] 3.7 Update `tests/tui/screens/test_dashboard_tui.py`: replace `test_home_compose_creates_status_and_activity_widgets` → assert HomeStatusBar + HomeNodeSummaryTable + ActivityFeedWidget present. Replace `test_home_panels_have_correct_titles` → assert "STATUS", "NODES", "ACTIVITY" panel titles. Update `test_home_has_no_peer_tree` to also assert no CommsSummaryWidget. Add: `test_home_cop_layout_order` (status bar before node table before activity feed), `test_enter_on_node_pushes_detail_screen`, `test_activity_feed_present_on_home`.

## 4. Footer Binding Cleanup
<!-- specs: home-layout-nav -->

Two-line change in `src/styrened/tui/app.py` plus test updates.

- [x] 4.1 In `StyreneApp.BINDINGS`, set `show=False` on the `c` (Comms), `b` (Contacts), and `p` (Provision) bindings. Keys remain functional, just hidden from footer display.
- [x] 4.2 Verify remaining visible bindings fit within 80 columns: `? Help`, `` ` Admin``, `n Nodes`, `x Exchange`, `m Mail`, `a Announce` = 6 items.
- [x] 4.3 Add/update test in `tests/tui/screens/test_dashboard_tui.py` or a new `tests/unit/test_app_bindings.py`: assert `c`, `b`, `p` bindings exist but have `show=False`. Assert `n`, `x`, `m`, `a` have `show=True`.
