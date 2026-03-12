---
id: test-path-peer-discovery
title: "Test Path: Peer Discovery &amp; Node Detail"
status: decided
parent: operator-interface-testing
open_questions: []
---

# Test Path: Peer Discovery &amp; Node Detail

## Overview

> Parent: [Operator Interface Testing Paths](operator-interface-testing.md)
> Spawned from: "What's the right boundary between Textual pilot tests (headless TUI automation) and CLI-driven assertions (styrened devices, styrened send)?"

*To be explored.*

## Research

### Functional operations to verify (MeshDeviceDetailScreen)

Each tab in MeshDeviceDetailScreen represents a testing path:

**MESH INFO panel (always visible)**
- [ ] Name, Type, Identity, LXMF hash, Hops, Via, Last Seen all render with expected values
- [ ] "Message" button → navigates to Chat tab
- [ ] "Add Contact" button → adds to contacts list
- [ ] "Copy Hash" button → copies LXMF hash to clipboard

**Status tab**
- [ ] RPC status request fires and returns peer system info (CPU, RAM, uptime, version)
- [ ] Loading spinner shown during request, replaced with data on response
- [ ] Timeout/error handling if peer is unreachable

**Mail tab**
- [ ] Placeholder content renders (v0.16.1 — no functional mail yet)

**Chat tab**
- [ ] Send message → delivered to peer
- [ ] Auto-reply received back within cooldown window
- [ ] Message appears in conversation view with correct timestamps
- [ ] Read receipts sent/received

**Fleet Ops tab**
- [ ] RPC exec command → response displayed
- [ ] RPC status → system info displayed
- [ ] Reboot command (if permitted)

**Terminal tab**
- [ ] Interactive command execution over RPC
- [ ] Output streaming

**Pages tab (if peer runs NomadNet)**
- [ ] Page browser loads index.mu
- [ ] Navigation between pages

## Decisions

### Decision: Both layers, different concerns: pilot for rendering, CLI for protocol

**Status:** decided
**Rationale:** Textual pilot tests verify what the operator sees: widget content, navigation, button behavior, panel rendering. CLI tests (styrened devices, styrened send) verify the daemon protocol layer: announce handling, message delivery, RPC responses. They overlap at the assertion level (both check the same peer identity hash) but test different code paths. Pilot tests catch rendering regressions (like the RemoteStatusInfo.hostname crash); CLI tests catch protocol regressions. Both share the same in-process peer fixture.

## Open Questions

*No open questions.*
