# UI State Model

## ADDED Requirements

### Requirement: Shared UI-facing state is snapshot-based and frontend-agnostic

The application SHALL expose canonical typed state objects and projection helpers that are independent of Textual so multiple frontends can consume the same post-IPC model.

#### Scenario: Textual TUI consumes shared canonical state
Given the Textual TUI needs node, config, and message state
When it loads data from daemon IPC
Then it normalizes that data through the shared UI-facing state layer
And screens/widgets do not reinterpret raw IPC payloads independently

#### Scenario: A future non-TUI frontend can consume the same state model
Given another frontend such as a web UI needs the same daemon information
When it consumes post-IPC state
Then it can use the same canonical state objects and projection helpers
And the model does not depend on Textual screen or widget classes

#### Scenario: Shared UI state does not require a background state machine
Given a frontend requests updated daemon information
When the shared UI-facing layer constructs canonical state
Then it does so from explicit authoritative input snapshots
And it does not require its own always-on cache, poller, or persistence layer

### Requirement: Shared UI-facing state has strict boundaries

The shared UI-facing state layer SHALL be a pure normalization boundary with no direct runtime dependencies on daemon services or visual frameworks.

#### Scenario: Builders do not reach back into IPC or databases
Given a shared state builder function
When it constructs canonical state
Then it accepts all authoritative inputs through an explicit input bundle
And it does not perform IPC calls, direct database reads, or daemon service lookups on its own

#### Scenario: Shared state package remains visual-framework agnostic
Given the shared `ui_state` package
When inspecting its runtime dependencies
Then it contains no Textual screen, widget, or rendering types
And frontend-specific projection adapters remain outside the shared package

### Requirement: Canonical aggregates define the minimum shared UI state surface

The shared state layer SHALL define canonical aggregates for node catalog, mail index, comms workspace state, peer workspace context, config draft state, local daemon state, and page-browser session state.

#### Scenario: Node catalog normalizes identity-centric mesh state once
Given node data arrives from authoritative daemon IPC sources
When the shared state layer builds the node catalog
Then it merges and normalizes that data into canonical node records
And screens consume those records rather than deduplicating or merging nodes locally

#### Scenario: Mail index state models asynchronous correspondence
Given a frontend loads store-and-forward message threads
When the shared state layer builds the mail index
Then it emits canonical async thread summaries, unread state, and compose/search metadata
And the model does not imply live-session semantics for those threads

#### Scenario: Mail index distinguishes direct, group, and forum scopes
Given authoritative async discussion inputs from multiple transports or transports carrying different discussion types
When the shared state layer builds the mail index
Then each thread is tagged with a canonical scope kind such as direct, group, or forum
And direct threads remain identity-centric
And group threads remain room-centric with room metadata and membership epoch state
And forum threads remain topic-centric rather than being forced into peer-thread grouping

#### Scenario: Group-thread participant state is transport-unified but capability-aware
Given a private group thread includes participants with different currently available transports
When the shared state layer builds canonical room-participant state
Then participant membership remains attached to the one room identity rather than forked per transport
And each participant can expose highest-available authoritative route metadata, fallback routes, and delivery-friction state
And constrained-path participants such as LoRa-only peers remain part of the same room model

#### Scenario: Group-thread state carries media-friction metadata for constrained paths
Given a participant is currently reachable only over a low-bandwidth or high-latency route
When the shared state layer builds group-thread participant or delivery metadata
Then it can mark that participant or send path as requiring confirmation for expensive media operations
And the UI does not need to infer constrained-path media policy ad hoc at render time

#### Scenario: Group-thread state includes footprint tier and bounded-retention policy
Given the local node is operating under a constrained group-thread feature tier
When the shared state layer builds canonical room state
Then it can expose whether rich features such as deep local history, automatic media fetch, or aggressive background catch-up are reduced or disabled
And the room identity, membership, and basic async participation model remain intact

#### Scenario: Comms workspace state models live-capable communication modes
Given a frontend loads communication capability and session snapshots from authoritative daemon inputs
When the shared state layer builds comms workspace state
Then it exposes transport-aware submodes such as Direct, Active, Bridges, and Presence
And future live capabilities like voice/video remain capability-gated rather than synthesized by the UI

#### Scenario: Peer workspace context preserves origin and comms focus
Given a frontend opens a selected peer from Nodes, Mail, or Comms
When the shared state layer builds peer workspace context
Then it records the originating workspace and requested focus such as mail, comms, pages, or ops
And Back navigation can return to the correct aggregate workspace without screen-local guesswork

#### Scenario: Config draft state separates persisted config from editable UI state
Given a frontend loads daemon configuration for editing
When the shared state layer creates config draft state
Then it keeps persisted and editable state distinct
And it can report dirty fields, validation errors, and save/reset state without raw dict mutation in screens

#### Scenario: Page browser session state keeps transport policy separate from rendering
Given a frontend opens NomadNet, HTTPS, or I2P content
When the shared state layer tracks page-browser session state
Then it records transport, cache fallback state, and action capabilities in canonical form
And the visual layer only decides how to present that state

### Requirement: Capability-specific state is only populated when the capability exists

The shared UI-facing state layer SHALL not synthesize runtime state or persistence for disabled daemon capabilities.

#### Scenario: Yggdrasil state remains unsupported when the daemon capability is disabled
Given the daemon has Yggdrasil disabled and exposes no Yggdrasil runtime data
When the shared state layer builds node catalog and local daemon state
Then Yggdrasil submodels remain absent or marked unsupported
And no synthetic peer, route, or persistence state is created for Yggdrasil

#### Scenario: Yggdrasil state is populated when authoritative runtime inputs exist
Given the daemon enables Yggdrasil and exposes runtime or peer data for it
When the shared state layer builds canonical node or local daemon state
Then it includes Yggdrasil-specific fields using those authoritative inputs
And it does not require a separate UI-owned tracker or database to do so

#### Scenario: I2P state appears only when the daemon advertises or enables I2P
Given the daemon enables I2P or a peer advertises I2P capability
When the shared state layer builds canonical node or page-browser state
Then it includes I2P-specific fields using authoritative daemon inputs
And disabled-mode frontends do not need a separate state store to represent I2P

#### Scenario: Shared UI state does not create shadow persistence
Given a capability is disabled and the daemon has no persistence for it
When a frontend constructs canonical state
Then the shared UI-facing layer keeps no independent database or shadow store for that capability
And persistence remains owned by the daemon subsystem that actually implements the feature
