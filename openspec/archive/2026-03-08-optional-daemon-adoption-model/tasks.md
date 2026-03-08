# Optional Daemon Adoption Model — Tasks

## Group 1: DaemonAdapter base class (`src/styrened/services/daemon_adapter.py`)

This is the foundation everything else depends on. Implement first.

- [ ] 1.1 Define `DaemonMode(str, Enum)` with DISABLED / ADOPT / MANAGED values
- [ ] 1.2 Define `DaemonStatus` dataclass: `mode`, `running`, `warming_up`, `warm_up_elapsed`, `warm_up_expected`, `details: dict`
- [ ] 1.3 Implement `DaemonAdapter` ABC with fields: `mode`, `_process`, `_started_at: float | None`, `_cached_details: dict | None`, `_supervision_task: asyncio.Task | None`
- [ ] 1.4 Implement `_ensure_config_dir(path: Path)` helper — creates dir with `chmod 0700`, enforces `0600` on any key files written within it
- [ ] 1.5 Implement `provision()` stub — raises `NotImplementedError` with message: binary acquisition belongs here, not in `start()`
- [ ] 1.6 Implement `start()` — DISABLED: return immediately. MANAGED: call `_start_managed()`, set `_started_at = time.monotonic()`, launch `_supervision_task`. ADOPT: no-op (probe happens on first `status()` call)
- [ ] 1.7 Implement `_run_supervision_loop()` — `asyncio.Task` that `await self._process.wait()`, logs crash, restarts with exponential backoff (1s/2s/4s…cap 60s), resets `_started_at = time.monotonic()` on each restart. MANAGED only — never runs in ADOPT mode.
- [ ] 1.8 Implement `stop()` — MANAGED: cancel `_supervision_task`, call `_stop_managed()`. ADOPT/DISABLED: no-op
- [ ] 1.9 Implement `is_warming_up` property — uses `time.monotonic()` only, no event loop. Returns False if not MANAGED or `_started_at` is None
- [ ] 1.10 Implement `status()` — DISABLED: return `DaemonStatus(running=False, warming_up=False, ...)`. ADOPT/MANAGED: call `_probe()`. If running and NOT warming up: call `_gather_details()` and cache result in `_cached_details`. If warming up: skip `_gather_details()`, return cached or empty dict. Return full `DaemonStatus`.
- [ ] 1.11 Declare abstract methods: `_probe()`, `_start_managed()`, `_stop_managed()`, `_gather_details()`, `warm_up_seconds: float`
- [ ] 1.12 Write unit tests for base class behaviour: DISABLED status, ADOPT probe-fail graceful degradation, MANAGED warm-up tracking, supervision loop restart resets `_started_at`, `_gather_details` skipped during warm-up, `time.monotonic()` used throughout (assert no `get_event_loop` calls)

## Group 2: Config model (`src/styrened/models/config.py`)

- [ ] 2.1 Add `DaemonMode` import from `daemon_adapter`
- [ ] 2.2 Add `YggdrasilConfig` dataclass: `mode: DaemonMode = DISABLED`, `binary_path: str = "yggdrasil"`, `listen_port: int = 9002` (managed; 9001 is system default), `admin_socket: str = ""`, `multicast: bool = True`, `bootstrap_from_rns: bool = True`, `peer_discovery: YggPeerDiscovery = EAGER`, `initial_peers: list[str]`
- [ ] 2.3 Add `I2PConfig` dataclass: `mode: DaemonMode = DISABLED`, `http_proxy_host: str = "127.0.0.1"`, `http_proxy_port: int = 4444`, `managed_http_proxy_port: int = 4445`, `managed_i2pcontrol_port: int = 7651`, `b32_address: str = ""`, `cache_ttl: int = 3600`, `fetch_timeout: float = 45.0`
- [ ] 2.4 Add `yggdrasil: YggdrasilConfig` and `i2p: I2PConfig` to `CoreConfig`
- [ ] 2.5 Add YAML parsing for both config sections in `services/config.py`
- [ ] 2.6 Write unit tests: default values correct, YAML round-trip, unknown fields ignored

## Group 3: `YggdrasilAdapter` (`src/styrened/services/yggdrasil.py`)

Depends on Group 1 and 2.

