---
id: styrene-rs-propagation-client
title: PropagationClient node role — thin LXMF client mode
status: decided
parent: styrene-rs-architecture
dependencies: [styrene-rs-s5-app-context]
open_questions: []
---

# PropagationClient node role — thin LXMF client mode

## Overview

First-class NodeRole::PropagationClient mode: device registers with a hub as an LXMF propagation client but does NOT route traffic, maintain announce tables for others, or run a full transport layer. Required for mobile Tier 1 (hub-connected client). On iOS the app wakes from APNs/UnifiedPush, connects to hub, fetches pending messages via LXMF propagation store protocol, then disconnects. Distinct from NodeRole::FullNode (runs transport, routes packets) and NodeRole::Hub (propagation store operator). Needs explicit modeling in AppContext config and the LXMF service layer.

## Open Questions

*No open questions.*
