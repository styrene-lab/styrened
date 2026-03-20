---
id: styrene-rs-s2-mesh-transport-trait
title: "S2: MeshTransport trait — testable, swappable transport backend"
status: decided
parent: styrene-rs-architecture
open_questions: []
---

# S2: MeshTransport trait — testable, swappable transport backend

## Overview

Transport is a 500+ LOC concrete struct with direct tokio::spawn and hardcoded TCP/UDP. Extract MeshTransport trait: send_packet, send_announce, request_path, link, subscribe_announces, subscribe_inbound, destination_identity. TokioTransport implements the trait. MockTransport enables unit tests without real network. WasmTransport (future) implements over WebSocket for browser targets. Required for AppContext service registry (S5) and testability of all service layer code.

## Open Questions

*No open questions.*
