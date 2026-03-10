# Workspace Architecture

## ADDED Requirements

### Requirement: The TUI defines stable primary workspaces and a canonical peer workspace

The TUI SHALL organize primary navigation around Home, Nodes, Mail, Comms, Contacts, and Admin, with a separate peer workspace as the canonical selected-peer drill-down.

#### Scenario: Primary workspaces have distinct responsibilities
Given the operator navigates the TUI
When they move between top-level workspaces
Then Home owns overview and launch summaries
And Nodes owns peer discovery and browsing
And Mail owns asynchronous store-and-forward correspondence
And Comms owns synchronous and session-oriented communication
And Contacts owns directory management
And Admin owns configuration, provisioning, and maintenance flows

#### Scenario: Peer workspace is not treated as a top-level aggregate workspace
Given the operator selects a peer from Nodes, Mail, Comms, Contacts, or Home summaries
When the TUI opens peer-specific interaction surfaces
Then it opens the peer workspace as a drill-down context
And aggregate global views remain in the originating workspace rather than being recreated inside the peer workspace

### Requirement: Mail and Comms remain separate time-model workspaces

The TUI SHALL separate asynchronous correspondence from synchronous communication in the primary workspace model.

#### Scenario: Mail owns asynchronous thread workflows
Given the operator wants inbox-style communication history
When they open Mail
Then they can triage unread threads, compose asynchronous correspondence, search message history, and sync store-and-forward state
And the workspace does not imply live-session semantics for those threads

#### Scenario: Mail unifies async correspondence without flattening discussion scope
Given the operator views asynchronous correspondence from direct peers, private groups, and forum-style discussions
When Mail renders the inbox and thread list
Then it presents a unified asynchronous workspace rather than protocol-silo tabs
And it preserves scope distinctions such as direct, group, and forum in thread metadata and affordances
And it does not force group or forum discussion into a one-peer thread model

#### Scenario: Group threads remain one room across varying participant transports
Given a private room contains members whose best current routes differ such as high-bandwidth links, hub-assisted async delivery, or LoRa-only RNS paths
When the operator opens that room in Mail
Then the workspace shows one group thread rather than separate transport-specific copies
And each participant can be shown with their highest currently available authoritative interface and any relevant delivery constraints

#### Scenario: Group-thread UX warns before expensive media operations on constrained paths
Given a room participant is currently reachable only through a constrained route such as LoRa
When the operator attempts an expensive media-related action for that room
Then the Mail workspace can surface a confirmation or warning before attempting the transfer
And the room still remains available for normal asynchronous participation over that constrained path

#### Scenario: Group-thread feature tier degrades capabilities without hiding the room
Given the local node is configured for a constrained group-thread storage or feature tier
When the operator opens a room
Then the workspace can show that local history retention, auto-fetch, or rich-media conveniences are reduced
And the room still appears as the same room with the same membership and invitation semantics
And degraded behavior does not fork the room by transport

#### Scenario: Comms owns synchronous and live-capable workflows
Given the operator wants real-time or near-real-time interaction
When they open Comms
Then they can access direct communication, active sessions, presence, invites, and bridge-backed live communication
And the workspace does not become a second inbox for asynchronous thread history

### Requirement: Comms exposes transport-aware submodes

The Comms workspace SHALL expose transport- and session-aware submodes instead of a single undifferentiated chat list.

#### Scenario: Comms exposes direct and bridge-aware views
Given the operator opens Comms
When the workspace renders available communication modes
Then it includes submodes such as Direct, Active, Bridges, and Presence
And Direct can host synchronous text chat and future call affordances
And Bridges can surface Meshtastic, Yggdrasil, I2P, and other authoritative bridge-backed communication routes when available

#### Scenario: Unsupported live capabilities remain capability-gated
Given the daemon does not expose authoritative voice, video, or bridge runtime state
When the TUI renders Comms
Then unsupported capabilities appear as absent, disabled, or clearly unavailable
And the UI does not fabricate synthetic live-session state

### Requirement: Peer workspace preserves origin-aware navigation

The peer workspace SHALL preserve the originating workspace and requested focus so navigation returns to the correct aggregate context.

#### Scenario: Opening a peer from Nodes returns to Nodes
Given the operator opens a peer from Nodes
When they leave the peer workspace
Then Back returns them to Nodes unless a deeper transient peer-local mode is still open

#### Scenario: Opening a peer from Mail or Comms returns to the originating workspace
Given the operator opens a peer from Mail or Comms
When they leave the peer workspace
Then Back returns them to the originating workspace
And the peer workspace can still focus the requested surface such as mail, comms, pages, or ops
