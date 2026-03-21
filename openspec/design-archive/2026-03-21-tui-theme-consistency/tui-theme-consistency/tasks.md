# TUI Theme Consistency — Cascade Sync, Residual Hardcodes, and Structural Gaps — Tasks

## 1. src/styrened/tui/widgets/home_status_bar.py (modified)

- [x] 1.1 Replaced all Rich Text style= hardcoded colors with cascade; added transport_enabled, propagation_enabled, active_links reactive props with T/P role indicators and LNK count in status bar

## 2. src/styrened/tui/widgets/chat_widget.py (modified)

- [x] 2.1 Fixed 4 remaining [red bold]/[red italic] hardcodes to cascade.color_danger

## 3. src/styrened/tui/screens/mesh_device_detail.py (modified)

- [x] 3.1 Added hops, discovered_via, and lxmf_destination_hash to device detail view

## 4. src/styrened/tui/screens/dashboard.py (modified)

- [x] 4.1 Wired transport_enabled, propagation_enabled, active_links from DaemonStatus to HomeStatusBar

## 5. src/styrened/tui/styles/styrene.tcss (modified)

- [x] 5.1 Switch height: 1 → height: auto for better visibility on dark themes

## 6. Cross-cutting constraints

- [x] 6.1 terminal_widget.py ANSI color map is exempt — those are terminal emulation, not theming
- [x] 6.2 color_picker.py white Style is exempt — intentional contrast for swatch rendering
