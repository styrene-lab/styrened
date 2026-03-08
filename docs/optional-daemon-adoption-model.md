---
id: optional-daemon-adoption-model
title: Optional Daemon Adoption Model — three-tier pattern
status: implementing
parent: overlay-network-integration
tags: [architecture, pattern, yggdrasil, i2p, nix, packaging]
open_questions: []
branches: ["feature/optional-daemon-adoption-model"]
openspec_change: optional-daemon-adoption-model
---

# Optional Daemon Adoption Model — three-tier pattern

## Overview

Defines the universal three-tier pattern for optional system daemons (Yggdrasil, i2pd, and future additions): disabled (do without), adopt (detect and use an existing installation without touching it), and managed (styrened provisions a pre-built Nix package and owns the process). The principle: don't prescribe, but provide a happy path for those who want one.

## Research

### The three tiers and what each means operationally



### Managed mode: the cold-start problem and how it differs per daemon

Not all daemons have the same warm-up profile. The managed mode UX must reflect reality.

### Abstract base class: DaemonAdapter pattern

The three-tier model is repeated across Yggdrasil, i2pd, and any future optional daemon. Rather than re-implementing the detection/lifecycle/status logic each time, a shared base class captures the pattern:

```python
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass

class DaemonMode(str, Enum):
    DISABLED = "disabled"
    ADOPT    = "adopt"
    MANAGED  = "managed"

@dataclass
class DaemonStatus:
    mode: DaemonMode
    running: bool
    warming_up: bool          # MANAGED only: process started but not yet functional
    warm_up_elapsed: float    # seconds since process start (MANAGED)
    warm_up_expected: float   # expected warm-up duration in seconds
    details: dict             # daemon-specific: address, peers, proxy_port, etc.

class DaemonAdapter(ABC):
    """Base class for optional system daemon integration."""
    
    def __init__(self, mode: DaemonMode):
        self.mode = mode
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
    
    # --- Subclass implements these ---
    
    @abstractmethod
    async def _probe(self) -> bool:
        """Check if the daemon is reachable (any mode)."""
    
    @abstractmethod
    async def _start_managed(self) -> None:
        """Start the daemon process (MANAGED mode only)."""
    
    @abstractmethod
    async def _stop_managed(self) -> None:
        """Stop the daemon process (MANAGED mode only)."""
    
    @abstractmethod
    async def _gather_details(self) -> dict:
        """Collect daemon-specific status info (address, peers, etc.)."""
    
    @property
    @abstractmethod
    def warm_up_seconds(self) -> float:
        """Expected warm-up duration for this daemon."""
    
    # --- Base class provides these ---
    
    async def start(self) -> None:
        if self.mode == DaemonMode.DISABLED:
            return
        if self.mode == DaemonMode.MANAGED:
            await self._start_managed()
            self._started_at = asyncio.get_event_loop().time()
        # ADOPT: nothing to start, just probe
    
    async def stop(self) -> None:
        if self.mode == DaemonMode.MANAGED and self._process:
            await self._stop_managed()
    
    @property
    def is_warming_up(self) -> bool:
        if self.mode != DaemonMode.MANAGED or self._started_at is None:
            return False
        elapsed = asyncio.get_event_loop().time() - self._started_at
        return elapsed < self.warm_up_seconds
    
    async def status(self) -> DaemonStatus:
        if self.mode == DaemonMode.DISABLED:
            return DaemonStatus(mode=self.mode, running=False, ...)
        running = await self._probe()
        details = await self._gather_details() if running else {}
        elapsed = (asyncio.get_event_loop().time() - self._started_at 
                   if self._started_at else 0.0)
        return DaemonStatus(
            mode=self.mode,
            running=running,
            warming_up=self.is_warming_up,
            warm_up_elapsed=elapsed,
            warm_up_expected=self.warm_up_seconds,
            details=details,
        )
```

**Concrete implementations:**

