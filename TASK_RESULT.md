# Task 1: startup-verification — Result

**Status:** COMPLETE

**Summary:** Implemented startup binary re-verification for managed adapters. Added `SecurityConfig` with `strict_binary_verification` (default false) to `CoreConfig`. Added `verify_binary_integrity()` static method on `DaemonAdapter` base class that loads `binary_manifest.json`, SHA-256 hashes the binary, and compares. Wired into `_start_managed()` for both `YggdrasilAdapter` and `I2PAdapter`. Non-strict mode warns and starts; strict mode raises `BinaryIntegrityError`. Missing manifest entries are skipped gracefully. Created `BinaryIntegrityError` and `UnsupportedPlatformError` in `binary_errors.py`. 17 TDD unit tests all pass.

**Artifacts:**
- `src/styrened/services/binary_errors.py` (new) — BinaryIntegrityError, UnsupportedPlatformError
- `src/styrened/models/config.py` (modified) — SecurityConfig dataclass added
- `src/styrened/services/daemon_adapter.py` (modified) — verify_binary_integrity(), _detect_platform_key()
- `src/styrened/services/yggdrasil.py` (modified) — verification wired into _start_managed(), optional core_config param
- `src/styrened/services/i2p.py` (modified) — verification wired into _start_managed(), optional core_config param
- `tests/unit/test_binary_verification.py` (new) — 17 tests

**Decisions Made:**
- `core_config` is an optional keyword arg on adapter constructors (backward compatible — existing call sites unchanged)
- `verify_binary_integrity()` is a static method for testability (can be called/mocked without instantiation)
- Returns `True`/`False`/`None` tri-state: match/mismatch/skip
- Platform detection via `_detect_platform_key()` static method (reusable by sibling provisioner-core task)

**Assumptions:**
- Sibling task provisioner-core will create `binary_provisioner.py`; `binary_errors.py` created here may need merging
- Existing adapter call sites (daemon.py, cli.py, doctor.py) will pass `core_config=` when verification is desired

**Interfaces Published:**
- `DaemonAdapter.verify_binary_integrity(adapter_name, binary_path, *, manifest_path=None) -> bool | None`
- `DaemonAdapter._detect_platform_key() -> str`
- `SecurityConfig(strict_binary_verification: bool = False)`
- `BinaryIntegrityError(adapter_name, expected, actual)`

**Verification:**
- `python3 -m pytest tests/unit/test_binary_verification.py -v` → 17 passed in 0.24s
- `mypy` on scoped files → 0 errors
- Full unit suite → 3196 passed (16 pre-existing failures, 5 skipped)
- Edge cases: corrupt manifest JSON → skip, missing binary file → skip, missing platform → skip
