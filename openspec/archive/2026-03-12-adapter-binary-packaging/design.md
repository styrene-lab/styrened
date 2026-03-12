# adapter-binary-packaging — Design

## Spec-Derived Architecture

### provisioner

- **Binary manifest ships with styrened source** (added) — 2 scenarios
- **BinaryProvisioner acquires binaries from upstream GitHub releases** (added) — 5 scenarios
- **Startup binary re-verification** (added) — 3 scenarios
- **Doctor checks binary status** (added) — 3 scenarios

### tui-provisioning

- **Settings Network tab shows adapter enable toggles** (added) — 2 scenarios
- **Provisioning modal shows download progress** (added) — 2 scenarios
- **RPC CMD_PROVISION for remote binary provisioning** (added) — 3 scenarios

## File Changes

### New files
| Path | Purpose |
|------|---------|
| `src/styrened/data/binary_manifest.json` | SHA-256 manifest for known-good adapter binaries (schema v1) |
| `src/styrened/services/binary_provisioner.py` | BinaryProvisioner — detect platform, download, verify, extract, install |
| `src/styrened/services/binary_errors.py` | Error types: BinaryIntegrityError, UnsupportedPlatformError |
| `src/styrened/tui/screens/provision_modal.py` | TUI modal: download progress, success/error states |
| `tests/unit/test_binary_provisioner.py` | Unit tests for provisioner core |
| `tests/unit/test_binary_verification.py` | Unit tests for startup re-verification |
| `tests/unit/test_doctor_binary.py` | Unit tests for doctor binary checks |
| `tests/unit/test_rpc_provision.py` | Unit tests for RPC CMD_PROVISION |
| `tests/tui/widgets/test_provision_modal.py` | Widget tests for provision modal |

### Modified files
| Path | Purpose |
|------|---------|
| `src/styrened/services/daemon_adapter.py` | Add `verify_binary_integrity()` method to base class |
| `src/styrened/services/yggdrasil.py` | Wire startup verification into `_start_managed()` |
| `src/styrened/services/i2p.py` | Wire startup verification into `_start_managed()` |
| `src/styrened/services/doctor.py` | Add binary presence/integrity/version checks + --fix provisioning |
| `src/styrened/models/config.py` | Add `security.strict_binary_verification` field |
| `src/styrened/models/rbac.py` | Add `adapter.provision` capability at ADMIN tier |
| `src/styrened/rpc/server.py` | Add CMD_PROVISION handler |
| `src/styrened/rpc/messages.py` | Add CMD_PROVISION request/response types |
| `src/styrened/ipc/messages.py` | Add IPC provision message types |
| `src/styrened/ipc/handlers.py` | Add provision handler (LOCAL context) |
| `src/styrened/tui/screens/settings.py` | Add adapter toggles to Network tab TRANSPORT panel |

## Key Decisions

1. **Three-tier provisioning**: Nix closure (air-gap) → BinaryProvisioner (online) → OS package manager (fallback)
2. **Dual SHA-256**: Archive hash verified on download, binary hash verified on startup
3. **Non-strict default**: Startup verification warns on mismatch but doesn't block (configurable)
4. **LOCAL bypasses RBAC**: TUI/CLI provisioning is unrestricted; remote RPC requires ADMIN + `adapter.provision`
5. **4-arch matrix**: linux-amd64, linux-arm64, linux-armhf, darwin-arm64
6. **Binary search order**: config override → `~/.styrene/bin/` → system PATH → Nix store (already implemented)
