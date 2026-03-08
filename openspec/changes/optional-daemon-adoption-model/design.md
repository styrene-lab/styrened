# Optional Daemon Adoption Model — three-tier pattern — Design

## Architecture Decisions

### Decision: DaemonMode enum: DISABLED | ADOPT | MANAGED — universal across all optional daemons

**Status:** decided
**Rationale:** Don't prescribe, but provide a happy path. DISABLED: zero overhead, explicit opt-in required. ADOPT: detect and use an existing installation, never touch its config or lifecycle — consent is explicit via config. MANAGED: styrened provisions via Nix-built binary, owns config and process, uses distinct ports to avoid conflicts with system installations. The operator chooses their relationship with each optional daemon. All three modes must degrade gracefully to the tier below if unavailable.

### Decision: MANAGED mode uses Nix-provisioned deterministic binaries, distinct ports to avoid system conflicts

**Status:** decided
**Rationale:** Nix provides reproducible, pinned binaries matching the rest of styrened's packaging philosophy. Distinct ports (i2pd managed: 4445 HTTP proxy, 7651 I2PControl vs system 4444/7650) mean system and managed instances can coexist without collision. Config lives in ~/.styrene/<daemon>/. OCI image variant nix build .#oci-full includes optional daemons; base .#oci does not.

### Decision: DaemonAdapter abstract base class captures the three-tier pattern for all optional daemons

**Status:** decided
**Rationale:** Detection logic, process lifecycle, warm-up tracking, and status reporting are the same across Yggdrasil, i2pd, and any future daemon. A shared DaemonAdapter base class with DaemonStatus dataclass avoids re-implementing this per service and establishes a consistent interface for the TUI and doctor to consume.

## Research Context

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



## File Changes

- `src/styrened/services/daemon_adapter.py` (new) — DaemonAdapter ABC, DaemonMode enum, DaemonStatus dataclass. Includes _supervision_task loop (MANAGED only), _ensure_config_dir() with 0700/0600 enforcement, time.monotonic() throughout (no event loop), provision() stub for binary acquisition.

## Constraints

- provision() is separate from start() — binary acquisition happens at setup time, never during daemon startup. Missing binary in MANAGED mode = fail fast, never download at runtime.
- MANAGED mode has a crash supervision loop: asyncio.Task watching _process.wait(), restart with exponential backoff (1s/2s/4s.../60s cap), resets _started_at = time.monotonic() on each restart.
- Use time.monotonic() everywhere for timing — never asyncio.get_event_loop().time(). _started_at is a float from time.monotonic().
- ~/.styrene/<daemon>/ created with 0700. Key files written with 0600. Enforced in _ensure_config_dir(), not left to umask.
- Yggdrasil MANAGED uses port 9002 and admin socket ~/.styrene/yggdrasil/yggdrasil.sock to avoid clash with system Yggdrasil on 9001 / /var/run/yggdrasil/yggdrasil.sock.
- 'Degrade gracefully' means DaemonStatus.running=False + clear doctor warning. It does NOT mean silent mode switching. Mode is operator config — never changed at runtime by styrened.
- Skip _gather_details() while is_warming_up=True. Cache first successful result in self._cached_details — avoids hammering I2PControl for 8 minutes.
- doctor distinguishes mode=DISABLED (silent/intentional) from mode=ADOPT+not-found (warning: possible misconfiguration). MANAGED+not-running surfaces setup instructions.
