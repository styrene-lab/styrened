# Changelog

All notable changes to styrened will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **Legacy Python Reticulum safety release prep** — Python `styrened` is now maintenance-only for public-network behavior. Meshtastic/MQTT bridge config is refused at config-load/startup time to prevent legacy bridge operators from creating synthetic Reticulum destinations or harmful public announce traffic.
- **Reticulum announce safety** — public announce defaults and validation now enforce a one-hour minimum cadence; operator-facing TUI presets no longer expose sub-hour public announce intervals.
- **Reticulum amplification controls** — TCP interface object churn no longer triggers legacy re-announces, and LXMF path-request fanout is bounded per destination and per hour.

### Deprecated
- **Python transport and bridge development** — new transport adapters, radio bridges, Meshtastic/LoRa integration, hub behavior, and path discovery strategy belong in `styrene-rs`. The Python daemon is retained for safety, migration, and maintenance only.

## [0.15.5] - 2026-03-09

### Fixed
- **TUI: Provision disk detection null model crash** — Linux `lsblk --json` entries with `model: null` or whitespace no longer crash `ProvisionScreen` disk detection workers; removable disks now fall back to the display name `Unknown`

## [0.15.1] - 2026-03-07

### Fixed
- **TUI: DeviceInfo→MeshDevice conversion** — `_device_info_to_mesh` used dict `.get()` on dataclass; now uses `getattr()` with safe DeviceType enum conversion
- **TUI: RBACPolicy deserialization** — added `RBACPolicy.from_dict()` classmethod for reconstructing RBAC from serialized config dicts
- **TUI: _format_my_mesh_line NameError** — `last_seen`/`unread_text` referenced before assignment when rbac=None
- **TUI: bridge nullability** — `bridge` property now correctly typed as `IPCBridge | None`; all callers guard against None
- **TUI: settings save no-op** — was reading daemon config and writing it back unchanged; now serializes TUI's in-memory CoreConfig via `_serialize_config()`
- **TUI: config reset** — was sending empty dict (rejected by handler); now sends serialized default CoreConfig
- **TUI: stored node data lost** — exploration and device detail screens now fetch historical nodes from daemon via async IPC instead of hardcoded `[]`
- **TUI: clear nodes button** — honest warning notification instead of fake success message
- **TUI: _is_my_mesh without rbac** — all callers now pass cached rbac
- **TUI: hub status no-op timer** — `_retry_hub_connection` replaced with actual IPC status poll via `get_hub_status()`
- **IPC: SAVE_CORE_CONFIG double-write** — handler removed useless load→save round-trip; writes caller's dict directly

### Changed
- **IPCBridge relocated to `styrened.ipc.bridge`** — shared contract for TUI, embedded web API, and planned web bridge. Zero Textual dependencies. Re-export shim at old path for backward compatibility.
- **Dead code removed** (-878 lines): `_load_comms_data()` (80 lines unreachable SQLAlchemy), `_rpc_client` + 4 fallback blocks in command_widget (legacy mode removed), replaced with `_no_bridge_error()` helper
- **`device_info_to_mesh()`** extracted to `tui/utils.py` — shared converter used by dashboard, exploration, and device detail screens
- **`_daemon_manager_from_setup`** declared in `StyreneApp.__init__` (removes last `type: ignore[attr-defined]` in daemon_setup.py)

### Added
- `RBACPolicy.from_dict()` classmethod — deserializes RBAC policy from `_serialize_config` format
- `device_info_to_mesh()` in `tui/utils.py` — safe DeviceInfo dataclass → MeshDevice conversion
- 14 new unit tests: `test_rbac_from_dict.py` (10), `test_tui_utils.py` (4)

## [0.4.0] - 2026-02-03

### Added

#### LXMF Chat Backend (Phase 1)
- ConversationService for full LXMF chat support with SQLite persistence
- Message history storage with configurable retention (default 90 days)
- Conversation list with unread counts and pagination
- Read receipt protocol for delivery confirmations
- IPC endpoints for chat operations (send, list, history, mark-read)
- CLI commands: `chat send`, `chat list`, `chat history`

#### Sideband/NomadNet Interoperability
- Plain text message normalization for Sideband/NomadNet/MeshChat compatibility
- Protocol-aware message routing (chat vs RPC vs read receipts)
- Auto-reply now correctly filters non-chat protocols

