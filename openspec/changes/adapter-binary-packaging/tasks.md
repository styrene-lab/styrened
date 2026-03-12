# adapter-binary-packaging — Tasks

## 1. Binary manifest + provisioner core
<!-- specs: provisioner -->
<!-- scope: src/styrened/data/binary_manifest.json, src/styrened/services/binary_provisioner.py, tests/unit/test_binary_provisioner.py -->

- [ ] 1.1 Create `src/styrened/data/binary_manifest.json` with schema_version=1, yggdrasil 0.5.13 + i2pd 2.59.0 entries, 4 platforms each (linux-amd64, linux-arm64, linux-armhf, darwin-arm64) with archive SHA-256 and extracted binary SHA-256
- [ ] 1.2 Create `src/styrened/services/binary_provisioner.py` — BinaryProvisioner class with `detect_platform()`, `provision(adapter_name, on_progress=None)`, `verify_binary(adapter_name)` methods
- [ ] 1.3 Platform detection: map `platform.machine()` + `sys.platform` to manifest keys
- [ ] 1.4 Download: GET upstream GitHub release asset URL, stream with progress callback, verify archive SHA-256
- [ ] 1.5 Extract: `.deb` via `ar x` + `tar xf data.tar.*`, `.tar.gz` via tarfile, `.pkg` via xar+cpio
- [ ] 1.6 Install to `~/.styrene/bin/`, chmod 755
- [ ] 1.7 Error types: `BinaryIntegrityError`, `UnsupportedPlatformError` in new `src/styrened/services/binary_errors.py`
- [ ] 1.8 Unit tests (TDD): manifest schema validation, platform detection, SHA-256 verify pass/fail, unsupported platform error, progress callback shape. All downloads mocked.

## 2. Startup re-verification + adapter integration
<!-- specs: provisioner -->
<!-- scope: src/styrened/services/daemon_adapter.py, src/styrened/services/yggdrasil.py, src/styrened/services/i2p.py, src/styrened/models/config.py, tests/unit/test_binary_verification.py -->

- [ ] 2.1 Add `security.strict_binary_verification: bool = false` to CoreConfig
- [ ] 2.2 Add `verify_binary_integrity(adapter_name, binary_path)` to DaemonAdapter base — loads manifest, hashes binary, compares against `binary_sha256`
- [ ] 2.3 Wire into `_start_managed()` for both I2P and Yggdrasil adapters: verify before subprocess launch
- [ ] 2.4 Non-strict (default): log WARNING on mismatch, start anyway
- [ ] 2.5 Strict mode: raise `BinaryIntegrityError`, refuse to start
- [ ] 2.6 Unit tests: valid hash passes, tampered hash warns, strict mode raises, missing manifest entry skips gracefully

## 3. Doctor binary checks + --fix provisioning
<!-- specs: provisioner -->
<!-- scope: src/styrened/services/doctor.py, tests/unit/test_doctor_binary.py -->

- [ ] 3.1 Add binary checks to doctor: binary exists, hash matches manifest, version matches (run binary --version)
- [ ] 3.2 Report: ✓ found + matches, ⚠ hash mismatch, ✗ not found
- [ ] 3.3 `--fix` mode: invoke BinaryProvisioner.provision() for missing binaries, report ✓ installed on success
- [ ] 3.4 Unit tests: all three report states, --fix invocation path

## 4. TUI provisioning modal + Settings toggle
<!-- specs: tui-provisioning -->
<!-- scope: src/styrened/tui/screens/settings.py, src/styrened/tui/screens/provision_modal.py, tests/tui/widgets/test_provision_modal.py -->

- [ ] 4.1 Add adapter enable toggles to Settings Network tab TRANSPORT panel (Yggdrasil, I2P) with status indicator
- [ ] 4.2 Create `ProvisionModal` screen: platform info, progress bar, success/error states, fallback install instructions
- [ ] 4.3 Wire toggle → check binary → if missing, mount ProvisionModal → on success, set mode=MANAGED and save config
- [ ] 4.4 Widget tests for ProvisionModal rendering states

## 5. RPC CMD_PROVISION for remote provisioning
<!-- specs: tui-provisioning -->
<!-- scope: src/styrened/rpc/server.py, src/styrened/rpc/messages.py, src/styrened/ipc/messages.py, src/styrened/ipc/handlers.py, tests/unit/test_rpc_provision.py -->

- [ ] 5.1 Add `CMD_PROVISION = 0x71` to RPC message types with request/response classes
- [ ] 5.2 RPC handler: validate ADMIN role + `adapter.provision` capability, invoke BinaryProvisioner, return result
- [ ] 5.3 Add `adapter.provision` capability to ADMIN tier in RBAC capability registry
- [ ] 5.4 IPC bridge method `provision_adapter()` for TUI consumption (LOCAL context, no RBAC check)
- [ ] 5.5 Unit tests: ADMIN succeeds, OPERATOR rejected, LOCAL bypasses RBAC
