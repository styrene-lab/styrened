# TUI Behavior Census and Migration Inventory

## Purpose

This document is the authoritative inventory of all behavior currently owned by the Python Textual-based TUI. Every entry must be classified into a migration disposition before the Ratatui port begins. This inventory works inward from the UI toward the daemon, complementing the daemon `inventory.md` which works outward from services toward IPC.

## Migration Dispositions

- **PORT**: rewrite in Rust/Ratatui in the TUI port wave
- **BRIDGE**: preserve temporarily via existing IPC/bridge until Rust TUI takes ownership
- **DEFER**: explicitly deferred; document follow-on plan
- **DROP**: intentionally removed (Textual-specific, no Ratatui equivalent needed)

No entry may be left unclassified.

## Codebase Summary

| Layer | Files | Lines |
|---|---|---|
| Screens | 27 | 12,345 |
| Widgets | 34 | 10,505 |
| Services | 17 | 4,861 |
| Models | 12 | 1,191 |
| Themes | 6 | 1,571 |
| Forge | 6 | 1,882 |
| CLI | 4 | 524 |
| Lifecycle | 3 | 447 |
| Menubar | 3 | 500 |
| Styles (TCSS) | 1 | 1,271 |
| App + utils | 3 | ~1,100 |
| **Total** | **~116** | **~35,390** |

---

## 1. Application Shell and Navigation

### 1.1 StyreneApp — main application class
- **Source**: `tui/app.py:StyreneApp` (~500 LOC)
- **Behavior**: Textual App subclass; owns config, lifecycle, device cache, theme registry, keybinding hierarchy; orchestrates screen navigation via toggle/switch/push; double-ctrl-c quit pattern; deferred update check; daemon auto-start; first-run wizard flow
- **IPC dependency**: all daemon interaction through `self._lifecycle.ipc_bridge`
- **Disposition**: `PORT`
- **Notes**: Ratatui equivalent is the top-level event loop, screen manager, and keybinding dispatch. The composition pattern (Header/Footer/Content) maps to Ratatui layout primitives. The TUIServices protocol contract should be preserved as a Rust trait.

### 1.2 TUIServices protocol
- **Source**: `tui/services/protocol.py:TUIServices`
- **Behavior**: typed interface for screens/widgets to access daemon (bridge + local_identity_hash)
- **IPC dependency**: defines the contract
- **Disposition**: `PORT`
- **Notes**: becomes a Rust trait; Ratatui screens/widgets depend on it

### 1.3 Screen navigation and keybindings
- **Source**: `tui/app.py` BINDINGS, `action_*` methods
- **Behavior**: single-letter global mnemonics (g/n/e/m/c/b/a/p), toggle semantics (same key returns to dashboard), priority bindings (ctrl+c)
- **Disposition**: `PORT`
- **Notes**: Ratatui needs equivalent input dispatch; macOS Option+Arrow patches are Textual-specific

### 1.4 macOS Input binding patches
- **Source**: `tui/app.py:_patch_input_bindings()`
- **Behavior**: monkey-patches Textual Input for Option+Arrow, Cmd+Arrow macOS support
- **Disposition**: `DROP`
- **Notes**: Textual-specific; Ratatui has its own input handling

---

## 2. Lifecycle and Daemon Communication

### 2.1 StyreneLifecycle (TUI wrapper)
- **Source**: `tui/services/app_lifecycle.py:StyreneLifecycle`
- **Behavior**: IPC-only lifecycle; spawns daemon via DaemonManager, creates IPCBridge, handles async init/shutdown
- **IPC dependency**: owns DaemonManager and IPCBridge
- **Disposition**: `PORT`
- **Notes**: Rust TUI will use Unix socket IPC to a running daemon; DaemonManager spawning logic may differ

### 2.2 DaemonManager
- **Source**: `tui/services/daemon_manager.py`
- **Behavior**: subprocess management for daemon process; ensure_running, restart, shutdown; socket path discovery
- **IPC dependency**: manages daemon process lifecycle
- **Disposition**: `PORT`
- **Notes**: Rust TUI may manage the Rust daemon process instead

