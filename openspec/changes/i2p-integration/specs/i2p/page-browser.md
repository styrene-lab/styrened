# i2p/page-browser — Delta Spec

## MODIFIED Requirements

### Requirement: The page browser routes `.i2p` requests through the configured I2P proxy

The page browser SHALL support explicit external transports alongside NomadNet and route `.i2p` requests through the configured I2P proxy.

#### Scenario: `.i2p` requests use the configured proxy when I2P is enabled
Given `i2p.mode` is `adopt` or `managed`
And the local I2P HTTP proxy is available
When the page browser fetches an explicit `.i2p` URL
Then styrened routes that request through the configured I2P proxy
And it does not fetch the URL directly over clearnet HTTP

#### Scenario: `.i2p` requests fail clearly when I2P is disabled
Given `i2p.mode` is `disabled`
When the page browser fetches an explicit `.i2p` URL
Then the fetch fails without contacting the URL
And the error message is `I2P not enabled — set i2p.mode: adopt or managed in config.`

#### Scenario: `.i2p` requests fail clearly when the proxy is not ready
Given `i2p.mode` is `adopt` or `managed`
And no usable I2P HTTP proxy is currently available
When the page browser fetches an explicit `.i2p` URL
Then styrened returns an operator-facing error explaining that the I2P proxy is not ready yet

### Requirement: Explicit HTTP(S) page browsing remains available without I2P

The page browser SHALL support direct HTTP(S) fetches as a separate transport from NomadNet and I2P.

#### Scenario: HTTPS fetches succeed without I2P enablement
Given `i2p.mode` is `disabled`
When the page browser fetches an explicit `https://` URL
Then styrened fetches it directly over HTTP(S)
And it does not require an I2P adapter or proxy

### Requirement: Graceful degradation uses explicit parallel endpoints rather than fallback

The same content MAY be published on NomadNet, HTTPS, and I2P at the same time, but styrened SHALL treat each request as transport-specific.

#### Scenario: Operators can publish the same content on multiple transports
Given the same documentation is published on `nomadnet://`, `https://`, and `.i2p` endpoints
When one transport is unavailable or disabled
Then styrened returns a clear transport-specific error for that request
And it does not silently reroute the request onto another transport
And operators remain free to choose a parallel endpoint explicitly

### Requirement: External transport cache behavior is transport-aware

The page cache SHALL support explicit URL cache entries and apply the configured I2P cache TTL to `.i2p` content.

#### Scenario: `.i2p` cached content uses the I2P cache TTL
Given an explicit `.i2p` URL was fetched successfully and cached
When styrened looks up cached content for that URL after a failed live fetch
Then it only reuses the cached entry while it remains within `i2p.cache_ttl`

#### Scenario: Explicit HTTPS cached content is stored separately from NomadNet paths
Given an explicit `https://` URL was fetched successfully and cached
When styrened reads or writes the cache for that URL
Then it uses a cache key distinct from NomadNet destination-hash path entries
