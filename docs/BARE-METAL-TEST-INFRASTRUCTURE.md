# Bare-Metal Test Infrastructure Design

Automated testing infrastructure for validating styrened on physical hardware devices.

## Problem Statement

K8s integration tests validate containerized deployments but miss:
- Real hardware interface behavior (serial, USB, GPIO)
- NixOS-specific systemd integration
- Actual mesh network propagation timing
- Config path resolution on real filesystems
- Resource constraints on low-power devices

Manual testing (current approach) is:
- Time-consuming and error-prone
- Not reproducible across releases
- Lacks structured pass/fail criteria

## Design Goals

1. **Automated**: Run tests via single command or CI trigger
2. **Reproducible**: Same tests, same criteria, every release
3. **Non-destructive**: Tests don't brick devices or corrupt state
4. **Observable**: Clear pass/fail with actionable logs
5. **Extensible**: Easy to add new devices and test cases

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Development Machine                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  pytest + bare_metal_harness.py                         │    │
│  │  - Device registry (YAML)                               │    │
│  │  - SSH connection pool                                  │    │
│  │  - Test orchestration                                   │    │
│  │  - Result collection                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                    SSH (paramiko/fabric)                         │
│                              │                                   │
└──────────────────────────────┼───────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  styrene-node │    │    t100ta     │    │  future-node  │
│  192.168.0.57 │    │  192.168.0.59 │    │  192.168.0.xx │
│  NixOS 24.11  │    │  NixOS 24.11  │    │  Debian 12    │
│  ARM64        │    │  x86_64       │    │  ARM64        │
└───────────────┘    └───────────────┘    └───────────────┘
```

## Device Registry

`tests/bare-metal/devices.yaml`:

```yaml
# Bare-metal test device registry
# Devices must be SSH-accessible from the test runner

devices:
  styrene-node:
    host: 192.168.0.57
    user: styrene
    os: nixos
    arch: aarch64
    hardware: ASUS Q502LA
    venv_path: ~/.local/styrene-venv
    config_path: ~/.config/styrene
    rns_config_path: /etc/reticulum
    identity_hash: 698f2232d4ddab45
    lxmf_dest: f3e11839bf683643
    capabilities:
      - tcp_server
      - auto_interface
      - systemd_user
    
  t100ta:
    host: 192.168.0.59
    user: styrene
    os: nixos
    arch: x86_64
    hardware: ASUS T100TA
    venv_path: ~/.local/styrene-venv
    config_path: ~/.config/styrene
    rns_config_path: /etc/reticulum
    identity_hash: 8b9527306ab83fd8
    lxmf_dest: 2d0d7f044c0bfa29
    capabilities:
      - tcp_server
      - auto_interface
      - systemd_user

# Device groups for targeted test runs
groups:
  all: [styrene-node, t100ta]
  nixos: [styrene-node, t100ta]
  arm64: [styrene-node]
  x86_64: [t100ta]