```python
class YggdrasilAdapter(DaemonAdapter):
    warm_up_seconds = 30.0    # fast
    
    async def _probe(self) -> bool:
        return await self._probe_admin_socket()
    
    async def _gather_details(self) -> dict:
        self_info = await self._admin_call("getSelf")
        peers = await self._admin_call("getPeers")
        return {"address": self_info["address"], "peer_count": len(peers)}

class I2PAdapter(DaemonAdapter):
    warm_up_seconds = 480.0   # 8 minutes typical
    
    async def _probe(self) -> bool:
        return await self._probe_http_proxy()
    
    async def _gather_details(self) -> dict:
        b32 = await self._detect_b32_address()
        return {"b32_address": b32, "proxy_port": self.config.http_proxy_port}
```

This pattern will extend cleanly to any future optional daemon (e.g., Tor, cjdns, a future BATMAN-ADV userspace manager).

### Landmine review — issues found before implementation



## Decisions

### Decision: DaemonMode enum: DISABLED | ADOPT | MANAGED — universal across all optional daemons

**Status:** decided
**Rationale:** Don't prescribe, but provide a happy path. DISABLED: zero overhead, explicit opt-in required. ADOPT: detect and use an existing installation, never touch its config or lifecycle — consent is explicit via config. MANAGED: styrened provisions via Nix-built binary, owns config and process, uses distinct ports to avoid conflicts with system installations. The operator chooses their relationship with each optional daemon. All three modes must degrade gracefully to the tier below if unavailable.

### Decision: MANAGED mode uses Nix-provisioned deterministic binaries, distinct ports to avoid system conflicts

**Status:** decided
**Rationale:** Nix provides reproducible, pinned binaries matching the rest of styrened's packaging philosophy. Distinct ports (i2pd managed: 4445 HTTP proxy, 7651 I2PControl vs system 4444/7650) mean system and managed instances can coexist without collision. Config lives in ~/.styrene/<daemon>/. OCI image variant nix build .#oci-full includes optional daemons; base .#oci does not.

### Decision: DaemonAdapter abstract base class captures the three-tier pattern for all optional daemons

