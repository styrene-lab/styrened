## ADDED Requirements

### Requirement: Home first paint does not wait for bulk hydration
The Home workspace MUST be able to render a truthful connected summary without waiting for full device inventory or full conversation list hydration.

#### Scenario: Slow bulk hydration does not block Home connection state
- **Given** the daemon control socket is reachable and status queries succeed
- **And** bulk hydration such as the shared device cache refresh is slow or delayed
- **When** Home performs its startup refresh
- **Then** Home reports the daemon as connected
- **And** Home does not wait for a full `get_devices()` result before first paint

### Requirement: Home distinguishes degraded IPC pressure from disconnect
The Home status surface MUST distinguish a healthy daemon under bulk-hydration pressure from an actually disconnected daemon.

#### Scenario: Bulk query lag yields degraded state, not disconnect
- **Given** Home can still fetch daemon status successfully
- **And** a non-critical hydration path such as unread-count or device-cache priming is delayed or fails transiently
- **When** Home updates its status indicators
- **Then** it keeps the daemon in a connected state
- **And** it surfaces a degraded/backpressured indicator distinct from a disconnected indicator

### Requirement: Shared DeviceCache primes after first paint
The shared app-level DeviceCache MUST continue to own fleet detail, but its initial bulk refresh MUST be staged so it does not compete with first-paint status work.

#### Scenario: Device cache priming is delayed into background work
- **Given** IPC services have initialized successfully
- **When** the app starts the shared DeviceCache
- **Then** initial bulk hydration is scheduled after first-paint startup work rather than running immediately in the same burst
- **And** later refreshes continue to update the shared cache for downstream screens

### Requirement: Home uses cheaper unread hydration than full conversation enumeration
Home MUST avoid full conversation-list hydration when only unread counts are required.

#### Scenario: Home reads unread counts without loading conversation summaries
- **Given** Home only needs unread badges and total unread count for summary display
- **When** it refreshes status panels
- **Then** it uses the unread-count summary path instead of full conversation enumeration
- **And** a slow conversation list does not determine Home connection state