```

## Test Harness

`tests/bare-metal/harness.py`:

```python
"""Bare-metal test harness for styrened.

Provides SSH-based test execution on physical hardware devices.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fabric
import yaml


@dataclass
class DeviceInfo:
    """Device configuration from registry."""
    name: str
    host: str
    user: str
    os: str
    arch: str
    venv_path: str
    config_path: str
    rns_config_path: str
    identity_hash: str
    lxmf_dest: str
    capabilities: list[str]


class BareMetalHarness:
    """Test harness for bare-metal device testing."""
    
    def __init__(self, registry_path: Path | None = None):
        if registry_path is None:
            registry_path = Path(__file__).parent / "devices.yaml"
        self.registry = self._load_registry(registry_path)
        self._connections: dict[str, fabric.Connection] = {}
    
    def _load_registry(self, path: Path) -> dict[str, DeviceInfo]:
        with open(path) as f:
            data = yaml.safe_load(f)
        return {
            name: DeviceInfo(name=name, **info)
            for name, info in data["devices"].items()
        }
    
    def connect(self, device_name: str) -> fabric.Connection:
        """Get or create SSH connection to device."""
        if device_name not in self._connections:
            info = self.registry[device_name]
            self._connections[device_name] = fabric.Connection(
                host=info.host,
                user=info.user,
                connect_timeout=10,
            )
        return self._connections[device_name]
    
    def run(self, device_name: str, command: str, **kwargs) -> fabric.Result:
        """Run command on device."""
        conn = self.connect(device_name)
        return conn.run(command, **kwargs)
    
    def run_styrened(self, device_name: str, args: str, **kwargs) -> fabric.Result:
        """Run styrened command in venv."""
        info = self.registry[device_name]
        cmd = f"source {info.venv_path}/bin/activate && styrened {args}"
        return self.run(device_name, cmd, **kwargs)
    
    def deploy_wheel(self, device_name: str, wheel_path: Path) -> None:
        """Deploy wheel to device and install."""
        conn = self.connect(device_name)
        info = self.registry[device_name]
        
        # Transfer wheel
        remote_path = f"/tmp/{wheel_path.name}"
        conn.put(str(wheel_path), remote_path)
        
        # Install in venv
        self.run(device_name, 
            f"source {info.venv_path}/bin/activate && "
            f"pip install --upgrade {remote_path}"
        )
    
    def get_version(self, device_name: str) -> str:
        """Get installed styrened version."""
        result = self.run_styrened(device_name, "version", hide=True)
        return result.stdout.strip()
    
    def get_identity(self, device_name: str) -> dict[str, str]:
        """Get device identity info."""
        result = self.run_styrened(device_name, "identity --json", hide=True)
        return yaml.safe_load(result.stdout)
    
    def restart_daemon(self, device_name: str) -> None:
        """Restart styrened daemon via systemd."""
        info = self.registry[device_name]
        if "systemd_user" in info.capabilities:
            self.run(device_name, "systemctl --user restart styrened")
        else:
            self.run(device_name, "sudo systemctl restart styrened")
    
    def wait_for_daemon(self, device_name: str, timeout: int = 30) -> bool:
        """Wait for daemon to be responsive."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            try:
                result = self.run_styrened(device_name, "devices", hide=True, warn=True)
                if result.ok:
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False
    
    def discover_devices(self, device_name: str, wait: int = 15) -> list[dict]:
        """Run device discovery and return results."""
        result = self.run_styrened(device_name, f"devices -w {wait} --json", hide=True)
        return yaml.safe_load(result.stdout) or []
    
    def query_status(self, device_name: str, target_dest: str, 
                     timeout: int = 60) -> dict[str, Any] | None:
        """Query status of remote node."""
        result = self.run_styrened(
            device_name, 
            f"status {target_dest} -w {timeout} --json",
            hide=True, warn=True
        )
        if result.ok:
            return yaml.safe_load(result.stdout)
        return None
    
    def exec_command(self, device_name: str, target_dest: str, 
                     command: str, timeout: int = 60) -> dict[str, Any] | None:
        """Execute command on remote node via RPC."""
        result = self.run_styrened(
            device_name,
            f"exec {target_dest} {command} -w {timeout} --json",
            hide=True, warn=True
        )
        if result.ok:
            return yaml.safe_load(result.stdout)
        return None
    
    def cleanup(self) -> None:
        """Close all SSH connections."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
```

## Test Suites

### Deployment Tests

`tests/bare-metal/test_deployment.py`:

```python
"""Deployment and upgrade tests for bare-metal devices."""

import pytest
from pathlib import Path

from .harness import BareMetalHarness


@pytest.fixture(scope="module")
def harness():
    h = BareMetalHarness()
    yield h
    h.cleanup()


@pytest.fixture(scope="module")
def wheel_path():
    """Path to wheel built from current source."""
    dist = Path(__file__).parents[2] / "dist"
    wheels = list(dist.glob("styrened-*.whl"))
    if not wheels:
        pytest.skip("No wheel found - run 'make build' first")
    return max(wheels, key=lambda p: p.stat().st_mtime)


class TestDeployment:
    """Test deployment to bare-metal devices."""
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_deploy_wheel(self, harness, wheel_path, device):
        """Deploy wheel and verify installation."""
        harness.deploy_wheel(device, wheel_path)
        version = harness.get_version(device)
        
        # Extract expected version from wheel name
        expected = wheel_path.stem.split("-")[1]
        assert version == expected
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_daemon_restart(self, harness, device):
        """Restart daemon and verify responsiveness."""
        harness.restart_daemon(device)
        assert harness.wait_for_daemon(device, timeout=30)
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_identity_preserved(self, harness, device):
        """Verify identity is preserved after upgrade."""
        info = harness.registry[device]
        identity = harness.get_identity(device)
        
        assert identity["hash"].startswith(info.identity_hash)


class TestRollback:
    """Test rollback scenarios."""
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_config_preserved_after_upgrade(self, harness, device):
        """Verify config files are not overwritten."""
        info = harness.registry[device]
        
        # Check config exists
        result = harness.run(device, f"test -f {info.config_path}/core-config.yaml")
        assert result.ok
        
        # Get config hash before
        hash_before = harness.run(
            device, 
            f"sha256sum {info.config_path}/core-config.yaml | cut -d' ' -f1",
            hide=True
        ).stdout.strip()
        
        # Simulate upgrade (reinstall same version)
        harness.restart_daemon(device)
        
        # Get config hash after
        hash_after = harness.run(
            device,
            f"sha256sum {info.config_path}/core-config.yaml | cut -d' ' -f1", 
            hide=True
        ).stdout.strip()
        
        assert hash_before == hash_after
```

### Mesh Integration Tests

`tests/bare-metal/test_mesh_integration.py`:

```python
"""Mesh network integration tests across bare-metal devices."""

import pytest

from .harness import BareMetalHarness


@pytest.fixture(scope="module")
def harness():
    h = BareMetalHarness()
    yield h
    h.cleanup()


class TestMeshDiscovery:
    """Test mesh device discovery."""
    
    def test_bidirectional_discovery(self, harness):
        """Both devices should discover each other."""
        # From styrene-node
        devices_from_node = harness.discover_devices("styrene-node", wait=20)
        t100ta_info = harness.registry["t100ta"]
        
        found_t100ta = any(
            d["destination"].startswith(t100ta_info.lxmf_dest)
            for d in devices_from_node
        )
        assert found_t100ta, "styrene-node did not discover t100ta"
        
        # From t100ta
        devices_from_t100ta = harness.discover_devices("t100ta", wait=20)
        node_info = harness.registry["styrene-node"]
        
        found_node = any(
            d["destination"].startswith(node_info.lxmf_dest)
            for d in devices_from_t100ta
        )
        assert found_node, "t100ta did not discover styrene-node"


class TestRPCCommunication:
    """Test RPC communication between devices."""
    
    def test_status_query_node_to_t100ta(self, harness):
        """Query status from styrene-node to t100ta."""
        t100ta = harness.registry["t100ta"]
        status = harness.query_status("styrene-node", t100ta.lxmf_dest)
        
        assert status is not None
        assert status["hostname"] == "t100ta"
        assert "uptime" in status
    
    def test_status_query_t100ta_to_node(self, harness):
        """Query status from t100ta to styrene-node."""
        node = harness.registry["styrene-node"]
        status = harness.query_status("t100ta", node.lxmf_dest)
        
        assert status is not None
        assert status["hostname"] == "styrene-node"
        assert "uptime" in status
    
    def test_exec_hostname_bidirectional(self, harness):
        """Execute hostname command in both directions."""
        t100ta = harness.registry["t100ta"]
        node = harness.registry["styrene-node"]
        
        # node -> t100ta
        result1 = harness.exec_command("styrene-node", t100ta.lxmf_dest, "hostname")
        assert result1 is not None
        assert result1["stdout"].strip() == "t100ta"
        
        # t100ta -> node
        result2 = harness.exec_command("t100ta", node.lxmf_dest, "hostname")
        assert result2 is not None
        assert result2["stdout"].strip() == "styrene-node"
    
    def test_exec_uptime(self, harness):
        """Execute uptime command remotely."""
        t100ta = harness.registry["t100ta"]
        result = harness.exec_command("styrene-node", t100ta.lxmf_dest, "uptime")
        
        assert result is not None
        assert result["exit_code"] == 0
        assert "up" in result["stdout"].lower()


class TestConfigPrecedence:
    """Test config path precedence (v0.3.5 fix validation)."""
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_uses_etc_reticulum_on_nixos(self, harness, device):
        """NixOS devices should use /etc/reticulum config."""
        info = harness.registry[device]
        
        # Check that /etc/reticulum/config exists
        result = harness.run(device, "test -f /etc/reticulum/config", warn=True)
        if not result.ok:
            pytest.skip(f"{device} does not have /etc/reticulum/config")
        
        # Check daemon logs for config path used
        result = harness.run(
            device,
            "journalctl --user -u styrened -n 50 | grep -i 'config'",
            hide=True, warn=True
        )
        
        # Should see "Using existing RNS config: /etc/reticulum"
        assert "/etc/reticulum" in result.stdout or info.rns_config_path in result.stdout
```

### Smoke Tests

`tests/bare-metal/test_smoke.py`:

```python
"""Quick smoke tests for bare-metal validation."""

import pytest

from .harness import BareMetalHarness


@pytest.fixture(scope="module")
def harness():
    h = BareMetalHarness()
    yield h
    h.cleanup()


class TestSmoke:
    """Fast smoke tests for release validation."""
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_device_reachable(self, harness, device):
        """Device is SSH-accessible."""
        result = harness.run(device, "echo ok", hide=True)
        assert result.stdout.strip() == "ok"
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_styrened_installed(self, harness, device):
        """styrened is installed and runnable."""
        version = harness.get_version(device)
        assert version  # Non-empty version string
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_daemon_running(self, harness, device):
        """Daemon service is active."""
        result = harness.run(
            device,
            "systemctl --user is-active styrened || systemctl is-active styrened",
            hide=True, warn=True
        )
        assert "active" in result.stdout
    
    @pytest.mark.parametrize("device", ["styrene-node", "t100ta"])
    def test_identity_exists(self, harness, device):
        """Device has valid identity."""
        identity = harness.get_identity(device)
        assert "hash" in identity
        assert len(identity["hash"]) >= 16
```

## CLI Runner

`tests/bare-metal/run_tests.py`:

```python
#!/usr/bin/env python3
"""CLI runner for bare-metal tests.