### 2.3 IPCBridge (re-export shim)
- **Source**: `tui/services/ipc_bridge.py` → `styrened.ipc.bridge:IPCBridge`
- **Behavior**: deprecated shim; actual bridge is in `styrened.ipc.bridge` with ~60 async methods covering devices, chat, config, pages, contacts, RPC, adapters, datalink
- **IPC dependency**: IS the IPC layer
- **Disposition**: `PORT`
- **Notes**: Rust TUI IPC client will implement equivalent calls over Unix socket framed transport; the IPCBridge method set IS the daemon API contract

### 2.4 DeviceCache
- **Source**: `tui/services/device_cache.py:DeviceCache`
- **Behavior**: app-level cache of MeshDevices with periodic background refresh, change detection, Textual message posting for reactive updates; timed priming after first paint
- **IPC dependency**: bridge.get_devices()
- **Disposition**: `PORT`
- **Notes**: Ratatui equivalent is a background task polling the daemon with diff-based UI notifications

---

## 3. Screens — Workspaces

### 3.1 SplashScreen
- **Source**: `tui/screens/splash.py` (437 LOC)
- **Behavior**: animated startup; waits for daemon connection; calls prepare_for_dashboard(); dismisses to dashboard or setup
- **Disposition**: `PORT`
- **Notes**: Ratatui splash can be simpler; core logic is "wait for daemon, then proceed"

### 3.2 DashboardScreen (Home)
- **Source**: `tui/screens/dashboard.py` (560 LOC)
- **Behavior**: home screen with node summary, status bar, activity feed, uptime, Reticulum info; reacts to DevicesUpdated
- **Disposition**: `PORT`
- **Notes**: primary operator landing screen

### 3.3 GlobalCopScreen
- **Source**: `tui/screens/global_cop.py` (404 LOC)
- **Behavior**: Common Operating Picture — fleet-wide mesh overview, fleet table, COP activity summary
- **Disposition**: `PORT`
- **Notes**: fleet situational awareness; requires device cache + activity feed

### 3.4 ExplorationScreen (Nodes)
- **Source**: `tui/screens/exploration.py` (1,418 LOC)
- **Behavior**: mesh device browser; DataTable of all devices; device detail overlay; node info panel; search/filter; sort; device actions (query status, send message, view console)
- **Disposition**: `PORT`
- **Notes**: most complex list screen; exploration_projection.py is a simpler projection variant

### 3.5 ExchangeScreen (Exchange)
- **Source**: `tui/screens/exchange.py` (1,060 LOC), `exchange_tabs.py` (748 LOC)
- **Behavior**: tabbed workspace containing Mail, Direct, and Contacts tabs; tab switching; event routing to active tab
- **Disposition**: `PORT`
- **Notes**: container screen; tabs delegate to sub-views

### 3.6 InboxScreen (Mail tab content)
- **Source**: `tui/screens/inbox.py` (808 LOC)
- **Behavior**: conversation list; unread counts; message preview; conversation open; swipe-to-delete; search
- **Disposition**: `PORT`
- **Notes**: core messaging UI

### 3.7 ConversationScreen
- **Source**: `tui/screens/conversation.py` (280 LOC)
- **Behavior**: single conversation view with chat widget, message input, read receipts
- **Disposition**: `PORT`
- **Notes**: hosts ChatWidget

### 3.8 CommsScreen (Direct messaging)
- **Source**: `tui/screens/comms.py` (205 LOC)
- **Behavior**: direct peer-to-peer messaging interface
- **Disposition**: `PORT`
- **Notes**: simpler than inbox; point-to-point

### 3.9 ContactsScreen
- **Source**: `tui/screens/contacts.py` (541 LOC)
- **Behavior**: contact address book; add/edit/remove/block contacts; alias management
- **Disposition**: `PORT`
- **Notes**: backed by ContactService via bridge