**Status:** decided
**Rationale:** Detection logic, process lifecycle, warm-up tracking, and status reporting are the same across Yggdrasil, i2pd, and any future daemon. A shared DaemonAdapter base class with DaemonStatus dataclass avoids re-implementing this per service and establishes a consistent interface for the TUI and doctor to consume.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/daemon_adapter.py` (new) — DaemonAdapter ABC, DaemonMode enum, DaemonStatus dataclass. Includes _supervision_task loop (MANAGED only), _ensure_config_dir() with 0700/0600 enforcement, time.monotonic() throughout (no event loop), provision() stub for binary acquisition.

### Constraints

- provision() is separate from start() — binary acquisition happens at setup time, never during daemon startup. Missing binary in MANAGED mode = fail fast, never download at runtime.
- MANAGED mode has a crash supervision loop: asyncio.Task watching _process.wait(), restart with exponential backoff (1s/2s/4s.../60s cap), resets _started_at = time.monotonic() on each restart.
- Use time.monotonic() everywhere for timing — never asyncio.get_event_loop().time(). _started_at is a float from time.monotonic().
- ~/.styrene/<daemon>/ created with 0700. Key files written with 0600. Enforced in _ensure_config_dir(), not left to umask.
- Yggdrasil MANAGED uses port 9002 and admin socket ~/.styrene/yggdrasil/yggdrasil.sock to avoid clash with system Yggdrasil on 9001 / /var/run/yggdrasil/yggdrasil.sock.
- 'Degrade gracefully' means DaemonStatus.running=False + clear doctor warning. It does NOT mean silent mode switching. Mode is operator config — never changed at runtime by styrened.
- Skip _gather_details() while is_warming_up=True. Cache first successful result in self._cached_details — avoids hammering I2PControl for 8 minutes.
- doctor distinguishes mode=DISABLED (silent/intentional) from mode=ADOPT+not-found (warning: possible misconfiguration). MANAGED+not-running surfaces setup instructions.

## 🔴 Critical

### 1. Binary provisioning conflated with process start

`start()` calls `_start_managed()`, but `_start_managed()` would need to: (a) check if the binary exists, (b) if not, download it via `nix profile install`, (c) then start the process. Steps a+b are slow (network, Nix evaluation) and must NOT happen at daemon startup. By the time styrened's `daemon.start()` is called, the binary must already be present.

**Fix**: Binary provisioning belongs in a separate `provision()` method, invoked by `styrened setup --enable <daemon>` — not in `start()`. If the binary is missing at daemon startup in MANAGED mode, fail fast with a clear error: "yggdrasil binary not found — run `styrened setup --enable yggdrasil`." Never block daemon startup on a network download.

### 2. No crash supervision loop in MANAGED mode

`_start_managed()` spawns a subprocess and stores it in `self._process`. If the managed daemon crashes — especially likely for i2pd during warm-up — `self._process` becomes a dead zombie. The next `status()` probe detects it's gone, but there's no recovery. styrened just silently runs without the feature.

**Fix**: Base class needs a `_supervision_task: asyncio.Task | None` that `await self._process.wait()` in a loop, logging the crash and re-calling `_start_managed()` with exponential backoff (1s, 2s, 4s... cap at 60s). Reset `_started_at = time.monotonic()` on each restart. Do NOT supervise in ADOPT mode — it's not our process.

### 3. Private key files need explicit permission enforcement

MANAGED mode writes Yggdrasil private keys and i2pd router keys to `~/.styrene/<daemon>/`. The design doesn't mention enforcing permissions. On NFS home directories or systems with lax umasks, these directories can be world-readable by default.

**Fix**: On creating `~/.styrene/<daemon>/`, explicitly `chmod 0700`. On writing key files, `chmod 0600`. The base class `_ensure_config_dir()` helper should handle this — not left to the OS umask. Constraint added to impl notes.

## 🟡 Important

### 4. `_started_at` not reset on supervised restart

If the crash supervisor (fix #2) restarts the process, `_started_at` must be reset to `time.monotonic()` at each restart — not just the initial start. Otherwise `is_warming_up` returns False immediately after restart (elapsed > warm_up_seconds from the original start), even though the daemon just came back up cold.

**Fix**: Reset `_started_at = time.monotonic()` inside the supervision loop on each restart attempt, not just in `start()`.

### 5. `asyncio.get_event_loop().time()` in a sync property — deprecated in 3.10+

`is_warming_up` is a `@property` (sync). It calls `asyncio.get_event_loop().time()`. In Python 3.10+, `get_event_loop()` is deprecated outside a running loop context and raises `DeprecationWarning`. In Python 3.12+ this can raise.

**Fix**: Use `time.monotonic()` throughout. `_started_at` is set with `time.monotonic()` (not `loop.time()`), and `is_warming_up` compares against `time.monotonic()`. No event loop needed — monotonic clock is always available.

### 6. Yggdrasil MANAGED port conflict not specified

The design explicitly names i2pd managed ports (4445, 7651) to avoid clashing with system i2pd (4444, 7650). But for Yggdrasil MANAGED, port 9001 is the default — the same as system Yggdrasil. If both coexist, they collide.

**Fix**: Yggdrasil MANAGED uses listen port 9002 and admin socket `~/.styrene/yggdrasil/yggdrasil.sock` (distinct from system `/var/run/yggdrasil/yggdrasil.sock`). The `/meta` response includes the actual port so peers connect correctly regardless of which port is in use.

### 7. "Degrade gracefully to the tier below" is ambiguous — clarify it means feature-unavailable, not silent mode switch

The rationale says "all three modes must degrade gracefully to the tier below if unavailable." This reads as: if MANAGED binary is missing, fall back to ADOPT detection; if ADOPT detection fails, act as DISABLED. That would be a silent mode switch — which violates the "deliberate trust" principle established for ephemeral peers.

**Fix**: "Degrade gracefully" means the feature becomes cleanly unavailable (DaemonStatus.running=False, CAPABILITY bit not set), with a clear error surfaced in doctor. It does NOT mean silently switching modes. Mode is set by the operator in config — styrened never changes it at runtime. Document this explicitly in the constraint list.

## 🟠 Notable (won't block implementation, but worth knowing)

### 8. `_gather_details()` called repeatedly during 8-minute i2pd warm-up

During warm-up, every `status()` poll calls `_gather_details()`, which tries the I2PControl API to get the b32 address. This will fail for ~8 minutes and creates unnecessary socket connection churn.

**Fix**: Skip `_gather_details()` while `is_warming_up` is True. Return `details={}`. Only start gathering details once warm-up is expected to be complete. The b32 address is stable once known — cache it in `self._cached_details` after the first successful gather.

### 9. ADOPT mode non-detection should be visible in doctor, not just DEBUG log

"Mode is ADOPT but daemon not found" is a likely misconfiguration (user set mode: adopt but forgot to start i2pd). The current design logs at DEBUG. That's invisible in normal operation.

**Fix**: In `doctor`, distinguish: `mode=DISABLED` → not shown or shown as "disabled" (intentional). `mode=ADOPT` but probe fails → shown as warning: "I2P mode is ADOPT but i2pd not detected at 127.0.0.1:4444." Operator action surfaced explicitly.

## Yggdrasil in MANAGED mode

- Cold start: connects to first Ygg peer in ~5–30 seconds
- Warm: fully functional, global mesh reachable
- UX: "Yggdrasil starting..." → "Yggdrasil connected (X peers)" within a minute
- Acceptable as an on-demand managed process

## i2pd in MANAGED mode

- Cold start: 5–10 minutes to build tunnel pools and integrate into the I2P network
- During warm-up: HTTP proxy responds but .i2p fetches time out or return errors
- After warm-up: functional, but slower than a long-running instance with warm tunnel pools
- This is non-negotiable — it's how I2P works

**TUI implications for i2pd MANAGED**: The status must surface the warm-up phase explicitly. Not "I2P error" but "I2P warming up (~8 min remaining)". A progress indicator based on elapsed time since process start (heuristic, not precise) is sufficient. The operator clicked "Enable I2P" knowing it takes time.

**Config generation for i2pd MANAGED**: styrened generates:
```ini
# ~/.styrene/i2pd/i2pd.conf
[logger]
level = warn

