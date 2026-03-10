# I2P Integration — Tasks

## Group 1: I2P adapter and daemon lifecycle

- [x] 1.1 Add `I2PAdapter` lifecycle wiring to the daemon
- [x] 1.2 Start and stop the adapter during daemon startup and shutdown
- [x] 1.3 Expose cached local `.b32.i2p` accessors needed by `/meta` and announces

## Group 2: Capability discovery and `/meta`

- [x] 2.1 Add `CAPABILITY_I2P` to the capability model
- [x] 2.2 Enrich DirectLink `/meta` with local `b32_address` when known
- [x] 2.3 Advertise `CAPABILITY_I2P` conservatively when a usable address is known
- [x] 2.4 Parse remote `CAPABILITY_I2P` announces and persist unknown-address state until `/meta`

## Group 3: Node persistence and config serialization

- [x] 3.1 Add `b32_address` to `MeshDevice`
- [x] 3.2 Add node-store persistence and migration support for `b32_address`
- [x] 3.3 Ensure config serialization includes the `i2p` section

## Group 4: Page browser transport support

- [x] 4.1 Add explicit external URL fetching to `PageBrowserService`
- [x] 4.2 Route `.i2p` URLs through the adapter-provided proxy when enabled
- [x] 4.3 Return the exact disabled-mode error for `.i2p` when `i2p.mode == disabled`
- [x] 4.4 Support direct HTTP(S) fetches as a separate transport from NomadNet
- [x] 4.5 Preserve explicit-transport behavior with no silent fallback between NomadNet, HTTPS, and I2P

## Group 5: Cache integration

- [x] 5.1 Add explicit URL cache helpers for external page fetches
- [x] 5.2 Apply `i2p.cache_ttl` to `.i2p` cached content
- [x] 5.3 Keep NomadNet cache entries distinct from explicit external URL cache entries

## Group 6: IPC and TUI plumbing

- [x] 6.1 Extend page-browser IPC requests to support explicit URL fetches
- [x] 6.2 Add IPC client and bridge methods for external page fetches
- [x] 6.3 Add page browser widget support for external URL mode
- [ ] 6.4 Add a user-visible TUI entrypoint for selecting or entering explicit external docs URLs
- [ ] 6.5 Land the final TUI entrypoint work under `tui-structural-refactor` so it follows the typed-services migration plan

## Group 7: Tests and hygiene

- [x] 7.1 Add focused unit coverage for I2P `/meta`, announce, and capability behavior
- [x] 7.2 Add focused unit coverage for page-browser HTTP(S)/I2P transport behavior
- [x] 7.3 Add focused unit coverage for transport-aware cache behavior
- [x] 7.4 Clean stale design prose that contradicted the decided daemon adoption model