### 3.10 SettingsScreen
- **Source**: `tui/screens/settings.py` (1,985 LOC)
- **Behavior**: application settings with multiple tabs: general, network/Reticulum, identity, theme, overlays, advanced; config form generation; save/apply; theme picker with tweakcn.com import; color cascade preview; overlay adapter status
- **Disposition**: `PORT`
- **Notes**: largest screen; theme picker is Textual-specific but the config/network/identity panels are essential

### 3.11 ProvisionScreen
- **Source**: `tui/screens/provision.py` (623 LOC), `provision_modal.py` (165 LOC), `confirm_flash.py` (142 LOC)
- **Behavior**: edge device provisioning wizard; hardware detection; NixOS image building; storage selection; flash confirmation
- **Disposition**: `DEFER`
- **Notes**: uses Forge subsystem; specialized operational tool

### 3.12 DeviceConsoleScreen
- **Source**: `tui/screens/device_console.py` (386 LOC)
- **Behavior**: remote terminal/command execution on selected mesh device
- **Disposition**: `PORT`
- **Notes**: uses terminal widget; important for fleet management

### 3.13 MeshDeviceDetailScreen
- **Source**: `tui/screens/mesh_device_detail.py` (833 LOC)
- **Behavior**: detailed device view with node info, status, capabilities, path info, overlay addresses; action buttons for RPC commands
- **Disposition**: `PORT`
- **Notes**: key inspection view for individual nodes

### 3.14 UpgradeScreen
- **Source**: `tui/screens/upgrade.py` (349 LOC)
- **Behavior**: version update notification; upgrade flow; TUI restart after upgrade
- **Disposition**: `BRIDGE`
- **Notes**: operational convenience; can remain Python-side initially

### 3.15 FirstRunWizardScreen
- **Source**: `tui/screens/first_run_wizard.py` (265 LOC)
- **Behavior**: initial Reticulum configuration wizard
- **Disposition**: `PORT`
- **Notes**: important for onboarding

### 3.16 DaemonSetupScreen
- **Source**: `tui/screens/daemon_setup.py` (272 LOC)
- **Behavior**: daemon start/connection setup when daemon not found
- **Disposition**: `PORT`
- **Notes**: critical for daemon-dependent TUI startup

### 3.17 DashboardLocal and DashboardProjection
- **Source**: `tui/screens/dashboard_local.py` (84 LOC), `dashboard_projection.py` (90 LOC)
- **Behavior**: compact local dashboard and projection variants
- **Disposition**: `PORT`
- **Notes**: lightweight; follow main dashboard

### 3.18 MailGroupThreadScreen and ForumThreadScreen
- **Source**: `tui/screens/mail_group_thread.py` (130 LOC), `forum_thread.py` (50 LOC)
- **Behavior**: group thread and forum thread views
- **Disposition**: `DEFER`
- **Notes**: group threading is a decided-but-unimplemented design node

---

## 4. Widgets — Reusable UI Components

### 4.1 ChatWidget
- **Source**: `tui/widgets/chat_widget.py` (1,719 LOC)
- **Behavior**: full chat interface with message bubbles, input, attachment preview, delivery status indicators, read receipt display, message actions (copy, delete, retry), auto-scroll, real-time IPC event subscription
- **IPC dependency**: bridge.send_chat(), bridge.get_messages(), bridge.subscribe_messages()
- **Disposition**: `PORT`
- **Notes**: largest and most complex widget; core messaging UX; Ratatui equivalent needs careful design

### 4.2 PageBrowserWidget
- **Source**: `tui/widgets/page_browser.py` (975 LOC)
- **Behavior**: NomadNet page browser with navigation, link handling, micron rendering, page cache
- **IPC dependency**: bridge.fetch_page(), bridge.page_*()
- **Disposition**: `BRIDGE`
- **Notes**: complex; can remain Python-side initially

