# i2p/adapter — Delta Spec

## ADDED Requirements

### Requirement: I2P adapter supports DISABLED, ADOPT, and MANAGED modes

styrened SHALL integrate with i2pd through the existing DaemonAdapter pattern.

#### Scenario: Managed mode uses non-conflicting ports
Given `i2p.mode` is `managed`
When styrened generates i2pd configuration
Then the HTTP proxy listens on port `4445`
And I2PControl listens on port `7651`
And the generated config is written under `~/.styrene/i2pd/`

#### Scenario: Adopt mode probes the system instance
Given `i2p.mode` is `adopt`
When styrened probes I2P availability
Then it checks the configured HTTP proxy host and port
And it does not generate config or spawn an i2pd process

#### Scenario: b32 address autodetection falls back to operator config
Given I2PControl does not return a `.b32.i2p` address
And `i2p.b32_address` is configured
When styrened gathers I2P details
Then it uses the configured `b32_address`

#### Scenario: Disabled mode does not expose an HTTP proxy
Given `i2p.mode` is `disabled`
When callers ask for the effective proxy URL
Then the adapter returns `None`