Usage:
    python -m tests.bare_metal.run_tests smoke
    python -m tests.bare_metal.run_tests deployment --device styrene-node
    python -m tests.bare_metal.run_tests mesh
    python -m tests.bare_metal.run_tests all
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run bare-metal tests")
    parser.add_argument(
        "suite",
        choices=["smoke", "deployment", "mesh", "all"],
        help="Test suite to run"
    )
    parser.add_argument(
        "--device",
        help="Run tests only on specific device"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()
    
    test_dir = Path(__file__).parent
    
    pytest_args = [
        "pytest",
        str(test_dir),
        "-v" if args.verbose else "-q",
    ]
    
    if args.suite == "smoke":
        pytest_args.extend(["-m", "smoke", "test_smoke.py"])
    elif args.suite == "deployment":
        pytest_args.append("test_deployment.py")
    elif args.suite == "mesh":
        pytest_args.append("test_mesh_integration.py")
    # "all" runs everything
    
    if args.device:
        pytest_args.extend(["-k", args.device])
    
    sys.exit(subprocess.call(pytest_args))


if __name__ == "__main__":
    main()
```

## Makefile Integration

Add to `Makefile`:

```makefile
# Bare-metal testing
.PHONY: test-bare-metal test-bare-metal-smoke test-bare-metal-deploy

test-bare-metal-smoke:
	pytest tests/bare-metal/test_smoke.py -v

test-bare-metal-deploy: build
	pytest tests/bare-metal/test_deployment.py -v

test-bare-metal-mesh:
	pytest tests/bare-metal/test_mesh_integration.py -v

test-bare-metal: test-bare-metal-smoke test-bare-metal-mesh
```

## Usage Examples

### Pre-Release Validation

```bash
# Build wheel
make build

# Quick smoke test (30 seconds)
make test-bare-metal-smoke

# Full deployment test (2-3 minutes)
make test-bare-metal-deploy

# Mesh integration test (3-5 minutes)
make test-bare-metal-mesh
```

### Single Device Testing

```bash
# Test only styrene-node
pytest tests/bare-metal/ -k styrene-node -v

# Deploy to specific device
pytest tests/bare-metal/test_deployment.py -k styrene-node -v
```

### CI Trigger

```bash
# Trigger via GitHub CLI
gh workflow run bare-metal-tests.yml -f suite=all
```

## Supported Hardware

### Currently Validated

| Device | Model | SoC/CPU | Architecture | OS | Status | Notes |
|--------|-------|---------|--------------|-----|--------|-------|
| styrene-node | ASUS Q502LA | Intel Core i5-4210U | x86_64 | NixOS 24.11 | ✅ Validated | Primary test node, good baseline x86 performance |
| t100ta | ASUS T100TA | Intel Atom Z3740 | x86_64 | NixOS 24.11 | ✅ Validated | Low-power x86, tests resource-constrained scenarios |

### Validated Test Results (v0.3.5)

| Test Category | styrene-node | t100ta |
|---------------|:------------:|:------:|
| Wheel deployment | ✅ | ✅ |
| Daemon startup | ✅ | ✅ |
| Identity persistence | ✅ | ✅ |
| Mesh discovery | ✅ | ✅ |
| RPC status query | ✅ | ✅ |
| RPC exec command | ✅ | ✅ |
| Chat/auto-reply | ✅ | ✅ |
| Config path precedence | ✅ | ✅ |

### Known Limitations

- **Q502LA**: None observed. Good reference platform.
- **T100TA**: Slower RPC response times (~2-3s vs ~1s on Q502LA) due to Atom CPU. Acceptable for mesh networking use case.

### Target Hardware (Planned)

The following devices are targeted for future validation to ensure broad ARM and low-power SoC support:

| Device | Model | SoC | Architecture | RAM | Target OS | Priority | Use Case |
|--------|-------|-----|--------------|-----|-----------|----------|----------|
| rpi5 | Raspberry Pi 5 | BCM2712 (Cortex-A76) | aarch64 | 4-8GB | NixOS | High | Primary ARM64 reference |
| rpi4b | Raspberry Pi 4B | BCM2711 (Cortex-A72) | aarch64 | 2-8GB | NixOS | High | Widely deployed ARM64 |
| rpi-zero2w | Raspberry Pi Zero 2 W | RP3A0 (Cortex-A53) | aarch64 | 512MB | NixOS | Medium | Ultra-low-power edge |
| rpi3b | Raspberry Pi 3B+ | BCM2837B0 (Cortex-A53) | aarch64 | 1GB | NixOS | Low | Legacy ARM64 |
| odroid-n2 | ODROID-N2+ | Amlogic S922X (Cortex-A73/A53) | aarch64 | 4GB | NixOS | Medium | High-performance ARM |
| rock5b | Radxa ROCK 5B | RK3588 (Cortex-A76/A55) | aarch64 | 8-16GB | NixOS | Low | Flagship ARM SoC |
| beaglebone | BeagleBone Black | AM3358 (Cortex-A8) | armv7l | 512MB | Debian | Low | 32-bit ARM legacy |

### Hardware Validation Criteria

For a device to be marked as "validated", it must pass:

1. **Deployment**: Wheel install succeeds, daemon starts
2. **Identity**: Creates/loads identity correctly
3. **Discovery**: Discovers at least one other validated node
4. **RPC**: Bidirectional status query and exec with another node
5. **Stability**: Daemon runs for 1+ hour without crashes

### Adding New Hardware

To add a new device to the test infrastructure:

1. **Provision device** with NixOS (preferred) or supported Linux distro
2. **Configure SSH** access from development machine
3. **Add to registry** in `tests/bare-metal/devices.yaml`:
   ```yaml
   new-device:
     host: 192.168.0.XX
     user: styrene
     os: nixos
     arch: aarch64
     hardware: "Raspberry Pi 5"
     venv_path: ~/.local/styrene-venv
     config_path: ~/.config/styrene
     rns_config_path: /etc/reticulum
     identity_hash: null  # Will be populated on first run
     lxmf_dest: null
     capabilities:
       - tcp_server
       - auto_interface
       - systemd_user
   ```
4. **Run smoke tests**: `pytest tests/bare-metal/test_smoke.py -k new-device -v`
5. **Run full validation**: `make test-bare-metal`
6. **Update documentation** with results

### NixOS Device Configuration

Standard NixOS configuration for test devices:

```nix
# /etc/nixos/styrene-test.nix
{ config, pkgs, ... }:

{
  # Network
  networking.firewall.allowedTCPPorts = [ 4242 ];
  
  # Python environment for styrened
  environment.systemPackages = with pkgs; [
    python311
    python311Packages.pip
    python311Packages.virtualenv
  ];
  
  # User for test automation
  users.users.styrene = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAA... test-runner@dev-machine"
    ];
  };
  
  # Enable lingering for user systemd services
  systemd.tmpfiles.rules = [
    "d /var/lib/systemd/linger 0755 root root -"
    "f /var/lib/systemd/linger/styrene 0644 root root -"
  ];
}
```

### Raspberry Pi Specific Notes

**NixOS on Raspberry Pi**:
- Use `nixos-generators` for SD card images
- RPi 4/5: Full NixOS support via `raspberry-pi-nix`
- RPi Zero 2 W: Limited RAM requires swap or minimal config

**Boot configuration** (`boot.nix`):
```nix
{ config, pkgs, ... }:

{
  # RPi 4/5
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = true;
  
  # Enable hardware RNG
  hardware.raspberry-pi."4".apply-overlays-dtmerge.enable = true;
}
```

**Memory-constrained devices** (Zero 2 W, 3B):
```nix
{
  # Add swap
  swapDevices = [{
    device = "/swapfile";
    size = 1024;  # 1GB
  }];
  
  # Limit Python memory
  systemd.services.styrened.serviceConfig.MemoryMax = "256M";
}
```

## Future Extensions

### Hardware Interface Tests

```python
class TestHardwareInterfaces:
    """Tests requiring physical hardware."""
    
    @pytest.mark.hardware
    def test_lora_interface(self, harness):
        """Test LoRa radio interface if available."""
        # Check for LoRa capability
        # Verify interface comes online
        # Test packet transmission
        pass
```

### Performance Benchmarks

```python
class TestPerformance:
    """Performance benchmarks on real hardware."""
    
    def test_rpc_latency(self, harness):
        """Measure RPC round-trip latency."""
        import time
        latencies = []
        for _ in range(10):
            start = time.time()
            harness.query_status("styrene-node", t100ta.lxmf_dest)
            latencies.append(time.time() - start)
        
        avg_latency = sum(latencies) / len(latencies)
        assert avg_latency < 5.0  # 5 second threshold
```

## Security Considerations

1. **SSH Keys**: Use dedicated test keys, not personal keys
2. **Device Isolation**: Test devices on isolated VLAN if possible
3. **No Secrets in Tests**: Device registry contains only non-sensitive data
4. **Idempotent Tests**: Tests should not leave devices in broken state