### 4.3 MicronParser
- **Source**: `tui/widgets/micron_parser.py` (819 LOC)
- **Behavior**: NomadNet micron markup parser and Rich renderable converter
- **Disposition**: `BRIDGE`
- **Notes**: tied to page browser; follows it

### 4.4 NodeInfoPanel
- **Source**: `tui/widgets/node_info_panel.py` (681 LOC)
- **Behavior**: detailed node information display with Rich markup; capabilities, overlay addresses, path info, version
- **Disposition**: `PORT`
- **Notes**: used by exploration and device detail screens

### 4.5 TerminalWidget
- **Source**: `tui/widgets/terminal_widget.py` (552 LOC)
- **Behavior**: remote command execution terminal with input, output display, command history
- **IPC dependency**: bridge.send_rpc()
- **Disposition**: `PORT`
- **Notes**: used by device console screen

### 4.6 CommandWidget
- **Source**: `tui/widgets/command_widget.py` (496 LOC)
- **Behavior**: command palette / quick-action widget
- **Disposition**: `PORT`
- **Notes**: operator efficiency tool

### 4.7 ColorPicker
- **Source**: `tui/widgets/color_picker.py` (490 LOC)
- **Behavior**: theme color picker for settings; tweakcn.com URL import
- **Disposition**: `DEFER`
- **Notes**: Textual-specific visual; Ratatui theme system will differ

### 4.8 MessageBubble
- **Source**: `tui/widgets/message_bubble.py` (280 LOC)
- **Behavior**: individual chat message rendering with direction, timestamp, delivery status, attachment indicator
- **Disposition**: `PORT`
- **Notes**: core chat UX component

### 4.9 AnimatedStatus
- **Source**: `tui/widgets/animated_status.py` (307 LOC)
- **Behavior**: animated status indicator with spinner, pulse effects
- **Disposition**: `PORT`
- **Notes**: simple but important for perceived responsiveness

### 4.10 GlitchLogo
- **Source**: `tui/widgets/glitch_logo.py` (301 LOC)
- **Behavior**: animated CRT-style glitch logo for splash screen
- **Disposition**: `PORT`
- **Notes**: branding; Ratatui can do this differently

### 4.11 HomeNodeSummary
- **Source**: `tui/widgets/home_node_summary.py` (257 LOC)
- **Behavior**: dashboard local node summary panel
- **Disposition**: `PORT`

### 4.12 HomeStatusBar
- **Source**: `tui/widgets/home_status_bar.py` (196 LOC)
- **Behavior**: dashboard status indicators (daemon, RNS, hub, mesh count)
- **Disposition**: `PORT`

### 4.13 DeviceStatusWidget
- **Source**: `tui/widgets/device_status_widget.py` (263 LOC)
- **Behavior**: compact device status display for lists/tables
- **Disposition**: `PORT`

### 4.14 ReticulumPanel
- **Source**: `tui/widgets/reticulum_panel.py` (247 LOC)
- **Behavior**: Reticulum network status and interface display
- **Disposition**: `PORT`

### 4.15 ConfigForm
- **Source**: `tui/widgets/config_form.py` (195 LOC)
- **Behavior**: dynamic configuration form generation from config schema
- **Disposition**: `PORT`
- **Notes**: Ratatui equivalent is a form renderer

### 4.16 ActivityFeed
- **Source**: `tui/widgets/activity_feed.py` (185 LOC)
- **Behavior**: scrolling activity event log for dashboard
- **IPC dependency**: bridge.get_activity_history()
- **Disposition**: `PORT`

### 4.17 GlobalCopFleetTable
- **Source**: `tui/widgets/global_cop_fleet_table.py` (179 LOC)
- **Behavior**: fleet-wide node table for Global COP screen
- **Disposition**: `PORT`

### 4.18 AlertList
- **Source**: `tui/widgets/alert_list.py` (156 LOC)
- **Behavior**: operational alert display
- **Disposition**: `PORT`

