---
id: adapter-binary-packaging
title: "Adapter Binary Packaging &amp; Provisioning Strategy"
status: implemented
parent: operator-interface-testing
tags: [packaging, i2p, yggdrasil, airgap, provisioning]
open_questions: []
branches: ["feature/adapter-binary-packaging"]
openspec_change: adapter-binary-packaging
---

# Adapter Binary Packaging &amp; Provisioning Strategy

## Overview

How styrened acquires, bundles, and manages external daemon binaries (i2pd, yggdrasil) across deployment contexts: pipx pure-Python install, air-gapped single-bundle, and fleet remote provisioning via RPC.

## Research

### Current state audit

**What exists:**
- `I2PAdapter` (304 lines) — fully wired into daemon via `_start_i2p_adapter()`. Config: `I2PConfig` with mode DISABLED/ADOPT/MANAGED. Probes HTTP proxy port, I2PControl API. Generates i2pd.conf. 480s warm-up.
- `YggdrasilAdapter` (335 lines) — **NOT wired into daemon**. Only referenced via `getattr(self, "_ygg_adapter", None)` in announce capabilities. Config: `YggdrasilConfig` (duplicated in both `models/config.py` and `services/yggdrasil.py`). Probes admin socket, supports add_peer. 30s warm-up.
- `DaemonAdapter` base class — abstract lifecycle (start/stop/probe/provision), supervision loop with exponential backoff, warm-up tracking.
- `cmd_setup --enable {yggdrasil,i2p}` — CLI command that runs `provision()` (which only prints install instructions, does NOT install), then sets mode=MANAGED if binary found.
- 181 unit tests — all mocked, no functional verification.
- Neither binary in Nix flake or styrene-edge configs.

**Provisioning model today:** `provision()` is a print-instructions-only stub. The user must manually install binaries via their OS package manager, then run `styrened setup --enable X`. No actual binary acquisition happens.

**Daemon wiring gap:** YggdrasilAdapter exists but daemon never starts it. No `_start_yggdrasil_adapter()` or `_stop_yggdrasil_adapter()` methods.

### Upstream binary availability

**Yggdrasil** (Go, single static binary):
- GitHub releases: .deb (amd64, arm64, armel, armhf, i386, mips, mipsel), .pkg (macOS amd64+arm64), .msi (Windows), vendored source tarball
- Latest: v0.5.13. Go binary → statically linked, no runtime deps
- .deb contains the `yggdrasil` and `yggdrasilctl` binaries — can be extracted without dpkg via `ar x && tar xf data.tar.*`
- Also in nixpkgs, brew, Alpine, Arch, Debian sid

**i2pd** (C++, dynamically linked):
- GitHub releases: .rpm (RHEL/Fedora/Mageia), .deb (Debian bookworm/bullseye/trixie, Ubuntu focal/jammy/noble, Raspberry Pi variants), .tar.gz (macOS)
- Latest: v2.59.0. C++ binary → dynamically linked against libssl, libboost, etc.
- Platform-specific .deb variants (bookworm-rpi for ARM)
- Also in nixpkgs, brew, Arch extra, PPA

**Key difference**: Yggdrasil is a single static Go binary (trivial to bundle). i2pd is C++ with shared library deps (needs distro-matched .deb or static build from source).

**For air-gapped bundles**: Yggdrasil is easy — extract binary from .deb, ship it. i2pd is harder — need either a static build, the matching .deb for the target distro, or use the Nix closure which captures all deps.

**For online acquisition**: Both have GitHub releases with predictable URLs. Yggdrasil .deb can be extracted rootlessly. i2pd .deb needs dpkg or ar+tar extraction, plus shared libraries.

### Deployment contexts and their constraints

**Three deployment personas:**

1. **Developer / Desktop operator** — `pipx install styrene`, macOS or Linux desktop, internet access, has brew/nix/apt. Wants to enable I2P/Ygg from the TUI with minimal friction. Root access available.

2. **Edge fleet device** — Raspberry Pi 4B/Zero 2W, NixOS via styrene-edge, potentially air-gapped (rural/maritime/tactical), no internet after initial provisioning. Admin provisions via RPC from a connected device. ARM arch. Minimal storage (8-32GB SD card).

