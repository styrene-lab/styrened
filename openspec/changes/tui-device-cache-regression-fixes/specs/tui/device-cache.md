## ADDED Requirements

### Requirement: Cache-backed node consumers tolerate unprimed cache state
TUI screens that consume the shared DeviceCache MUST continue to function when the app exposes a DeviceCache object but the cache has not yet been populated.

#### Scenario: Nodes workspace falls back when cache is empty
- **Given** ExplorationScreen is mounted in a context where `app.device_cache` exists but returns an empty device list
- **When** the screen refreshes its tables
- **Then** it does not treat the empty cache as authoritative absence during direct-discovery-compatible contexts
- **And** it preserves a functional path to show available node data instead of rendering all node categories empty solely because the cache is unprimed

#### Scenario: Peer detail resolution falls back when cache is empty
- **Given** MeshDeviceDetailScreen is resolving a peer and `app.device_cache` exists but returns an empty device list
- **When** live device lookup runs
- **Then** the screen still has a fallback path to resolve the peer from available non-cache sources
- **And** the peer detail screen does not remain stuck in a not-found state solely because the cache is unprimed

### Requirement: Bare-screen or test contexts do not report false daemon disconnects
Dashboard status refresh MUST distinguish between actual daemon/bridge failure and inability to access app-level cache helpers from an unmounted or synthetic test context.

#### Scenario: Dashboard status wiring remains connected when bridge calls succeed
- **Given** `_fetch_daemon_status()` is invoked with successful bridge responses
- **And** the screen is exercised in a unit context without a fully mounted app tree
- **When** dashboard status refresh runs
- **Then** the status bar remains marked connected
- **And** cache helper access does not force the method down the daemon-disconnected path

### Requirement: Startup and navigation tests reflect current Home and splash ownership
Automated tests MUST reflect the intentional splash-first startup flow and the current Home-versus-Nodes ownership boundary.

#### Scenario: App startup expects SplashScreen first
- **Given** StyreneApp launches normally
- **When** the first visible screen is asserted in tests
- **Then** tests expect SplashScreen as the startup surface before dashboard/setup routing completes

#### Scenario: Legacy dashboard tree imports are retired or redirected
- **Given** dashboard peer browsing now belongs to the Nodes workspace rather than Home
- **When** navigation and integration tests are collected
- **Then** they do not import removed dashboard-only peer-tree symbols
- **And** collection succeeds against the current architecture
