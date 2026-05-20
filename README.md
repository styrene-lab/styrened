# styrened

> **Legacy Python daemon notice:** `styrened` was Styrene's first foray into
> Reticulum and LXMF. Some of it was exploratory, vibe-coded prototype work that
> should have been retired the moment it became clear the approach was not a
> sound foundation. It was not retired quickly enough. In particular, legacy
> Meshtastic/MQTT bridge behavior was left in a dangerous state and caused
> harmful spam on public Reticulum transports. That was unacceptable. It was
> irresponsible to the Reticulum community and embarrassing for this project.
>
> The Python daemon is now maintenance-only. Public-network behavior is being
> cut back, rate-limited, and deprecated. The Python Meshtastic/MQTT bridge is
> disabled by a local startup/config poison pill; remove any `meshtastic` or
> `mqtt` bridge sections from old configs. New transport and bridge work belongs
> in [`styrene-rs`](https://github.com/styrene-lab/styrene-rs), not here.

Daemon, library, and TUI for [Reticulum](https://reticulum.network) mesh networks.

## Overview

`styrened` is the core of the [Styrene](https://github.com/styrene-lab) mesh networking stack. It provides a headless daemon for edge devices, a terminal UI for interactive fleet management, and a Python library for building mesh applications on RNS/LXMF.

**Key Features**:
- **Mesh daemon** — headless operation on edge devices (Raspberry Pi, NixOS, containers)
- **Terminal UI** — full-featured TUI for fleet management, chat, device provisioning
- **RPC over LXMF** — remote device management (status, exec, reboot, config)
- **Device discovery** — automatic mesh topology tracking
- **Auto-reply** — automated message responses with cooldown
- **Direct links** — point-to-point RNS links for status queries and speedtests
- **Mesh VPN** — WireGuard tunnels bootstrapped over LXMF (IPv6 ULA addressing)
- **HTTP API** (optional) — REST/WebSocket endpoints for external integration
- **Nix flake** — declarative NixOS deployment with OCI container builds

## Installation

```bash
# Full stack: daemon + TUI (via meta-package)
pip install styrene

# Daemon only (minimal dependencies)
pip install styrened

# Daemon + TUI
pip install styrened[tui]

# All extras
pip install styrened[tui,web,metrics,yubikey]
```

### Nix Flake

```bash
nix run github:styrene-lab/styrened
```

### Container

```bash
docker pull ghcr.io/styrene-lab/styrened:latest
```

## Usage

```bash
# Run daemon
styrened daemon

# Run TUI
styrene

# CLI tools
styrened devices              # List discovered mesh devices
styrened devices -w 10        # Wait 10s for announces
styrened status               # Local daemon health
styrened status <dest>        # Query remote node
styrened send <dest> "hello"  # Send message
styrened exec <dest> uptime   # Remote command execution
styrened doctor               # Installation diagnostics
styrened doctor --setup       # Interactive setup wizard
styrened identity             # Show local identity
```

## Architecture

```
┌──────────────────────────────────────┐
│  styrened                            │
│  ├── tui/          Terminal UI       │  pip install styrened[tui]
│  ├── services/     Business logic    │
│  ├── protocols/    LXMF routing      │
│  ├── rpc/          Remote mgmt       │
│  ├── models/       Data models       │
│  └── web/          HTTP API          │  pip install styrened[web]
├──────────────────────────────────────┤
│  RNS + LXMF (Reticulum Stack)       │
└──────────────────────────────────────┘
```

**Async-first** — all network operations use asyncio. The daemon runs an event loop with periodic tasks for announces, discovery, and mesh maintenance.

**Protocol discrimination** — LXMF messages are routed to handlers based on `fields["protocol"]`, supporting chat (NomadNet/MeshChat), Styrene wire protocol, and VPN handshake messages.

## Configuration

Config file: `~/.styrene/config.yaml`

```yaml
identity:
  display_name: "My Node"

reticulum:
  mode: standalone
  interfaces:
    peers:
      - host: rns.styrene.io
        port: 4242

rpc:
  enabled: true

chat:
  auto_reply_mode: template
  auto_reply_message: "Automated node"

mesh_vpn:
  enabled: false
  gateway: false
```

## Installation Extras

| Extra | Adds |
|-------|------|
| `[tui]` | Terminal UI (textual, psutil) |
| `[web]` | HTTP API (fastapi, uvicorn) |
| `[metrics]` | Prometheus metrics |
| `[yubikey]` | YubiKey authentication |

## Development

```bash
git clone https://github.com/styrene-lab/styrened
cd styrened
pip install -e ".[tui,dev]"

just test-unit    # ~5s, 2200+ tests
just test         # Full suite
make lint         # ruff
make typecheck    # mypy
make validate     # lint + typecheck + test
```

## Related Projects

- **[styrene-rs](https://github.com/styrene-lab/styrene-rs)** — Rust RNS/LXMF implementation (interoperable wire protocol)
- **[styrene-pypi](https://github.com/styrene-lab/styrene-pypi)** — PyPI meta-package (`pip install styrene`)
- **[Reticulum](https://reticulum.network)** — The underlying mesh networking stack

## License

[MIT](LICENSE)