3. **Container / K8s** — OCI image on brutus cluster, x86_64, internet access but prefer deterministic builds. i2pd/yggdrasil as sidecar containers or baked into image. Root inside container.

**Footprint constraints (edge devices):**
- Pi Zero 2W: 512MB RAM, Cortex-A53 quad-core
- SD card: 8-32GB, slow writes
- Power: possibly solar/battery, must minimize disk I/O
- Yggdrasil binary: ~15MB (Go static)
- i2pd binary: ~8MB + shared libs (~30MB total with deps)
- styrened itself: ~5MB wheel + Python runtime (~100MB via Nix or pyenv)

### Proposed architecture: three-tier provisioning

**Tier 1: Nix (air-gapped first-class)**
The Nix flake already builds the OCI image. Add i2pd and yggdrasil as optional Nix inputs. `nix build .#styrened-full` produces a closure with all three binaries. `nix bundle` or `nix copy --to file:///path` creates a portable archive. styrene-edge NixOS configs add the packages to `environment.systemPackages`. This is the air-gap path — `nix copy` the closure to a USB stick, `nix copy --from` on the target device.

**Tier 2: Binary provisioner (online pipx users)**
A new `BinaryProvisioner` service that downloads upstream release assets from GitHub, verifies SHA-256, extracts the binary, and places it in `~/.styrene/bin/`. Steps:
1. Detect platform (uname -m, /etc/os-release)
2. Map to upstream asset name (e.g., `yggdrasil-0.5.13-arm64.deb`)
3. Download from GitHub releases API
4. Verify SHA-256 against a manifest shipped in styrened (updated each release)
5. Extract binary (ar+tar for .deb, tar for .tar.gz)
6. Install to `~/.styrene/bin/{yggdrasil,i2pd}` (no root required)
7. `chmod 755`, update config mode to MANAGED

`~/.styrene/bin/` is added to the adapter's binary search path (before system PATH, after explicit config override).

**Tier 3: OS package manager (fallback)**
Current behavior — print instructions for `brew install`, `apt install`, `nix profile install`. Kept as documentation/fallback when Tier 2 fails or user prefers system packages.

**Exposure:**
- CLI: `styrened setup --enable yggdrasil` (exists, upgrade to use BinaryProvisioner)
- TUI: Settings → Network → Transport section, "Enable Yggdrasil" button → progress modal
- RPC: `CMD_PROVISION` (0x71) with `{"adapter": "yggdrasil", "source": "online"|"bundle"}`, gated by OPERATOR capability
- IPC: Bridge method `provision_adapter()` for TUI consumption

**SHA-256 manifest:**
Ship `src/styrened/data/binary_manifest.json` with known-good hashes per version × platform. Updated when we bump adapter version support. Example:
```json
{
  "yggdrasil": {
    "version": "0.5.13",
    "assets": {
      "linux-amd64": {"asset": "yggdrasil-0.5.13-amd64.deb", "sha256": "abc..."},
      "linux-arm64": {"asset": "yggdrasil-0.5.13-arm64.deb", "sha256": "def..."},
      "darwin-arm64": {"asset": "yggdrasil-0.5.13-macos-arm64.pkg", "sha256": "ghi..."}
    }
  }
}
```

### Q5 deep dive: local authority vs remote RBAC

**The naming collision:** "OPERATOR" is both an RBAC role (tier 30, between MONITOR and ADMIN) and the word we use for "the human using the TUI." This creates confusion:
- "The operator can provision adapters" — which operator? RBAC Role.OPERATOR, or the person sitting at the keyboard?
- The human at the keyboard should have full authority over their own device. They installed it. It's theirs.

**Current role hierarchy:**
BLOCKED(0) → NONE(1) → PEER(10) → MONITOR(20) → OPERATOR(30) → ADMIN(40)

- PEER: chat, browse, ping, status
- MONITOR: inbox_read, web_read, datalink
- OPERATOR: config_update, terminal_restricted, web_write
- ADMIN: exec, reboot, self_update, terminal_full

