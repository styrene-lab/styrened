# TUI Visual QA Checklist

Run `.venv/bin/styrene` in a separate terminal before confirming this checklist.

This checklist is a pre-release gate. Complete all core items. Review flagged items
if the diff addendum identifies changes in those areas.

---

## Core Checklist (every TUI release)

### Home Screen
- [ ] Home screen mounts without error or blank panel
- [ ] NodeInfoPanel shows two-column layout (SYSTEM/DAEMON/IDENTITY left, RETICULUM/STYRENE/VERSION right)
- [ ] ActivityFeedWidget is present and shows startup events
- [ ] Daemon status (online/offline) is reflected correctly
- [ ] No layout overlap or truncation at default terminal size

### Nodes Tab
- [ ] Nodes tab is reachable (key: n or tab navigation)
- [ ] Device list renders (empty state or live peers)
- [ ] Clicking/selecting a peer opens MeshDeviceDetailScreen
- [ ] MeshDeviceDetailScreen tab bar shows: Status, Chat, Mail, Fleet Ops, Pages, Terminal
- [ ] Status tab shows peer info without crash
- [ ] Back navigation returns to Nodes tab correctly

### Comms Screen
- [ ] Comms screen is reachable
- [ ] Direct link section shows active_links count (or "0 active")
- [ ] I2P section is hidden when I2P is disabled in config
- [ ] Yggdrasil section is hidden when Yggdrasil is disabled in config
- [ ] No crash when bridge returns no data for overlay sections

### Mail / Inbox
- [ ] Inbox screen is reachable
- [ ] Empty state renders cleanly (no crash, helpful message)
- [ ] Compose button or keybinding is visible

### Settings → Network Tab
- [ ] Settings screen opens
- [ ] Network tab is reachable within Settings
- [ ] All 5 panels visible: TRANSPORT, PEERS, LOCAL DISCOVERY, SERVER, BATMAN-ADV MESH
- [ ] Peer rows render (add/remove a peer row, verify layout)
- [ ] Save does not crash; success notification appears

### Navigation
- [ ] Global keybindings responsive: `?` shows help, `` ` `` toggles something, `ctrl+r` refreshes
- [ ] `q` or `escape` exits screens cleanly without traceback
- [ ] No screen transitions leave a blank/frozen UI

---

## Extended Checks (run if flagged by diff addendum)

These are prompted automatically by `just release` when git diff detects
changes in specific TUI directories.

### screens/dashboard.py changed
- [ ] Home panel titles are correct (HOME STATUS, RECENT ACTIVITY)
- [ ] No MeshDeviceTree widget present (removed in v0.16.1)

### screens/mesh_device_detail.py changed
- [ ] All peer workspace tabs present and clickable
- [ ] Origin-aware back navigation works from Nodes and other entry points

### screens/comms.py changed
- [ ] Capability-gated sections respond correctly to config state

### screens/settings.py changed
- [ ] All Network tab panels render
- [ ] Save/reset flows complete without error

### tui/widgets/ changed
- [ ] Affected widget renders in its parent screen
- [ ] No CSS bleed from widget DEFAULT_CSS into adjacent elements

### tui/themes/ or imperial_crt.tcss changed
- [ ] Color cascade applies correctly across all visited screens
- [ ] No contrast failures on key text elements (node hash, status indicators)

---

## Sign-off

After completing the checklist:
- All core items checked ✓ → confirm `y` at the release prompt
- Any failures found → fix before releasing, confirm `n` to abort

**Do not release with unchecked core items.**
