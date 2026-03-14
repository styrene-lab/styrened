# transport-browser — Delta Spec

## ADDED Requirements

### Requirement: .i2p URLs rewritten to localhost proxy for browser delegation

When the user presses O to open an .i2p URL in their browser, the URL must be
rewritten to go through the I2P HTTP proxy (default localhost:4444) since browsers
cannot resolve .i2p hostnames natively.

#### Scenario: I2P URL rewritten to proxy for browser
Given the page browser is viewing `http://something.b32.i2p/page`
When the user triggers action_open_in_browser
Then the URL passed to `app.open_url()` is `http://localhost:4444/http://something.b32.i2p/page`
And the original .i2p hostname is not passed directly to the browser

#### Scenario: HTTPS URL passed through unchanged
Given the page browser is viewing `https://styrene.dev/docs`
When the user triggers action_open_in_browser
Then the URL passed to `app.open_url()` is `https://styrene.dev/docs`

#### Scenario: NomadNet path shows informational message
Given the page browser is viewing NomadNet path `/page/index.mu`
When the user triggers action_open_in_browser
Then a notification says NomadNet pages are only viewable in the TUI
And `app.open_url()` is not called

### Requirement: Transport cycling performs exactly one fetch

When cycling transports via T key, the widget must set internal state and fire
exactly one `_load_page()` worker. It must not call `set_external_url()` or
`set_destination()` which themselves fire workers.

#### Scenario: Cycling to I2P transport fires one load
Given a node with NomadNet and I2P transports available
And the active transport is NomadNet
When action_cycle_transport is triggered
Then `_external_url` is set to the I2P URL
And exactly one `_load_page` worker is started
And history is cleared

#### Scenario: Cycling to HTTPS transport fires one load
Given a node with NomadNet and HTTPS transports available
And the active transport is NomadNet
When action_cycle_transport is triggered twice (past I2P if present)
Then `_external_url` is set to the HTTPS URL
And exactly one `_load_page` worker is started per cycle

### Requirement: O keybinding hidden on headless environments

The O binding should not appear in the footer when no browser is available.
Textual's `check_action` mechanism is used to dynamically enable/disable bindings.

#### Scenario: O binding hidden over SSH without DISPLAY
Given the environment has SSH_CONNECTION set and no DISPLAY variable
And the platform is Linux
When PageBrowserWidget renders its bindings
Then the `open_in_browser` action returns False from check_action
And the O binding does not appear in the footer

#### Scenario: O binding visible on macOS even over SSH
Given the environment has SSH_CONNECTION set
And the platform is Darwin (macOS)
When PageBrowserWidget renders its bindings
Then the `open_in_browser` action returns True from check_action

## MODIFIED Requirements

### Requirement: _last_content_kind set on all render paths

The content-type indicator in the URL bar and status line must always reflect
the current page, including when structured data rendering is used.

#### Scenario: Content kind updated even when structured renderer used
Given a page response with content_type 'text/html' and structured_data present
When `_load_page` renders the page via `render_structured_page()`
Then `_last_content_kind` is set to `ContentKind.HTML`
And the URL bar shows the HTML indicator

#### Scenario: Content kind updated on micron page
Given a page response with content_type 'text/x-micron'
When `_load_page` renders the page
Then `_last_content_kind` is set to `ContentKind.MICRON`
