# daemon-validation

### Requirement: web_url scheme validated in _validate_meta_response

A malicious remote peer can declare any string as their `web_url` in /meta responses.
Only `https://` and `http://` schemes are accepted. This prevents javascript:, file:,
and data: URL scheme injection that would be passed to `App.open_url()` when the user
presses O to open in browser.

#### Scenario: HTTPS URL accepted
Given a /meta response with `web_url: \"https://styrene.dev\"`
When `_validate_meta_response()` processes it
Then the result includes `web_url: \"https://styrene.dev\"`

#### Scenario: HTTP URL accepted
Given a /meta response with `web_url: \"http://my-node.local:8080\"`
When `_validate_meta_response()` processes it
Then the result includes the web_url value

#### Scenario: javascript: URL rejected
Given a /meta response with `web_url: \"javascript:alert(1)\"`
When `_validate_meta_response()` processes it
Then the result does not include a `web_url` field

#### Scenario: file: URL rejected
Given a /meta response with `web_url: \"file:///etc/passwd\"`
When `_validate_meta_response()` processes it
Then the result does not include a `web_url` field

#### Scenario: data: URL rejected
Given a /meta response with `web_url: \"data:text/html,<script>alert(1)</script>\"`
When `_validate_meta_response()` processes it
Then the result does not include a `web_url` field

#### Scenario: Empty string still excluded
Given a /meta response with `web_url: \"\"`
When `_validate_meta_response()` processes it
Then the result does not include a `web_url` field

### Requirement: ygg_port validated to 1-65535 range

Port values outside the valid TCP/UDP range are silently rejected.

#### Scenario: Valid port accepted
Given a /meta response with `ygg_port: 9002`
When `_validate_meta_response()` processes it
Then the result includes `ygg_port: 9002`

#### Scenario: Negative port rejected
Given a /meta response with `ygg_port: -1`
When `_validate_meta_response()` processes it
Then the result does not include a `ygg_port` field

#### Scenario: Port zero rejected
Given a /meta response with `ygg_port: 0`
When `_validate_meta_response()` processes it
Then the result does not include a `ygg_port` field

#### Scenario: Port above 65535 rejected
Given a /meta response with `ygg_port: 99999`
When `_validate_meta_response()` processes it
Then the result does not include a `ygg_port` field

## ADDED Requirements

### Requirement: ExchangeScreen uses set_mesh_device on fresh browser mount

When ExchangeScreen creates a new PageBrowserWidget in the Pages tab, it must call
`set_mesh_device(device)` rather than setting `_mesh_device` directly. This ensures
`_active_transport` is initialized correctly for the transport selector.

#### Scenario: Fresh browser mount initializes transport
Given a node with NomadNet and I2P transports in the ExchangeScreen Pages tab
When the user selects the node for the first time (fresh browser mount)
Then `set_mesh_device()` is called on the new widget
And `_active_transport` is set to the first available transport
