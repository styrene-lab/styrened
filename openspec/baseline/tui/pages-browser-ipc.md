# tui/pages-browser-ipc

### Requirement: Page browsing must not block control-plane IPC

The TUI must isolate long-running page-browsing traffic so a slow or timing-out page fetch does not delay unrelated control-plane requests that use the normal shared bridge.

#### Scenario: Slow page fetch does not stall shared control requests
Given a `PageBrowserWidget` page load is in flight for a slow or timing-out node
When the TUI issues an unrelated control-plane request such as daemon status on the normal shared bridge
Then that request completes without waiting for the page fetch response on the same IPC lane
And the page fetch continues on its isolated lane

### Requirement: Page browsing preserves traffic-class separation

The TUI must preserve distinct traffic classes for quick control/command work, bulk data refreshes, and long-running interactive execution so QoS emerges from lane isolation rather than request-priority hacks.

#### Scenario: Page browser uses a dedicated long-running lane
Given the TUI separates quick control/command requests, bulk data refreshes, and long-running interactive work
When a page browser instance performs NomadNet, I2P, or HTTPS page loads
Then those loads use a dedicated long-running lane rather than the shared control bridge
And normal startup demand remains unchanged until an operator actually opens or reloads a page

### Requirement: Page failures remain local to the browser surface

Page timeouts, link failures, and cached fallbacks must degrade only the page-browser surface and must not be mistaken for daemon disconnects or global TUI failure.

#### Scenario: Page timeout remains local to the browser
Given a page fetch times out or fails to establish a link
When the page browser reports the failure or shows cached content
Then the operator sees page-specific degradation in the browser surface
And unrelated daemon liveness or shared-screen status remains truthful and responsive
