# provisioner — Delta Spec

## ADDED Requirements

### Requirement: Binary manifest ships with styrened source

A JSON manifest at `src/styrened/data/binary_manifest.json` defines known-good adapter binaries with version, upstream repo, and per-platform SHA-256 hashes for both archive and extracted binary.

#### Scenario: Manifest schema is valid and complete

Given the manifest file exists at `src/styrened/data/binary_manifest.json`
When the manifest is loaded as JSON
Then it has a `schema_version` field equal to 1
And it has an `adapters` object with keys `yggdrasil` and `i2pd`
And each adapter entry has `version`, `upstream_repo`, and `platforms` fields
And each platform entry has `asset`, `sha256`, `binary_path_in_archive`, and `binary_sha256` fields

#### Scenario: All target architectures are covered

Given the manifest is loaded
When the platforms for each adapter are inspected
Then `yggdrasil` has entries for `linux-amd64`, `linux-arm64`, `linux-armhf`, and `darwin-arm64`
And `i2pd` has entries for `linux-amd64`, `linux-arm64`, `linux-armhf`, and `darwin-arm64`

### Requirement: BinaryProvisioner acquires binaries from upstream GitHub releases

A `BinaryProvisioner` class in `src/styrened/services/binary_provisioner.py` detects the local platform, downloads the correct asset from GitHub releases, verifies SHA-256, extracts the binary, and installs it to `~/.styrene/bin/`.

#### Scenario: Platform detection maps to manifest key

Given BinaryProvisioner is instantiated
When `detect_platform()` is called on a linux/amd64 host
Then the result is `"linux-amd64"`

#### Scenario: Successful download and install

Given BinaryProvisioner targets adapter `"yggdrasil"`
And the platform is `"linux-amd64"`
And the manifest has a matching entry with a valid SHA-256
When `provision("yggdrasil")` is called
Then the asset is downloaded from the upstream GitHub release URL
And the downloaded archive SHA-256 matches the manifest's `sha256` field
And the binary is extracted to `~/.styrene/bin/yggdrasil`
And the extracted binary SHA-256 matches the manifest's `binary_sha256` field
And the binary is executable (mode 755)

#### Scenario: SHA-256 mismatch aborts install

Given BinaryProvisioner targets adapter `"yggdrasil"`
And the downloaded archive SHA-256 does NOT match the manifest
When `provision("yggdrasil")` is called
Then a `BinaryIntegrityError` is raised
And no file is written to `~/.styrene/bin/`

#### Scenario: Unsupported platform raises clear error

Given BinaryProvisioner runs on a platform not in the manifest (e.g. `linux-riscv64`)
When `provision("yggdrasil")` is called
Then an `UnsupportedPlatformError` is raised with a message naming the platform

#### Scenario: Progress callback during download

Given BinaryProvisioner is called with an `on_progress` callback
When the download proceeds
Then `on_progress(bytes_downloaded, total_bytes)` is called periodically
And the final call has `bytes_downloaded == total_bytes`

### Requirement: Startup binary re-verification

When a daemon adapter starts in MANAGED mode, it verifies the binary at the configured path against the manifest's `binary_sha256` before launching the subprocess.

#### Scenario: Valid binary passes verification

Given yggdrasil binary at `~/.styrene/bin/yggdrasil` matches the manifest hash
When `YggdrasilAdapter.start()` is called in MANAGED mode
Then the adapter starts normally

#### Scenario: Tampered binary logs warning

Given yggdrasil binary at `~/.styrene/bin/yggdrasil` does NOT match the manifest hash
And `security.strict_binary_verification` is false (default)
When `YggdrasilAdapter.start()` is called in MANAGED mode
Then a WARNING is logged with expected and actual hashes
And the adapter starts anyway

#### Scenario: Strict mode refuses tampered binary

Given yggdrasil binary does NOT match the manifest hash
And `security.strict_binary_verification` is true
When `YggdrasilAdapter.start()` is called in MANAGED mode
Then a `BinaryIntegrityError` is raised
And the adapter does NOT start

### Requirement: Doctor checks binary status

`styrened doctor` inspects adapter binary presence, integrity, and version.

#### Scenario: Doctor reports missing binary

Given yggdrasil is configured with mode=MANAGED
And no yggdrasil binary exists on the system
When `styrened doctor` runs
Then output contains `✗ yggdrasil binary not found`

#### Scenario: Doctor reports hash mismatch

Given yggdrasil binary exists but SHA-256 does not match manifest
When `styrened doctor` runs
Then output contains `⚠ yggdrasil binary hash mismatch`

#### Scenario: Doctor --fix triggers provisioning

Given yggdrasil binary is missing
When `styrened doctor --fix` runs
Then BinaryProvisioner is invoked for yggdrasil
And on success, output contains `✓ yggdrasil installed`
