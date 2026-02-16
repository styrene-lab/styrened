# styrened

Headless Styrene daemon for edge deployments on Reticulum mesh networks.

## Overview

`styrened` is the Styrene daemon and library for Reticulum mesh networks. It provides both headless daemon functionality for edge devices and the core library used by styrene-tui. Optimized for resource-constrained edge devices and designed for easy deployment via Nix flakes on NixOS.

**Key Features**:
- **Zero UI dependencies** - No textual, minimal footprint
- **RPC server** - Remote device management over LXMF
- **Auto-reply handler** - Respond to mesh messages automatically
- **Device discovery** - Track mesh network topology
- **HTTP API** (optional) - REST endpoints for status/control
- **Nix flake** - Declarative NixOS deployment

## Architecture

```
┌──────────────────┐
│  styrene-tui     │  ← Terminal UI (optional)
├──────────────────┤
│  styrened        │  ← This package: daemon + library
│  (RNS, LXMF,     │
│   protocols,     │
│   services)      │
├──────────────────┤
│  Reticulum Stack │
└──────────────────┘
```

`styrened` serves two purposes:
1. **As a library** - Provides RNS/LXMF services, protocols, and models used by styrene-tui
2. **As a daemon** - Runs headless on edge devices for fleet management

## Installation

### PyPI

```bash
pip install styrened
```

### Nix Flake

```bash
# Run directly
nix run github:styrene-lab/styrened

# Or add to your flake.nix
{
  inputs.styrened.url = "github:styrene-lab/styrened";

  outputs = { self, nixpkgs, styrened }: {
    # ...
  };
}
```

### NixOS Module

```nix
# configuration.nix
{
  inputs.styrened.url = "github:styrene-lab/styrened";

  # ...

  services.styrened = {
    enable = true;
    # user = "styrened";  # Optional: custom user
  };
}
```

### Containers / Kubernetes

OCI container images are published to GitHub Container Registry (built via nix2container):

```bash
# Production image
docker pull ghcr.io/styrene-lab/styrened:latest
docker pull ghcr.io/styrene-lab/styrened:0.4.0

# Edge builds (main branch)
docker pull ghcr.io/styrene-lab/styrened:edge

# Test images (includes test dependencies)
docker pull ghcr.io/styrene-lab/styrened-test:latest
```

**Supported platforms**: `linux/amd64`

**Run container:**
```bash
docker run -d \
  --name styrened \
  -v ~/.styrene:/config \
  -v styrene-data:/data \
  ghcr.io/styrene-lab/styrened:latest
```

**Available tags:**
- `latest` - Latest stable release (production image)
- `edge` - Latest main branch build (production image)
- `v0.2.1` - Specific release version
- `<commit-sha>` - Build from specific commit

See [tests/k8s/helm/styrened-test](tests/k8s/helm/styrened-test) for Kubernetes deployment examples.

### Building from Source

For local builds and development:

```bash
# Build production OCI image (via Nix)
just build

# Build test OCI image
just build-test

# Show version information
just version
```

See [CONTAINERS.md](CONTAINERS.md) for complete build pipeline documentation, including:
- Nix OCI build pipeline (nix2container)
- Pushing to GitHub Container Registry
- CI/CD integration
- Troubleshooting

## Usage

### Command Line

```bash
# Run daemon with default config
styrened

# Or via Python module
python -m styrened
```

### Configuration

Config file: `~/.styrene/config.yaml` (or `/etc/styrene/config.yaml` for system-wide)

```yaml
reticulum:
  mode: client
  transport_enabled: false

rpc:
  enabled: true
  authorized_operators:
    - identity_hash: "abc123..."
      role: operator

discovery:
  announce_interval: 300

chat:
  auto_reply_enabled: true
  auto_reply_message: "This is an automated system"

api:
  enabled: false
  host: "0.0.0.0"
  port: 8000
```

### Programmatic Usage

```python
import asyncio
from styrened import StyreneDaemon
from styrened.services.config import get_default_config

config = get_default_config()
daemon = StyreneDaemon(config)

asyncio.run(daemon.start())
```

## Features

### RPC Server

Handles incoming LXMF messages for remote device management:

- **status_request** - CPU, memory, disk, network stats
- **exec** - Execute whitelisted commands
- **reboot** - Schedule system reboot
- **update_config** - Update configuration remotely

### Auto-Reply

Automatically responds to LXMF messages from NomadNet/MeshChat users.

### Device Discovery

Listens for RNS announces and tracks discovered devices.

### HTTP API (Optional)

REST endpoints for status and control (when `api.enabled: true`).

## Deployment Scenarios

### Edge Device (NixOS)

```nix
# Minimal edge node configuration
services.styrened = {
  enable = true;
};
```

### Mesh Gateway

```yaml
# Gateway config
reticulum:
  mode: gateway
  transport_enabled: true

rpc:
  enabled: true
```

### Monitoring Node

```yaml
# Discovery-focused config
discovery:
  announce_interval: 60

api:
  enabled: true
  port: 8000
```

## Differences from `styrene-tui`

| Feature | styrene-tui | styrened |
|---------|-------------|----------|
| **UI** | Textual TUI | Headless only |
| **Dependencies** | +textual, +psutil | Minimal (RNS, LXMF, msgpack) |
| **Use Case** | Interactive operator | Service/edge device |
| **Nix Support** | Python package | Nix flake + module |

Both packages share the same underlying library code (protocols, services, models) which lives in styrened.

## Development

```bash
# Clone repository
git clone https://github.com/styrene-lab/styrened
cd styrened

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## Requirements

- Python 3.11+
- RNS (Reticulum Network Stack)
- LXMF
- msgpack

## Related Projects

- **[styrene-tui](https://github.com/styrene-lab/styrene-tui)** - Terminal UI for interactive operation
- **[styrene](https://github.com/styrene-lab/styrene)** - Organization docs and research

## License

MIT License

## Documentation

### API Reference

Auto-generated API documentation is available at:

**[styrene-lab.github.io/styrened](https://styrene-lab.github.io/styrened/)**

The API reference is built from source using [pdoc](https://pdoc.dev) and updated automatically on each release.

#### Generate Locally

```bash
# Install docs dependencies
pip install -e ".[docs]"

# Generate static docs to docs/api/
just docs

# Serve with live reload for development
just docs-serve
```

### Related Documentation

- [Reticulum docs](https://reticulum.network)
- [LXMF docs](https://github.com/markqvist/LXMF)