- [ ] 3.1 Implement `YggdrasilAdapter(DaemonAdapter)` with `warm_up_seconds = 30.0`
- [ ] 3.2 Implement `_ensure_yggdrasil_config()` — generates `~/.styrene/yggdrasil/yggdrasil.conf` with: managed listen port (9002), managed admin socket path (`~/.styrene/yggdrasil/yggdrasil.sock`), `initial_peers` from config, multicast settings. Calls `_ensure_config_dir()` to enforce permissions.
- [ ] 3.3 Implement `_start_managed()` — check binary exists (fail fast if not, do NOT provision), call `_ensure_yggdrasil_config()`, spawn subprocess
- [ ] 3.4 Implement `_stop_managed()` — SIGTERM, wait up to 5s, SIGKILL if unresponsive
- [ ] 3.5 Implement `_probe()` — try admin socket paths in order: managed socket first, then common system paths (`/var/run/yggdrasil/yggdrasil.sock`, `/run/yggdrasil.sock`, `/tmp/yggdrasil.sock`). Return True if any responds.
- [ ] 3.6 Implement `_admin_call(method, params={})` — JSON-RPC over Unix socket with timeout
- [ ] 3.7 Implement `_gather_details()` — `getSelf` for address, `getPeers` for peer count
- [ ] 3.8 Implement `get_local_address() -> str | None` — returns cached address from last successful `_gather_details()` or None
- [ ] 3.9 Implement `add_peer(address: str, port: int = 9001) -> bool` — admin socket `addPeer` call only, no filesystem write (ephemeral by design)
- [ ] 3.10 Implement `provision()` — checks if binary exists in PATH / Nix store. If not: print instructions for `nix profile install nixpkgs#yggdrasil`. Does NOT install automatically.
- [ ] 3.11 Write unit tests: probe succeeds/fails, add_peer ephemeral (no file write), get_local_address caches correctly, managed start fails fast on missing binary, config dir permissions enforced

## Group 4: `I2PAdapter` (`src/styrened/services/i2p.py`)

Depends on Group 1 and 2.

- [ ] 4.1 Implement `I2PAdapter(DaemonAdapter)` with `warm_up_seconds = 480.0`
- [ ] 4.2 Implement `_generate_i2pd_conf()` — writes `~/.styrene/i2pd/i2pd.conf` with managed ports (4445 HTTP proxy, 7651 I2PControl), `[httpserver] enabled=true` for b32 detection, `[sam] enabled=false`. Calls `_ensure_config_dir()`.
- [ ] 4.3 Implement `_start_managed()` — check binary exists (fail fast), call `_generate_i2pd_conf()`, spawn subprocess
- [ ] 4.4 Implement `_stop_managed()` — SIGTERM, wait up to 10s (i2pd is slower), SIGKILL if unresponsive
- [ ] 4.5 Implement `_probe()` — TCP connect to HTTP proxy port with 2s timeout
- [ ] 4.6 Implement `_detect_b32_address()` — (1) try I2PControl API on managed port (7651) or adopted port (7650), (2) fall back to `config.b32_address` string. Return None if both fail.
- [ ] 4.7 Implement `_gather_details()` — calls `_detect_b32_address()`. Returns `{"b32_address": addr, "proxy_port": effective_port}`
- [ ] 4.8 Implement `get_http_proxy_url() -> str | None` — returns `http://host:port` for the effective proxy (managed port or adopted port), or None if not running
- [ ] 4.9 Implement `provision()` — checks for i2pd binary. If not found: print instructions. Does NOT install.
- [ ] 4.10 Write unit tests: probe (running/not running), b32 detection (I2PControl success, I2PControl fail → config fallback, both fail → None), warm-up skips _gather_details, managed uses port 4445 not 4444, config dir permissions enforced

## Group 5: `doctor.py` integration

Depends on Groups 3 and 4.

- [ ] 5.1 Add Yggdrasil check: mode=DISABLED → skip. mode=ADOPT + not found → WARNING "yggdrasil not detected at expected socket paths — is it running?". mode=ADOPT + found → OK with address and peer count. mode=MANAGED + binary missing → ERROR with `styrened setup --enable yggdrasil` hint. mode=MANAGED + running → OK.
- [ ] 5.2 Add I2P check: same pattern. mode=ADOPT + not found → WARNING "i2pd not detected at 127.0.0.1:4444". mode=MANAGED + running but warming up → INFO "i2pd warming up (~N min remaining)".
- [ ] 5.3 Write unit tests for both doctor check paths covering all mode × running combinations

## Group 6: `styrened setup` subcommand (`src/styrened/cli.py`)

- [ ] 6.1 Add `setup` subcommand with `--enable {yggdrasil,i2p}` flag
- [ ] 6.2 `setup --enable yggdrasil`: calls `YggdrasilAdapter.provision()`, then if binary found sets `config.yggdrasil.mode = MANAGED` and saves config
- [ ] 6.3 `setup --enable i2p`: calls `I2PAdapter.provision()`, same pattern. Prints cold-start warning: "i2pd requires 5–10 minutes to warm up after first start."
- [ ] 6.4 Write unit tests for CLI surface: provision() called, config written, appropriate messages printed
