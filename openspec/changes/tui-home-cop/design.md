# tui-home-cop — Design

## Spec-Derived Architecture

### home-status-bar
- **Compact horizontal status bar replaces NodeInfoPanel on Home** (added) — 5 scenarios
- **NodeInfoPanel state drives the status bar** (added) — 2 scenarios

### home-node-summary
- **Home screen embeds a compact read-only node summary table** (added) — 5 scenarios
- **CommsSummaryWidget removed from Home compose** (added) — 1 scenario

### home-layout-nav
- **Home compose follows COP layout order** (added) — 2 scenarios
- **Activity feed on Home shows recent events** (added) — 2 scenarios
- **Footer bindings reduced per Exchange consolidation** (modified) — 2 scenarios

## Scope

### In Scope
- New `HomeStatusBar` widget: compact 1-2 line horizontal status bar with SCADA-style dim/bright rendering
- New `HomeNodeSummaryTable` widget: read-only compact DataTable (Name|Status|Last Seen|Unread|Link), sorted abnormal-first, Enter navigates to MeshDeviceDetailScreen
- Rewire `DashboardScreen.compose()` to COP layout: HomeStatusBar → HomeNodeSummaryTable → ActivityFeedWidget
- Remove CommsSummaryWidget and NodeInfoPanel from Home compose (they continue to exist for other screens)
- Hide `c`, `b`, `p` footer bindings in app.py (`show=False`)
- CSS updates for new layout (status bar height:auto, node table 1fr, activity feed compact)
- Update existing dashboard tests to reflect new widget tree
- New unit tests for HomeStatusBar and HomeNodeSummaryTable

### Out of Scope
- Changing NodeInfoPanel internals (it stays for LocalDashboard)
- Changing CommsSummaryWidget internals (it stays for any other consumer)
- Changing ExplorationScreen, ExchangeScreen, or MeshDeviceDetailScreen
- New daemon IPC or data sources — all data already available via existing APIs

## File Changes

### New Files
| Path | Description |
|------|-------------|
| `src/styrened/tui/widgets/home_status_bar.py` | HomeStatusBar widget — compact horizontal bar with SCADA-style dim/bright rendering, reads same reactive props as NodeInfoPanel |
| `src/styrened/tui/widgets/home_node_summary.py` | HomeNodeSummaryTable widget — DataTable subclass, read-only, abnormal-first sort, Enter-to-drill |
| `tests/tui/widgets/test_home_status_bar.py` | Unit tests for HomeStatusBar rendering and anomaly promotion |
| `tests/tui/widgets/test_home_node_summary.py` | Unit tests for HomeNodeSummaryTable sort, columns, navigation |

### Modified Files
| Path | Description |
|------|-------------|
| `src/styrened/tui/screens/dashboard.py` | Rewire compose(): HomeStatusBar + HomeNodeSummaryTable + ActivityFeedWidget replaces NodeInfoPanel + CommsSummaryWidget. Update _fetch_daemon_status() to feed both status bar and node table. Wire Enter action to push MeshDeviceDetailScreen. |
| `src/styrened/tui/styles/styrene.tcss` | Add CSS for HomeStatusBar, HomeNodeSummaryTable panels; update #dashboard-container layout |
| `src/styrened/tui/app.py` | Set `show=False` on Binding entries for `c`, `b`, `p` |
| `tests/tui/screens/test_dashboard_tui.py` | Update existing tests for new widget tree: HomeStatusBar instead of NodeInfoPanel, HomeNodeSummaryTable instead of CommsSummaryWidget. Add new tests for COP layout order, node table interaction, activity feed presence. |

## Key Decisions
1. **HomeStatusBar is a new widget**, not a mode of NodeInfoPanel — NodeInfoPanel has 676 lines of two-column rendering logic that LocalDashboard still uses; trying to add a compact mode would create a maintenance burden. Clean separation.
2. **HomeNodeSummaryTable uses Textual DataTable**, not a custom Rich table rendered into a Static — DataTable gives us cursor navigation, row selection, and Enter handling for free.
3. **Node data comes from existing discovery** — `start_discovery()` is already called in `on_mount()`, and the node store is populated by announce handlers. The table reads from the same source as ExplorationScreen's fleet tables.
4. **ActivityFeedWidget reused directly** — no wrapper or adapter needed. Same widget, same API, composed into a third panel on Home.