[httpproxy]
enabled = true
address = 127.0.0.1
port = 4445                # managed port, avoids clash with system i2pd on 4444

[httpserver]
enabled = true             # I2PControl — needed for b32 address auto-detection
address = 127.0.0.1
port = 7651                # managed port, avoids clash with 7650

[sam]
enabled = false            # not needed for page browser use case

[datadir] 
# ~/.styrene/i2pd/
```

Using distinct ports (`4445`, `7651`) means MANAGED and ADOPT can technically coexist — the operator's system i2pd on 4444/7650 is undisturbed.

## The doctor flow for MANAGED setup

```
$ styrened doctor
  ✗ Yggdrasil: not running (mode: managed)
      → Run: styrened setup --enable yggdrasil
      → Or:  set yggdrasil.mode: adopt  if you have an existing installation
      
  ✗ I2P: not running (mode: managed)
      → I2P requires 5–10 min warm-up after first start
      → Run: styrened setup --enable i2p
```

```
$ styrened setup --enable yggdrasil
  Downloading yggdrasil via Nix... done
  Generating ~/.styrene/yggdrasil/yggdrasil.conf... done
  Starting yggdrasil... connected (2 peers, 200:abc::1)
  ✓ Yggdrasil ready
```

```
$ styrened setup --enable i2p
  Downloading i2pd via Nix... done
  Generating ~/.styrene/i2pd/i2pd.conf... done
  Starting i2pd... (this will take 5–10 minutes to warm up)
  ✓ i2pd started — warming up in background
    I2P eepsite browsing will be available once tunnels are established.
    Check status: styrened status --i2p
```

## The ADOPT flow in doctor

```
$ styrened doctor
  ✓ Yggdrasil: detected (mode: adopt, address: 200:abc::1, 5 peers)
  ✓ I2P: detected (mode: adopt, proxy: 127.0.0.1:4444, b32: abc...i2p)
      Note: styrened will use your existing i2pd. 
            styrened will not modify its configuration.
