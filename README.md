# styrened

Headless Styrene daemon for edge deployments on Reticulum mesh networks.

## Overview

`styrened` is a lightweight daemon built on **styrene-core** for running Styrene services without the TUI. Optimized for resource-constrained edge devices and designed for easy deployment via Nix flakes on NixOS.

**Key Features**:
- **Zero UI dependencies** - No textual, minimal footprint
- **RPC server** - Remote device management over LXMF
- **Auto-reply handler** - Respond to mesh messages automatically
- **Device discovery** - Track mesh network topology
- **HTTP API** (optional) - REST endpoints for status/control
- **Nix flake** - Declarative NixOS deployment

## Architecture

```
┌─────────────────────┐
│  styrened           │  ← This package
│  (daemon only)      │
├─────────────────────┤
│  styrene-core       │  ← Headless library
│  (RNS, LXMF, etc.)  │
├─────────────────────┤
│  Reticulum Stack    │
└─────────────────────┘
```

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
from styrened import StyreneDaemon
from styrene_core.services.config import get_default_core_config

config = get_default_core_config()
daemon = StyreneDaemon(config)

import asyncio
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

## Differences from `styrene` (TUI)

| Feature | styrene (TUI) | styrened (daemon) |
|---------|---------------|-------------------|
| **UI** | Textual TUI | Headless only |
| **Dependencies** | +textual, +psutil | styrene-core only |
| **Size** | ~10MB | ~5MB |
| **Use Case** | Interactive | Service/edge |
| **Nix Support** | Python package | Nix flake + module |

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
- styrene-core >= 0.1.0

## Related Projects

- **styrene-core** - Headless RNS/LXMF library
- **styrene** - Terminal UI (depends on styrene-core)

## License

MIT License

## Documentation

Full documentation coming soon.

For now, see:
- [styrene-core docs](https://github.com/styrene-lab/styrene-core)
- [Reticulum docs](https://reticulum.network)
- [LXMF docs](https://github.com/markqvist/LXMF)
