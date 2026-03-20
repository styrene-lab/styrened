---
id: styrene-rs-s5-app-context
title: "S5: AppContext — decompose RpcDaemon god-struct into service registry"
status: exploring
parent: styrene-rs-architecture
dependencies: [styrene-rs-s1-arc-runtime, styrene-rs-s2-mesh-transport-trait, styrene-rs-s4-module-structure]
open_questions: []
---

# S5: AppContext — decompose RpcDaemon god-struct into service registry

## Overview

RpcDaemon is a god-struct with 40+ Mutex fields. styrene-ipc already defines the Daemon composite trait (DaemonMessaging, DaemonIdentity, DaemonStatus, DaemonFleet, DaemonEvents, DaemonTunnel) but RpcDaemon does not implement it yet. AppContext owns all services (transport, messages, conversations, node_store, auto_reply, protocols, config, identity). RpcDaemon becomes a thin RPC dispatch layer that delegates to AppContext services. Services receive Arc&lt;AppContext&gt; and subscribe to transport events via broadcast channels. Depends on S1 (Arc), S2 (MeshTransport trait), S4 (modules).

## Open Questions

*No open questions.*