**The insight:** There are two authority contexts:
1. **Local authority** — the process owner. Always has full access to their own daemon. Not an RBAC role; it's a privilege level derived from "am I running on this machine?"
2. **Remote authority** — an external peer making requests over RNS/LXMF. Governed by the RBAC role assigned to their identity hash.

**Proposal — LOCAL as implicit super-role:**
- IPC commands (Unix socket, localhost) are inherently LOCAL. The TUI connects via IPC → LOCAL authority.
- RPC commands (over LXMF from remote peers) are checked against the RBAC roster → role-gated.
- LOCAL bypasses all RBAC checks. It's not a role in the roster; it's a privilege context.
- This is how it already works — IPC handlers don't check RBAC. The question is whether to formalize it.

**On renaming OPERATOR:** The role hierarchy is well-established across 60+ RBAC tests. Renaming is high churn for unclear benefit. Instead, disambiguate in docs:
- "operator" (lowercase) = the human using styrened
- "OPERATOR" (caps/enum) = RBAC role tier 30
- "LOCAL" = the implicit privilege context for IPC/TUI access

**Provisioning RPC capability:** `adapter.provision` at ADMIN tier (40). Rationale: provisioning installs binaries and changes daemon behavior — this is fleet management, not casual self-service. The local operator always has it via LOCAL context. Remote provisioning is an ADMIN-only fleet operation.

### Q6 deep dive: binary integrity verification

**Threat model:**
The BinaryProvisioner downloads executables from the internet and runs them as child processes. If an attacker can MITM the download or compromise the GitHub release, they get code execution on the operator's device — or worse, on an entire fleet via RPC provisioning.

**Attack vectors:**
1. **DNS/BGP hijack of GitHub** — unlikely but possible for state actors. HTTPS + certificate pinning mitigates.
2. **Compromised upstream release** — upstream maintainer account takeover or supply chain attack on the build pipeline. This happened to xz-utils (CVE-2024-3094). Neither i2pd nor yggdrasil has reproducible builds.
3. **Compromised styrened manifest** — if an attacker can modify `binary_manifest.json` in our repo, they can substitute hashes. Mitigated by our own release signing.
4. **Local tampering** — binaries in `~/.styrene/bin/` modified after download. Mitigated by re-verification on daemon start.

**Defense layers:**

Layer 1 — **SHA-256 manifest (baseline, always):**
Ship `src/styrened/data/binary_manifest.json` with known-good hashes. On download, verify before extraction. On daemon start, optionally re-verify if `security.verify_binaries = true` in config (default: true for managed, false for adopted).

Format:
```json
{
  "schema_version": 1,
  "adapters": {
    "yggdrasil": {
      "version": "0.5.13",
      "upstream_repo": "yggdrasil-network/yggdrasil-go",
      "platforms": {
        "linux-amd64": {
          "asset": "yggdrasil-0.5.13-amd64.deb",
          "sha256": "abc123...",
          "binary_path_in_archive": "usr/bin/yggdrasil",
          "binary_sha256": "def456..."
        }
      }
    }
  }
}
```

Note: two SHA-256 values — one for the downloaded archive, one for the extracted binary itself. The archive hash prevents download tampering; the binary hash enables re-verification on startup without keeping the archive around.

Layer 2 — **Upstream release signature verification (aspirational):**
Yggdrasil signs releases with a GPG key (Ed Holbrook, 0x...). i2pd does not consistently sign. We could verify Yggdrasil GPG sigs if available, but this adds complexity (GPG keyring management, key rotation). Deferred — SHA-256 is sufficient for our threat model.

Layer 3 — **Startup re-verification:**
When the daemon starts with mode=MANAGED, hash the binary at the configured path against the manifest's `binary_sha256`. If mismatch:
- Log a WARNING with the expected vs actual hash
- If `security.strict_binary_verification = true`: refuse to start the adapter
- If false (default): start anyway but set a `tampered_binary` flag visible in status/doctor