### 4.19 HtmlRenderer
- **Source**: `tui/widgets/html_renderer.py` (238 LOC)
- **Behavior**: html2text rendering for I2P pages
- **Disposition**: `BRIDGE`
- **Notes**: follows page browser

### 4.20 PageRenderers
- **Source**: `tui/widgets/page_renderers.py` (170 LOC)
- **Behavior**: page content rendering helpers
- **Disposition**: `BRIDGE`
- **Notes**: follows page browser

### 4.21 ImagePreview
- **Source**: `tui/widgets/image_preview.py` (214 LOC)
- **Behavior**: inline image preview in chat (textual-image integration)
- **Disposition**: `DEFER`
- **Notes**: requires terminal image protocol support; Ratatui has ratatui-image

### 4.22 ProgressPanel, UptimePanel, HardwarePanel, HardwarePicker, StoragePicker, ProfilePicker, AdapterStatusBar, CopActivitySummary, CommsSummary, HighlightedPanel, SafeHeader, ForgeLog
- **Source**: various `tui/widgets/*.py`
- **Behavior**: utility/display widgets for various screens
- **Disposition**: `PORT` (most), `DEFER` (ForgeLog — follows Forge), `DROP` (SafeHeader — Textual monkey-patch)

---

## 5. Services — TUI-Local Business Logic

### 5.1 Config service
- **Source**: `tui/services/config.py` (930 LOC)
- **Behavior**: TUI-specific config (tui.yaml) loading/saving/validation; RNS config generation; directory management; CLI override application
- **Disposition**: `PORT`
- **Notes**: Rust TUI needs equivalent config management; some of this merges with daemon config

### 5.2 ServiceInstaller
- **Source**: `tui/services/service_installer.py` (607 LOC)
- **Behavior**: systemd service unit generation and installation for styrened daemon
- **Disposition**: `BRIDGE`
- **Notes**: operational tooling; can remain Python CLI

### 5.3 Changelog service
- **Source**: `tui/services/changelog.py` (454 LOC)
- **Behavior**: version changelog parsing and display
- **Disposition**: `BRIDGE`

### 5.4 Reticulum service (TUI-local)
- **Source**: `tui/services/reticulum.py` (417 LOC)
- **Behavior**: TUI-local Reticulum config detection, status queries, device discovery fallback
- **Disposition**: `PORT`
- **Notes**: much of this becomes unnecessary once TUI is pure IPC client to Rust daemon

### 5.5 Fleet service
- **Source**: `tui/services/fleet.py` (358 LOC)
- **Behavior**: fleet data formatting, node grouping, status aggregation for display
- **Disposition**: `PORT`

### 5.6 Catalog service
- **Source**: `tui/services/catalog.py` (305 LOC)
- **Behavior**: hardware catalog for provisioning
- **Disposition**: `DEFER`
- **Notes**: follows Forge/provisioning

### 5.7 Storage service
- **Source**: `tui/services/storage.py` (300 LOC)
- **Behavior**: disk/storage detection for provisioning
- **Disposition**: `DEFER`
- **Notes**: follows Forge/provisioning

### 5.8 Provisioner service
- **Source**: `tui/services/provisioner.py` (300 LOC)
- **Behavior**: edge device provisioning orchestration
- **Disposition**: `DEFER`
- **Notes**: follows Forge/provisioning

### 5.9 Update checker
- **Source**: `tui/services/update_checker.py` (59 LOC)
- **Behavior**: PyPI version check for upgrade notifications
- **Disposition**: `BRIDGE`
- **Notes**: Python-specific (PyPI); Rust TUI may have different update mechanism

### 5.10 AssetResolver
- **Source**: `tui/services/asset_resolver.py` (90 LOC)
- **Behavior**: asset path resolution for bundled resources
- **Disposition**: `PORT`

---

## 6. Theming and Styling