```

## DaemonMode enum — universal across all optional daemons

```python
class DaemonMode(str, Enum):
    DISABLED = "disabled"   # Feature off. No detection, no probing, no use.
    ADOPT    = "adopt"      # Detect existing installation. Use it. Never touch its config or lifecycle.
    MANAGED  = "managed"    # styrened provisions and owns the process via Nix-built binary.
```

## DISABLED

Feature simply isn't there. No socket probing, no capability bit in announces, no /meta fields. Zero overhead. This is the default for all optional daemons — the operator consciously opts in.

## ADOPT

styrened detects a running instance via its standard interfaces (admin socket, HTTP proxy port, etc.). If found: use it. If not found: log at DEBUG level, feature unavailable, graceful degradation. 

**Constraints in adopt mode:**
- Never write to the daemon's config files
- Never start or stop the process
- Never assume the daemon was started for styrened's benefit — it may serve other purposes
- Surface detection status in `styrened doctor` and TUI settings
- Respect the user's existing configuration exactly as-is

The i2pd privacy case is the canonical example: the user may be running i2pd for personal browsing. styrened should never assume it can use that resource without explicit consent (`i2p.mode: adopt` IS the consent, set by the operator).

## MANAGED

styrened acts as the lifecycle owner:
- Locates a Nix-built binary (from the Nix store, or downloads it on-demand via `nix profile install`)
- Generates a minimal, styrene-specific config in `~/.styrene/<daemon>/`
- Starts the process as a subprocess, monitors health, restarts on failure
- Knows exactly when the process started — can surface warm-up status in TUI
- Admin socket / API paths are known exactly (styrened configured them)

**Key property of managed mode:** styrened generated the config, so it knows where everything is. No probing needed — the b32 address, admin socket path, keypair location are all known quantities.

**What managed does NOT mean:**
- It does not mean "optimal configuration" — styrened generates a functional baseline, not a tuned production setup
- It does not prevent the operator from also running a system instance — managed mode uses a separate config dir (`~/.styrene/yggdrasil/`, `~/.styrene/i2pd/`) with distinct ports where needed to avoid conflicts
- It is explicitly a convenience path, not the "right" way to run these services at scale

## Config structure — consistent across all optional daemons

```python
@dataclass
class YggdrasilConfig:
    mode: DaemonMode = DaemonMode.DISABLED
    # ADOPT: probe these
    admin_socket: str = ""              # "" = probe common paths
    listen_port: int = 9001
    # MANAGED: use these
    binary_path: str = "yggdrasil"     # or resolved from Nix store
    multicast: bool = True
    # Behavior (applies in ADOPT + MANAGED)
    bootstrap_from_rns: bool = True
    peer_discovery: YggPeerDiscovery = YggPeerDiscovery.EAGER
    initial_peers: list[str] = field(default_factory=list)

@dataclass
class I2PConfig:
    mode: DaemonMode = DaemonMode.DISABLED
    # ADOPT: probe these
    http_proxy_host: str = "127.0.0.1"
    http_proxy_port: int = 4444
    # MANAGED: use a separate port to avoid conflict with system i2pd
    managed_http_proxy_port: int = 4445
    # Behavior (applies in ADOPT + MANAGED)
    b32_address: str = ""               # auto-detected in MANAGED, probed in ADOPT
    cache_ttl: int = 3600
    fetch_timeout: float = 45.0
```

YAML surface for operators:
```yaml
yggdrasil:
  mode: managed    # disabled | adopt | managed

i2p:
  mode: adopt      # using my existing i2pd
```

## The Nix happy path for MANAGED mode

styrened's Nix flake already produces OCI images. Extending it to also provide optional daemon binaries is natural:

```nix
# flake.nix — optional packages
packages.yggdrasil-managed = pkgs.yggdrasil;   # pinned version, deterministic
packages.i2pd-managed = pkgs.i2pd;
```

For PyPI installs (non-Nix environments), managed mode checks if `nix` is available in PATH. If yes, `nix profile install nixpkgs#yggdrasil`. If no, falls back to binary in PATH or surfaces a helpful error in `styrened doctor`.

For OCI containers: the `nix build .#oci-full` variant includes optional daemon binaries. `nix build .#oci` (base) does not. Clear separation — operators choose the image variant they want.