#### Terminal Service Security Hardening
- Async identity verification with configurable retry (10 retries, 200ms delay)
- Session hijacking prevention (link association guards)
- Handoff timeout for sessions awaiting Link establishment (30s default)
- Rate limiting: per-identity session limits, total session limits, request rate limiting
- Command validation with shell and command whitelists
- Signal whitelist with blocked dangerous signals (SIGKILL, SIGSTOP, SIGQUIT)
- Idle session timeout with configurable duration (default 30 min)
- Payload dimension validation (rows/cols bounds checking)

#### RPC Security Hardening
- Authorization framework with identity-based access control
- Rate limiting (30 requests/minute per identity)
- Replay protection with request_id tracking and expiry
- Dangerous command restrictions (reboot, shutdown, factory_reset require explicit authorization)

#### IPC Handler Security
- Comprehensive input validation for all IPC message types
- Graceful shutdown handling (rejects requests during shutdown)
- Bounded message sizes and parameter validation
- Safe error responses for partial daemon initialization

### Changed
- Terminal service `_handle_terminal_resize` and `_handle_terminal_signal` now take LXMF message objects
- Identity verification moved from synchronous blocking to async with retries
- Auto-reply service filters protocol field to avoid replying to RPC messages

### Fixed
- LocalInterface reconnection no longer spams duplicate destination registrations
- Cross-node messaging identity resolution via NodeStore
- Truncated destination hash handling in chat messages
- Config loading now properly handles all edge cases
- NodeStore validates hash formats before storage

### Security
- **Terminal Sessions**: Added comprehensive security controls (authorization, rate limiting, command validation, signal filtering, idle timeout)
- **RPC Server**: Added authorization, rate limiting, and replay protection
- **IPC Handlers**: Added input validation and shutdown safety checks
- **LXMF Messages**: Plain text messages now safely normalized (prevents JSON injection)

### Testing
- Added 98 new unit tests for RPC server security (authorization, rate limiting, replay protection)
- Added 19 tests for chat protocol
- Added 20 tests for protocol registry
- Added 27 tests for daemon lifecycle
- Added 242 tests for read receipt protocol
- Added 896 tests for conversation service
- Total unit tests: 658 (up from ~400)

## [0.3.0] - 2026-02-01

### Added

#### Identity Management
- Identity detection from existing LXMF applications (NomadNet, Sideband, MeshChat)
- Identity sharing via symlinks to other LXMF applications
- CLI commands: `identity-status`, `identity-share`, `identity-unshare`
- Configurable identity paths with backup/restore support

#### IPC Module
- Unix domain socket control server for local daemon communication
- IPC protocol for status queries and daemon control
- Foundation for terminal session support

#### Terminal Sessions
- Wire protocol message types for terminal sessions (TERMINAL_REQUEST, TERMINAL_ACCEPT, TERMINAL_DATA, TERMINAL_RESIZE, TERMINAL_SIGNAL, TERMINAL_CLOSE, TERMINAL_CLOSED)
- Terminal module structure (implementation in progress)

#### Build System
- Justfile with comprehensive build automation
- Parameterized recipes: `just helm-install-tag v0.2.5`, `just release 0.4.0`
- Interactive version bump: `just bump-version`
- Development helpers: `just run-debug`, `just devices`, `just status <dest>`
- Git hooks: `.githooks/prepare-commit-msg` with commit checklist
- ImagePullSecret support for GHCR on remote K8s clusters
- Remote testing workflow: `just test-k8s-remote`

#### Testing
- Unit test directory structure (`tests/unit/`) with 113 new unit tests
- Integration test directory (`tests/integration/`) with IPC and RPC tests
- Identity detection tests (30 test cases)
- Mesh propagation test scenarios
- Overnight stability tests with metrics collection
- Test metrics infrastructure for memory leak detection

#### Documentation
- GitHub operations skill (`.claude/skills/styrened-github/`)
- Remote testing guide (`tests/k8s/REMOTE-TESTING.md`)
- Container build pipeline documentation (`CONTAINERS.md`)
- Auto-generated API documentation via pdoc
- GitHub Pages deployment for API reference

### Changed
- Consolidated LXMF message callback handling to support multiple callbacks
- Improved LXMF announce timing for RPC reliability
- Reorganized test suite with pytest markers (smoke, integration, comprehensive, slow)