### 6.1 Imperial CRT theme
- **Source**: `tui/themes/imperial_crt.py`, `styrene_brand.py`
- **Behavior**: custom Textual theme with dark CRT aesthetic; brand colors; token generation
- **Disposition**: `PORT`
- **Notes**: Ratatui has its own color/style system; the palette and aesthetic should be preserved

### 6.2 ColorCascade system
- **Source**: `tui/themes/color_cascade.py`
- **Behavior**: hierarchical color theming; Forge World presets; derives from Textual themes
- **Disposition**: `PORT`
- **Notes**: the concept of a semantic color cascade is valuable regardless of framework

### 6.3 Semantic color tokens
- **Source**: `tui/themes/semantic.py`
- **Behavior**: semantic color naming (primary, danger, success, etc.)
- **Disposition**: `PORT`

### 6.4 TweakCN integration
- **Source**: `tui/themes/tweakcn.py`
- **Behavior**: import custom themes from tweakcn.com URLs
- **Disposition**: `DEFER`
- **Notes**: Textual-specific integration; Ratatui theme import will differ

### 6.5 TCSS Stylesheet
- **Source**: `tui/styles/styrene.tcss` (1,271 LOC)
- **Behavior**: Textual CSS for layout, spacing, colors, widget styling
- **Disposition**: `DROP`
- **Notes**: Textual-specific; Ratatui uses inline style/layout code

---

## 7. Forge — Edge Device Provisioning

### 7.1 Bundle builder
- **Source**: `tui/forge/bundle_builder.py`
- **Behavior**: NixOS image download, extraction, Styrene automation bundling
- **Disposition**: `DEFER`

### 7.2 Disk detect
- **Source**: `tui/forge/disk_detect.py`
- **Behavior**: removable media detection for flashing
- **Disposition**: `DEFER`

### 7.3 Media writer
- **Source**: `tui/forge/media_writer.py`
- **Behavior**: image flashing to USB/SD
- **Disposition**: `DEFER`

### 7.4 Nix build
- **Source**: `tui/forge/nix_build.py`
- **Behavior**: Nix flake build integration
- **Disposition**: `DEFER`

### 7.5 Forge models
- **Source**: `tui/forge/models.py`
- **Behavior**: data models for provisioning flow
- **Disposition**: `DEFER`

---

## 8. TUI Models

### 8.1 StyreneConfig (TUI config model)
- **Source**: `tui/models/config.py`
- **Behavior**: TUI-specific configuration dataclass; deployment mode, peer config, TUI settings
- **Disposition**: `PORT`

### 8.2 Fleet models
- **Source**: `tui/models/fleet.py`
- **Behavior**: fleet summary, node group, fleet statistics
- **Disposition**: `PORT`

### 8.3 Events model
- **Source**: `tui/models/events.py`
- **Behavior**: TUI event type definitions
- **Disposition**: `PORT`

### 8.4 COP situation model
- **Source**: `tui/models/cop_situation.py`
- **Behavior**: Common Operating Picture situation data model
- **Disposition**: `PORT`

### 8.5 Adapter status, catalog, hardware, profiles, roles, RPC models
- **Source**: various `tui/models/*.py`
- **Behavior**: data models for adapter display, hardware catalog, user profiles, role display, RPC results
- **Disposition**: `PORT` (adapter_status, hardware, profiles, roles, rpc), `DEFER` (catalog — follows Forge)

---

## 9. Menubar and CLI

### 9.1 Agent menubar
- **Source**: `tui/menubar/agent.py`
- **Behavior**: agent/automation menubar integration
- **Disposition**: `DEFER`

### 9.2 Clipboard menubar
- **Source**: `tui/menubar/clipboard.py`
- **Behavior**: clipboard operations
- **Disposition**: `PORT`

### 9.3 TUI CLI commands
- **Source**: `tui/cli/fleet_cli.py`, `hardware_cli.py`, `reticulum_cli.py`
- **Behavior**: CLI subcommands accessible from within the TUI
- **Disposition**: `BRIDGE`
- **Notes**: may be replaced by Rust CLI equivalents

