# adapter-binary-packaging — Tasks

## 1. Binary manifest + provisioner core
<!-- specs: provisioner -->

- [x] 1.1 Create `src/styrened/data/binary_manifest.json` — schema v1, yggdrasil 0.5.13 + i2pd 2.59.0, 4 platforms each with verified SHA-256 hashes
- [x] 1.2 Create `src/styrened/services/binary_provisioner.py` — BinaryProvisioner class
- [x] 1.3 Platform detection: `detect_platform()` maps uname/sys.platform to manifest keys
- [x] 1.4 Download: async GET via urllib in executor, stream with progress callback, verify archive SHA-256
- [x] 1.5 Extract: `.deb` (ar format parse + data.tar.*), `.tar.gz` (tarfile), `.pkg` (xar+cpio) with path traversal protection
- [x] 1.6 Install to `~/.styrene/bin/`, chmod 755
- [x] 1.7 Error types: `BinaryIntegrityError`, `UnsupportedPlatformError` in `binary_errors.py`
- [x] 1.8 23 unit tests: manifest schema, platform detection, hash verify, extraction, provision flow, error cases

## 2. Startup re-verification + adapter integration
<!-- specs: provisioner -->

- [x] 2.1 Add `security.strict_binary_verification: bool = false` to CoreConfig
- [x] 2.2 Add `verify_binary_integrity()` to DaemonAdapter base — loads manifest, hashes binary, compares
- [x] 2.3 Wire into `_start_managed()` for both I2P and Yggdrasil adapters
- [x] 2.4 Non-strict: log WARNING on mismatch, start anyway
- [x] 2.5 Strict mode: raise `BinaryIntegrityError`, refuse to start
- [x] 2.6 Unit tests: valid hash, tampered hash warns, strict mode raises, missing manifest skips

## 3. Doctor binary checks + --fix provisioning
<!-- specs: provisioner -->

- [x] 3.1 Binary checks in doctor: exists, hash matches, version matches
- [x] 3.2 Report: ✓ found, ⚠ hash mismatch, ✗ not found
- [x] 3.3 `--fix` invokes BinaryProvisioner for missing binaries
- [x] 3.4 Unit tests for all report states and --fix path

## 4. TUI provisioning modal + Settings toggle
<!-- specs: tui-provisioning -->

- [x] 4.1 Adapter enable toggles in Settings Network TRANSPORT panel (Yggdrasil, I2P) with status
- [x] 4.2 ProvisionModal screen: platform info, progress bar, success/error, fallback instructions
- [x] 4.3 Toggle → check binary → if missing mount ProvisionModal → success sets MANAGED
- [x] 4.4 Widget tests for ProvisionModal rendering states (9 tests)

## 5. RPC CMD_PROVISION for remote provisioning
<!-- specs: tui-provisioning -->

- [x] 5.1 CMD_PROVISION = 0x71 with request/response message classes
- [x] 5.2 RPC handler: ADMIN + adapter.provision capability check
- [x] 5.3 `adapter.provision` capability at ADMIN tier in RBAC registry
- [x] 5.4 IPC bridge method `provision_adapter()` (LOCAL, no RBAC)
- [x] 5.5 Unit tests: ADMIN succeeds, OPERATOR rejected, LOCAL bypasses