### Fixed
- Config `bool()` coercion bug - `bool("false")` now correctly returns `False`
- NodeStore hash validation - rejects malformed mesh peer data
- IPC handler null checks - proper error responses when daemon partially initialized
- CLI cleanup on error paths - guaranteed `lifecycle.shutdown()` via try/finally
- Wait for LXMF announce after finding target device (be0ec70)
- Add discovery wait to send/exec CLI commands (5f7cb01)
- Support multiple LXMF message callbacks (5ce6267)
- Use register_delivery_identity for LXMF message receiving (4f5bbaf)
- Prevent announce handler from interfering with path responses (f2cc60f)
- Add client_only mode to prevent CLI port conflicts (6d22edd)

## [0.2.0] - 2026-01-28

### Added

#### CLI Tooling
- `styrened devices` - List discovered mesh devices with wait option
- `styrened status <dest>` - Query remote node status via RPC
- `styrened send <dest> "msg"` - Send chat message to node
- `styrened exec <dest> <cmd>` - Execute command on remote node
- `styrened announce` - Trigger local mesh announce
- `styrened identity` - Show/create local operator identity
- Discovery wait flags for reliable RPC operations

#### styrene-core Merge
- Merged styrene-core library into styrened package
- Consolidated wire protocol, models, and services
- Single package for daemon and library functionality

#### Build Infrastructure
- Container multi-arch builds (amd64, arm64)
- GitHub Actions workflows:
  - `pr-validation.yml` - Smoke tests on PRs
  - `edge-build.yml` - Edge builds from main
  - `nightly-build.yml` - Comprehensive nightly tests
  - `release.yml` - Full release pipeline
- Helm chart for K8s testing (`tests/k8s/helm/styrened-test/`)
- K8sTestHarness for automated deployment testing
- Justfile with composable build targets

#### Wire Protocol v2
- StyreneEnvelope format with 56 message types
- Request/response correlation via 16-byte request IDs
- Message categories: Control, Status, Content, RPC, Terminal, Hub, Pub/Sub

### Changed
- Dependency reduced from styrene-core to direct RNS/LXMF
- Configuration hierarchy simplified
- Test organization into tiers (smoke, integration, comprehensive, slow)

### Fixed
- RPC timeout handling improvements
- Announce handler interference with path discovery

## [0.1.0] - 2026-01-26

### Added

**Initial release** - Extracted daemon from styrene-tui for lightweight edge deployments.

#### Core Features
- Headless daemon mode (no UI dependencies)
- RPC server for remote device management over LXMF
- Auto-reply handler for incoming mesh messages
- Device discovery via RNS announces
- Optional HTTP API for status/control
- Systemd-ready with signal handling

#### RPC Implementation
- STATUS_REQUEST/RESPONSE - Query device status
- EXEC/EXEC_RESULT - Remote command execution (whitelisted commands)
- REBOOT - Remote reboot scheduling
- CONFIG_UPDATE - Configuration updates
- PING/PONG - Connectivity testing

#### Protocol Support
- ChatProtocol - NomadNet/MeshChat compatibility
- StyreneProtocol - Native Styrene RPC over LXMF
- Protocol registry for message routing

#### Deployment
- Nix flake for declarative deployment
- NixOS module with systemd service
- PyPI package installation
- OCI container support

#### Configuration
- YAML configuration files
- Hierarchy: CLI args > user config > system config > defaults
- CoreConfig dataclass model

### Changed
- Refactored from `styrene.daemon` to standalone `styrened` package
- Uses `CoreLifecycle` instead of `StyreneLifecycle` (removes TUI dependencies)

### Dependencies
- RNS >= 0.7.5
- LXMF >= 0.4.3
- PyYAML >= 6.0
- platformdirs >= 4.0
- SQLAlchemy >= 2.0
- msgpack >= 1.0
- Python 3.11+

---

## Migration Notes

### From styrene-tui

If migrating from the monolithic styrene-tui package:

1. Install styrened: `pip install styrened`
2. Configuration files are compatible (same CoreConfig format)
3. Identity files can be shared or migrated (see `styrened identity-status`)
4. RPC protocol is unchanged

### Version Compatibility

| styrened | RNS | LXMF | Python |
|----------|-----|------|--------|
| 0.3.x | >= 0.7.5 | >= 0.4.3 | >= 3.11 |
| 0.2.x | >= 0.7.5 | >= 0.4.3 | >= 3.11 |
| 0.1.x | >= 0.7.5 | >= 0.4.3 | >= 3.11 |
