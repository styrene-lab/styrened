# COP Adapter Status — Extensible Overlay Service Health Surface — Tasks

## 1. Event bus extension + adapter registry
<!-- specs: adapter-protocol -->

- [ ] 1.1 Add `adapter_changed` as 6th EventBus top-level type in `src/styrened/services/event_bus.py`
      — actions enum: `ready`, `warming`, `degraded`, `probing`, `disabled`
      — follow exact pattern of existing types (hub_changed, link_changed, etc.)
- [ ] 1.2 Create `src/styrened/services/adapter_registry.py`:
      — `AdapterState` enum: `DISABLED`, `PROBING`, `WARMING`, `READY`, `DEGRADED`
      — `WarmupBehavior` dataclass: `actionable: bool`, `action_label: str | None = None`
      — `AdapterProtocol` ABC: `probe() -> AdapterState`, `display_name: str`, `short_label: str`, `warmup_behavior: WarmupBehavior`
      — `AdapterRegistry`: holds `list[AdapterProtocol]`, `get_all() -> list[AdapterProtocol]`
      — `AdapterStateRecord` dataclass: `adapter_name`, `short_label`, `state: AdapterState`, `warmup_behavior: WarmupBehavior`, `last_changed: datetime`

## 2. I2PAdapter implements AdapterProtocol
<!-- specs: adapter-protocol -->

- [ ] 2.1 Update `src/styrened/services/i2p.py` — `I2PAdapter` implements `AdapterProtocol`:
      — `display_name = "I2P"`, `short_label = "I2P"`
      — `warmup_behavior = WarmupBehavior(actionable=False)` (bootstrapping is non-actionable)
      — `probe() -> AdapterState`: maps existing `_probe()` result to AdapterState enum
        — adapter DISABLED → `AdapterState.DISABLED`
        — proxy not bound → `AdapterState.PROBING`
        — proxy bound, test fetch pending/slow → `AdapterState.WARMING`
        — test fetch succeeds → `AdapterState.READY`
        — was READY, now unreachable → `AdapterState.DEGRADED`
- [ ] 2.2 Add probe loop to daemon startup: `_start_adapter_probe_loop()` in `src/styrened/daemon.py`
      — instantiates `AdapterRegistry` with configured adapters
      — runs `asyncio.create_task(_adapter_probe_loop())` alongside other service tasks
      — `_adapter_probe_loop()`: polls each adapter at configurable interval (default 30s)
      — on state transition: emits `DaemonEvent(EventType.ADAPTER_CHANGED, new_state.value, {adapter: name, prev: prev_state.value})`
      — stores previous state per adapter to detect transitions

## 3. TUI model — AdapterStatusTracker
<!-- specs: tui-model -->

- [ ] 3.1 Create `src/styrened/tui/models/adapter_status.py`:
      — `AdapterDisplayState` dataclass: `name: str`, `short_label: str`, `state: AdapterState`, `warmup_behavior: WarmupBehavior`, `since: datetime`
      — `AdapterStatusSnapshot` dataclass: `adapters: list[AdapterDisplayState]`, `timestamp: datetime`
      — `AdapterStatusTracker`:
        — `ingest(event: DaemonEvent) -> AdapterStatusSnapshot | None`
          — handles `adapter_changed` events, updates internal state dict keyed by adapter name
          — returns new snapshot if state changed, None if no-op
        — `snapshot() -> AdapterStatusSnapshot` — current snapshot of all known adapters
        — `get_situation_line(event) -> SituationLine | None`
          — returns a `SituationLine` for transitions that warrant COP activity lines:
            — `WARMING → READY`: informational, normal TTL
            — `READY → DEGRADED`: anomaly, persists until recovery
            — `DEGRADED → READY`: informational, normal TTL
            — `DISABLED → *`: no line

## 4. AdapterStatusBar widget
<!-- specs: widget -->

- [ ] 4.1 Create `src/styrened/tui/widgets/adapter_status_bar.py`:
      — `AdapterStatusBar(Static)`: presentation-only, no bridge access, no subscriptions
      — `apply_snapshot(snapshot: AdapterStatusSnapshot) -> None`: stores snapshot, calls `refresh()`
      — `render() -> RenderableType`: renders the ADAPTERS row using Rich markup
        — DISABLED: dim dashed indicator `[dim]╌ {label} off[/dim]`
        — PROBING: amber `[yellow]◌ {label} probing[/yellow]`
        — WARMING: amber `[yellow]◌ {label} warming[/yellow]` (+ duration if >30s)
        — READY: green `[green]● {label}[/green]`
        — DEGRADED: red `[bold red]✗ {label} degraded[/bold red]`
      — If no adapters registered: renders nothing (empty string / collapsed)
      — WarmupBehavior.actionable: reserve space for action label when True (future: button)
- [ ] 4.2 Write unit tests in `tests/tui/widgets/test_adapter_status_bar.py`:
      — test render for each AdapterState
      — test multiple adapters render in row
      — test empty snapshot renders empty
      — test apply_snapshot triggers refresh

## 5. Dashboard wiring
<!-- specs: dashboard -->

- [ ] 5.1 Update `src/styrened/tui/screens/dashboard.py`:
      — instantiate `AdapterStatusTracker` alongside `CopSituationTracker` in `on_mount`
      — add `AdapterStatusBar` to compose — above `CopActivitySummary` in the COP column
      — in `on_daemon_event()`: handle `EventType.ADAPTER_CHANGED`
        — call `adapter_tracker.ingest(event)` → get snapshot
        — call `adapter_status_bar.apply_snapshot(snapshot)`
        — if tracker returns a `SituationLine`, inject it into `cop_situation_tracker` and push updated COP snapshot
      — on initial state load (`_fetch_daemon_status`): if adapter states are returned, seed tracker
- [ ] 5.2 Write/extend tests in `tests/tui/screens/test_dashboard_tui.py`:
      — test adapter_changed event updates AdapterStatusBar snapshot
      — test READY→DEGRADED transition injects anomaly SituationLine into COP feed
      — test WARMING→READY transition injects informational SituationLine
      — test DISABLED→PROBING transition generates no SituationLine

## 6. Tests — daemon probe loop
<!-- specs: adapter-protocol -->

- [ ] 6.1 Write unit tests in `tests/unit/test_adapter_registry.py`:
      — test AdapterProtocol is correctly implemented by I2PAdapter (isinstance check, ABC compliance)
      — test probe loop emits adapter_changed on state transition (mock probe(), mock event bus)
      — test probe loop emits nothing when state unchanged
      — test WarmupBehavior.actionable=False means no action_label rendered
      — test AdapterRegistry.get_all() returns all registered adapters
