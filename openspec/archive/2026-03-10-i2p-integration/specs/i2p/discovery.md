# i2p/discovery — Delta Spec

## ADDED Requirements

### Requirement: I2P presence is advertised conservatively to mesh peers

styrened SHALL only advertise I2P capability when I2P is enabled and a usable address is known.

#### Scenario: Capability bit is omitted when no b32 address is available
Given the local node has `i2p.mode` set to `adopt` or `managed`
And no `.b32.i2p` address can be auto-detected or configured
When styrened builds an announce or `/meta` response
Then it omits the I2P address fields
And it does not set `CAPABILITY_I2P`

#### Scenario: Capability bit and meta fields are published when b32 is known
Given the local node has I2P enabled
And styrened knows a `.b32.i2p` address for the node
When styrened builds an announce and `/meta` response
Then it sets `CAPABILITY_I2P` in the announce capability bitmap
And it includes `b32_address` in `/meta`

#### Scenario: Remote I2P capability is stored without requiring the address in the announce
Given a remote announce includes `CAPABILITY_I2P`
When styrened parses the announce
Then it records that the peer supports I2P
And it treats the concrete `.b32.i2p` address as unknown until `/meta` is fetched
