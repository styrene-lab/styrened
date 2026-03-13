# COP Adapter Status — Extensible Overlay Service Health Surface — Design Spec

## Scenarios

### Scenario 1: Adapter state reflects probe reality

Given an adapter is configured in ADOPT mode  
When the probe loop transitions state (e.g., WARMING → READY)  
Then the COP ADAPTERS row updates within one probe interval, with no stale state held beyond that

### Scenario 2: DISABLED adapters remain visible

Given an adapter is DISABLED in config  
When the ADAPTERS row renders  
Then the adapter appears with dashed/inactive visual language rather than being hidden

### Scenario 3: Anomaly transitions generate situation lines

Given an adapter is in READY state  
When the probe detects the adapter has become unreachable (READY → DEGRADED)  
Then a situation line appears in the COP activity feed, persists until recovery, and is categorized as an anomaly

### Scenario 4: Recovery transitions generate informational lines

Given an adapter is in DEGRADED state  
When a subsequent probe confirms the adapter is functional again (DEGRADED → READY)  
Then an informational situation line appears in the COP activity feed and dims on normal TTL

### Scenario 5: New adapter registration requires no COP widget changes

Given a new adapter class implements AdapterProtocol  
When it is added to the AdapterRegistry at daemon startup  
Then it appears in the ADAPTERS row without modification to AdapterStatusBar, AdapterStatusTracker, or DashboardScreen

### Scenario 6: Probe timer is daemon-side only

Given the TUI is disconnected or on a non-dashboard screen  
When an adapter state transition occurs  
Then the adapter_changed event is still emitted on the EventBus — probe logic does not depend on TUI presence

### Scenario 7: Per-adapter warm-up actionability

Given two adapters with different WarmupBehavior declarations  
When one declares non-actionable and one declares retryable  
Then the ADAPTERS row renders a retry affordance only for the retryable adapter during WARMING state

## Falsifiability

- If any probe code appears in the TUI layer, this design fails
- If adding a new adapter requires modifying AdapterStatusBar or dashboard wiring, the extensibility contract is broken
- If a DISABLED adapter is hidden from the ADAPTERS row, the discoverability requirement is violated
- If the displayed state lags more than one probe interval behind actual adapter state, accuracy is violated

## Constraints

- adapter_changed is a 6th EventBus top-level type — not folded into hub_changed or link_changed
- AdapterProtocol ABC is the only registration surface — no dict/dataclass alternative
- DashboardScreen is a pure observer — no probe timers, no adapter logic
- DISABLED state never generates situation lines