---

## 10. Lifecycle Helpers

### 10.1 Screen content lifecycle
- **Source**: `tui/lifecycle/screen_content.py`
- **Behavior**: screen content load/unload lifecycle management
- **Disposition**: `PORT`
- **Notes**: Ratatui has its own screen lifecycle patterns

### 10.2 Widget resource lifecycle
- **Source**: `tui/lifecycle/widget_resources.py`
- **Behavior**: widget resource cleanup and disposal
- **Disposition**: `PORT`

---

## IPC Contract Surface

The TUI communicates with the daemon exclusively through `IPCBridge` (~60 methods). This is the contract that the Rust daemon's Unix socket IPC must implement:

### Device / mesh
- `get_devices(styrene_only)` → `list[DeviceInfo]`
- `get_nodes(styrene_only)` → `list[DeviceInfo]`
- `query_device_status(dest_hash)` → status dict
- `get_path_info(dest_hash)` → path dict
- `announce()` → result string

### Messaging / conversations
- `send_chat(peer_hash, content, ...)` → result
- `get_messages(peer_hash, limit, ...)` → message list
- `get_conversations()` → conversation list
- `mark_read(peer_hash)` → count
- `search_messages(query, ...)` → results
- `delete_conversation(peer_hash)` → count
- `delete_message(message_id)` → bool
- `retry_message(message_id)` → result
- `subscribe_messages(callback)` → subscription
- `get_unread_counts()` → counts dict
- `get_attachment(message_id)` → attachment dict
- `sync_messages()` → sync result

### Identity / config
- `get_status()` → DaemonStatus
- `get_identity()` → IdentityInfo
- `get_config()` → config dict
- `get_core_config()` → core config dict
- `save_core_config(config)` → bool
- `set_identity(display_name, ...)` → result
- `get_auto_reply()` → auto reply config
- `set_auto_reply(enabled, message, ...)` → result

### Contacts
- `get_contacts()` → contact list
- `set_contact(peer_hash, alias, ...)` → result
- `remove_contact(peer_hash)` → bool
- `resolve_name(name)` → resolved info
- `block_peer(identity_hash, ...)` → result
- `unblock_peer(identity_hash)` → result
- `get_blocked_peers()` → blocked list

### RPC / fleet
- `send_rpc(dest_hash, command, ...)` → result
- `send_message(dest_hash, payload, ...)` → result
- `reboot_device(dest_hash, ...)` → result
- `self_update_device(dest_hash, ...)` → result

### Pages
- `fetch_page(dest_hash, path)` → page content
- `fetch_page_url(url)` → page content
- `page_disconnect(dest_hash)` → bool
- `page_save_site(...)` → result
- `page_remove_site(dest_hash)` → bool
- `page_list_sites()` → site list
- `page_crawl_site(...)` → result
- `page_get_cached(...)` → cached page
- `page_regenerate_index()` → bool

### Hub / adapters / activity
- `get_hub_status()` → hub status dict
- `get_adapter_state()` → adapter list
- `get_activity_history(limit)` → event list

### Datalink
- `datalink_establish(dest_hash)` → result
- `datalink_teardown(dest_hash)` → result
- `datalink_status(dest_hash)` → status

---

## Summary Classification

| Disposition | Count | Examples |
|---|---|---|
| **PORT** | ~55 | app shell, navigation, lifecycle, device cache, all core screens, most widgets, theming, config, fleet, models |
| **BRIDGE** | ~10 | page browser, micron parser, HTML renderer, upgrade screen, service installer, changelog, update checker, TUI CLI |
| **DEFER** | ~15 | Forge (all 5), provisioning screens/services, catalog, storage, color picker, tweakcn, image preview, group threads, agent menubar |
| **DROP** | ~3 | macOS input patches, TCSS stylesheet, SafeHeader monkey-patch |

This inventory must be reviewed and finalized before Ratatui TUI implementation begins.