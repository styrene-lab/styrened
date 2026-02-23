# NixOS Deployment Guide

Real hardware deployment notes for styrened on NixOS.

## Quick Start (Nix Flake)

The Nix flake builds successfully and is the recommended installation method on NixOS:

```bash
# Run directly from flake
nix run github:styrene-lab/styrened

# Or build locally
nix build .#default
./result/bin/styrened --version

# Install into profile
nix profile install .#default
```

### NixOS Module

The flake exports a NixOS module for declarative configuration:

```nix
# In your NixOS flake.nix inputs:
inputs.styrened.url = "github:styrene-lab/styrened";

# In your NixOS configuration:
{ inputs, ... }: {
  imports = [ inputs.styrened.nixosModules.default ];
  services.styrened.enable = true;
}
```

### Dev Shell

For development work:

```bash
nix develop
# Provides: python3.11, setuptools, wheel, pytest, mypy, ruff, just
```

### Alternative: pip in venv

If you prefer pip-based installation:

```bash
# Create persistent venv
nix-shell -p python311 python311Packages.pip python311Packages.virtualenv --run "
    python3 -m venv ~/.local/styrene-venv
"

# Install from wheel (for private repos) or git
source ~/.local/styrene-venv/bin/activate
pip install /path/to/styrened-X.Y.Z-py3-none-any.whl

# Or from git (requires auth):
pip install git+https://github.com/styrene-lab/styrened.git@vX.Y.Z
```

## Known Issues

### 1. platformdirs Dependency (FIXED in wheel)

**Issue**: `ModuleNotFoundError: No module named 'platformdirs'`

The `platformdirs` dependency is listed in pyproject.toml but the nix-shell provides its own copy that isn't accessible outside the shell.

**Fix**: Already handled - wheel includes all dependencies. The Nix flake also includes platformdirs in propagatedBuildInputs.

### 2. Config Environment Variable

**Issue**: `STYRENE_CONFIG` is not a valid environment variable.

**Correct variable**: `STYRENE_CONFIG_DIR` - points to directory containing `core-config.yaml`

```bash
export STYRENE_CONFIG_DIR=/path/to/config/dir
styrened daemon
```

### 3. RNS Config Path Override

When using `config_path_override: null` in standalone mode, styrened creates a temporary RNS config in `/tmp/styrened_rns_*`. This works but loses state on reboot.

**For persistent RNS config**: Set `config_path_override` to a real path:
```yaml
reticulum:
  mode: standalone
  config_path_override: /home/styrene/.reticulum
```

## Configuration

Example config for standalone mode with TCP server:

```yaml
# ~/.config/styrene/core-config.yaml
reticulum:
  mode: standalone
  config_path_override: null  # Uses temp dir
  enable_transport: false
  announce_interval: 300
  interfaces:
    auto:
      enabled: true
      group_id: styrene-local
    server:
      enabled: true
      listen_ip: 0.0.0.0
      port: 4242

rpc:
  enabled: true
  relay_mode: false
  allow_command_execution: true
  allowed_commands:
    - uptime
    - hostname
    - uname -a
    - df -h
    - free -h

chat:
  enabled: true
  auto_reply_mode: template
  auto_reply_cooldown: 60
  auto_reply_message: |
    Hello from {hostname}!
    Running styrened {version}
    Uptime: {uptime}

ipc:
  enabled: true
  socket_path: null  # Uses XDG_RUNTIME_DIR

logging:
  level: INFO
```

## Running as Systemd Service

### NixOS Module (Recommended)

```nix
{ inputs, ... }: {
  imports = [ inputs.styrened.nixosModules.default ];
  services.styrened = {
    enable = true;
    # Configuration is read from ~/.config/styrene/core-config.yaml
  };
}
```

### Manual User Service

Create user service (no root required):

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/styrened.service << 'EOF'
[Unit]
Description=Styrene Daemon
After=network.target

[Service]
Type=simple
ExecStart=%h/.nix-profile/bin/styrened daemon
Restart=always
RestartSec=10
Environment=STYRENE_CONFIG_DIR=%h/.config/styrene

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now styrened
systemctl --user status styrened
journalctl --user -u styrened -f
```

## Testing

```bash
# Check identity
styrened identity

# List discovered devices
styrened devices -w 10

# Query another node's status
styrened status <dest-hash> -w 30

# Send message
styrened send <dest-hash> "Hello from NixOS"

# Execute command on remote (if allowed)
styrened exec <dest-hash> uptime
```

## Observed Behavior (v0.3.4 on NixOS 24.11)

**Working**:
- Daemon starts cleanly
- Identity generation and persistence
- RNS initialization (AutoInterface + TCP)
- LXMF router and announcements
- Device discovery (discovered 3000+ nodes on public mesh)
- IPC socket creation at `/run/user/1000/styrened/control.sock`
- Cross-platform discovery (Mac <-> NixOS laptop)

**Not Yet Tested**:
- Full RPC round-trip (status query sent, response pending)
- Command execution over RPC
- Long-term stability
- systemd service integration

## Platform Differences

| Feature | macOS | NixOS |
|---------|-------|-------|
| Config dir | `~/Library/Application Support/styrene` | `~/.local/share/styrene` |
| IPC socket | Not tested | `/run/user/1000/styrened/control.sock` |
| RNS temp config | `/var/folders/.../styrened_rns_*` | `/tmp/styrened_rns_*` |
| Python | System/Homebrew | Nix flake / nix-shell |

## Network Considerations

The NixOS laptop connected to the global Reticulum mesh via TCP transport and discovered thousands of nodes. For isolated testing:

1. Disable TCP transport in RNS config
2. Use only AutoInterface with a unique `group_id`
3. Or use `reticulum.mode: peer` to connect to a local hub only
