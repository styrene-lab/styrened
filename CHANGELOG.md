# Changelog

All notable changes to styrened will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Justfile with feature parity to Makefile plus enhancements
- Parameterized recipes: `just helm-install-tag v0.2.5`, `just release 0.4.0`
- Interactive version bump: `just bump-version`
- Development helpers: `just run-debug`, `just devices`, `just status <dest>`
- Git hooks: `.githooks/prepare-commit-msg` with commit checklist
- ImagePullSecret support for GHCR on remote K8s clusters
- Remote testing workflow: `make test-k8s-remote`

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
- Makefile with composable build targets

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