This catches local tampering and accidental binary replacement (e.g., system package manager updated yggdrasil to a version we haven't vetted).

Layer 4 — **Doctor integration:**
`styrened doctor` checks:
- Binary exists at expected path
- Binary hash matches manifest
- Binary version matches expected version (run `yggdrasil -version`, `i2pd --version`)
- Warm-up status for managed instances

**What we skip and why:**
- No GPG verification — adds keyring management complexity, upstream key rotation risk, and i2pd doesn't consistently sign. SHA-256 against known-good hashes from our reviewed manifest is sufficient.
- No certificate pinning — HTTPS to GitHub is already good enough; pinning adds maintenance burden when GitHub rotates certs.
- No code signing of our own manifest — our release process (Argo CI → tagged release → PyPI) already establishes the trust chain. If someone can modify our source, they can modify anything.

**Air-gap specific concern:**
In air-gapped deployments, binaries arrive via USB stick or Nix closure. The Nix store provides its own integrity (content-addressed paths). For non-Nix bundles, the SHA-256 manifest verifies the extracted binaries against the same hashes as online downloads. The trust anchor is the styrened version that shipped with the bundle.

## Decisions

### Decision: Q1: Nix closure as primary air-gap format

**Status:** decided
**Rationale:** Nix handles deps, arch, reproducibility. OCI image variant bakes binaries in. Platform-specific tar.gz as secondary for non-Nix environments.

### Decision: Q2: Download from upstream GitHub releases

**Status:** decided
**Rationale:** No mirror to maintain. Predictable URLs. Yggdrasil trivial (static Go). i2pd needs distro-matched .deb or macOS tarball.

### Decision: Q3: ~/.styrene/bin/ primary, system PATH as adopt

**Status:** decided
**Rationale:** Binary search order: (1) config.binary_path explicit override, (2) ~/.styrene/bin/, (3) system PATH via shutil.which(). If the system already has yggdrasil/i2pd installed, ADOPT mode uses it in-place — good ecosystem citizen. BinaryProvisioner defaults to ~/.styrene/bin/ but can be told to install system-wide with --system flag (requires appropriate permissions).

### Decision: Q5: LOCAL implicit super-role, provisioning at ADMIN tier for remote

**Status:** decided
**Rationale:** IPC (TUI/CLI) is LOCAL context — bypasses RBAC, full authority. Remote provisioning via RPC is ADMIN-tier (installs binaries, changes daemon behavior = fleet management). No rename of OPERATOR role — disambiguate via convention: lowercase 'operator' = human, caps 'OPERATOR' = role tier 30. New capability: adapter.provision at ADMIN tier.

### Decision: Q6: SHA-256 manifest with startup re-verification

**Status:** decided
**Rationale:** Four defense layers: (1) SHA-256 manifest in source with archive + extracted binary hashes, verified on download. (2) Upstream GPG deferred — inconsistent across projects, adds keyring complexity. (3) Startup re-verification — hash binary against manifest on daemon start, warn or refuse based on strict mode config. (4) Doctor integration — binary existence, hash, version checks. Air-gapped bundles verified against same manifest. Trust anchor is the styrened release itself.

### Decision: Binary search order: config override → ~/.styrene/bin/ → PATH → Nix store

**Status:** decided
**Rationale:** Explicit config is highest priority (operator knows best). ~/.styrene/bin/ is user-local provisioned binaries (no root). System PATH enables ADOPT mode for system-installed binaries. Nix store is fallback for NixOS/nix-profile installs.

### Decision: Q4: 4-arch matrix, oversupport rather than undersupport

**Status:** decided
**Rationale:** Manifest covers linux/amd64, linux/arm64, linux/armhf, darwin/arm64. armhf included despite styrene-edge targeting aarch64 NixOS — valid target for 32-bit Raspbian users. Nix handles the happy path for most instances; the SHA-256 manifest matters for Tier 2 (BinaryProvisioner) downloads. darwin/amd64 omitted (dying platform, brew covers it if needed).

### Decision: Q7: Settings toggle + doctor --fix combo

**Status:** decided
**Rationale:** Primary path: Settings → Network → Transport panel toggle. When enabled and binary not found, progress modal handles download/extract/verify/install to ~/.styrene/bin/. Diagnostic path: styrened doctor detects missing binary, offers --fix acquisition. Forge-like dedicated widget rejected as overkill for single-binary downloads.

## Open Questions

*No open questions.*
