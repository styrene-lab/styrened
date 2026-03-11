---
id: internal-event-bus
title: Internal Event Bus
status: seed
parent: interface-boundary-logging
tags: [architecture, eventing, deferred]
open_questions: []
---

# Internal Event Bus

## Overview

Long-term: a unified internal pub/sub hub (asyncio.Queue or lightweight broker) that NotificationService, boundary logging, relay lifecycle, and other daemon services all publish to. Currently three separate eventing mechanisms exist (NotificationService callbacks, SSEBroadcaster for web, IPC EVENT_* messages) with no shared internal bus. Boundary logging deliberately avoids plugging into NotificationService (wrong abstraction) — the right fix is a first-class internal bus, not retrofitting. Deferred: not worth blocking boundary logging or any v0.17 feature on this.

## Open Questions

*No open questions.*
