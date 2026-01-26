# Changelog

All notable changes to styrened will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

#### Deployment
- Nix flake for declarative deployment
- NixOS module with systemd service
- PyPI package for traditional Python installations

#### Configuration
- Uses CoreConfig from styrene-core
- Compatible with standard styrene config format
- Minimal configuration required for basic operation

### Changed
- Refactored from `styrene.daemon` to standalone `styrened` package
- Uses `CoreLifecycle` instead of `StyreneLifecycle` (removes TUI dependencies)
- Updated imports to use only `styrene-core`

### Dependencies
- **Only** depends on styrene-core (no textual, no psutil)
- Minimal footprint for edge devices
- Python 3.11+ required

### Documentation
- Complete README with usage examples
- Nix flake usage documentation
- NixOS module configuration examples

## Development Notes

This package was extracted from the styrene-tui monolith as part of Phase 11
of the library separation project. The extraction removes all TUI dependencies
(textual, psutil) to create an optimized daemon for resource-constrained
edge deployments, particularly on NixOS systems.

**Differences from original daemon.py**:
- Uses CoreConfig instead of StyreneConfig
- Uses CoreLifecycle instead of StyreneLifecycle
- No hub connection (TUI-specific feature)
- Standalone package with own entry point

See parent project documentation for migration details.
