---
id: styrene-rs-service-workers
title: Service-layer Workers — Inbound + Announce Processing Pipeline
status: implemented
parent: styrene-rs-daemon-port-execution-plan
tags: [rust, daemon, workers, inbound, announce, events]
open_questions: []
---

# Service-layer Workers — Inbound + Announce Processing Pipeline

## Overview

Background workers bridging MeshTransport events to the service layer. Inbound worker: transport data → LXMF decode → MessagingService persist → ProtocolService dispatch → EventService emit. Announce worker: transport announce → DiscoveryService peer table → EventService emit. EventService dual-broadcasts RpcEvent (internal) + DaemonEvent (IPC). DaemonFacade subscriptions return live broadcast receivers.

## Open Questions

*No open questions.*
