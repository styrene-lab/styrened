# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Styrened is a headless daemon for running Styrene services on Reticulum mesh networks. It's optimized for resource-constrained edge devices and supports deployment via Nix flakes, containers, or PyPI. The styrene-core library has been merged into this package.

**Key features**: RPC server for remote management, auto-reply handler, device discovery, optional HTTP API.

## Commands

```bash
# Development setup
make install              # Install with dev dependencies

# Testing
make test                 # Run all tests
make test-unit            # Run unit tests only (excludes k8s)
make test-k8s             # Run k8s integration tests
pytest tests/test_models.py::test_name -v  # Run single test

# Code quality
make lint                 # Run ruff linter
make format               # Format with ruff
make typecheck            # Run mypy
make validate             # Run lint + typecheck + test

# Docker
make build                # Build local image (auto-detect arch)
make build-multi          # Build multi-arch (amd64, arm64)
make push                 # Build and push to ghcr.io

# Run daemon
styrened                  # Run daemon (default)
styrened daemon           # Run daemon explicitly

# CLI tools for interactive testing
styrened devices              # List discovered mesh devices
styrened devices -w 10        # Wait 10s for announces
styrened status <dest>        # Query remote node status
styrened send <dest> "msg"    # Send chat message to node
styrened exec <dest> uptime   # Execute command on remote
styrened announce             # Trigger local announce
styrened identity             # Show local operator identity
styrened identity --create    # Create identity if missing
```

## Architecture

```
src/styrened/
├── cli.py              # CLI entry point with subcommands (devices, status, send, exec, etc.)
├── daemon.py           # Main StyreneDaemon class - orchestrates all services
├── models/             # Data models (dataclasses)
│   ├── config.py       # CoreConfig - central configuration model
│   ├── mesh_device.py  # MeshDevice, DeviceType, NodeStatus
│   ├── messages.py     # SQLAlchemy message persistence
│   ├── reticulum.py    # ReticulumIdentity, ReticulumInterface
│   ├── rns_error.py    # RNS error state tracking
│   └── styrene_wire.py # StyreneEnvelope wire protocol
├── services/           # Business logic
│   ├── config.py       # YAML config loading/saving
│   ├── lifecycle.py    # CoreLifecycle - init/shutdown orchestration
│   ├── reticulum.py    # Mesh initialization, announce handling
│   ├── rns_service.py  # RNS destination caching
│   ├── lxmf_service.py # LXMF router and message handling
│   ├── auto_reply.py   # Auto-reply with cooldown tracking
│   ├── hub_connection.py
│   └── node_store.py   # Device storage/queries
├── rpc/                # Remote procedure calls over LXMF
│   ├── server.py       # Handles status_request, exec, reboot, update_config
│   ├── client.py       # Sends RPC commands
│   ├── messages.py     # Request/response message types
│   └── errors.py       # RPCError, RPCTimeoutError
└── protocols/          # LXMF protocol handlers
    ├── base.py         # Abstract Protocol base class
    ├── chat.py         # Chat protocol (NomadNet/MeshChat)
    ├── styrene.py      # Styrene-specific protocol
    └── registry.py     # Protocol routing via fields["protocol"]
```

**Async-first**: All network operations use asyncio. The daemon runs an event loop with periodic tasks for announces and cleanup.

**Configuration hierarchy**: `~/.styrene/config.yaml` → `/etc/styrene/config.yaml` → defaults

**Protocol discrimination**: LXMF messages are routed to handlers based on `fields["protocol"]` dictionary.

## Testing

Tests are organized in tiers with pytest markers:

- `smoke` - Fast validation (<2 min)
- `integration` - Moderate complexity (<10 min)  
- `comprehensive` - Deep validation (<30 min)
- `slow` - Load/scaling tests
- `rns_singleton` - Tests requiring RNS singleton isolation

```bash
pytest -m smoke                    # Run smoke tests only
pytest -m "not slow"               # Exclude slow tests
pytest -n auto                     # Parallel execution
pytest tests/k8s/ -m integration   # K8s integration tests
```

K8s tests use `tests/k8s/harness.py` (K8sTestHarness) for Helm deployment automation.

## Iterative Testing (Two-Machine)

For hands-on peer testing between two machines on the same LAN:

**Machine A (server/hub)** - e.g., MacBook:
```yaml
# ~/.config/styrene/core-config.yaml
reticulum:
  mode: standalone
  interfaces:
    server:
      enabled: true
      listen_ip: 0.0.0.0
      port: 4242
```
Then: `styrened daemon`

**Machine B (client)** - e.g., Desktop:
```yaml
# ~/.config/styrene/core-config.yaml
reticulum:
  mode: standalone
  interfaces:
    peers:
      - host: <machine-a-ip>
        port: 4242
```
Then:
```bash
styrened devices -w 15          # Discover Machine A
styrened status <dest-hash>     # Query its status
styrened send <dest-hash> "hi"  # Send a message
styrened exec <dest-hash> uptime # Run command remotely
```

Watch daemon logs on both sides to observe announces, message delivery, and RPC handling.

## CI/CD

GitHub Actions workflows:
- **pr-validation.yml** - Builds test image, runs smoke tests in kind cluster
- **nightly-build.yml** - Daily multi-arch builds + full test suite
- **release.yml** - Triggered by `v*` tags, builds/pushes to GHCR
- **manual-test.yml** - On-demand with tier selection
