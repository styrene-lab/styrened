# Test Path: Peer Discovery &amp; Node Detail — Design Spec (extracted)

> Auto-extracted from docs/test-path-peer-discovery.md at decide-time.

## Decisions

### Both layers, different concerns: pilot for rendering, CLI for protocol (decided)

Textual pilot tests verify what the operator sees: widget content, navigation, button behavior, panel rendering. CLI tests (styrened devices, styrened send) verify the daemon protocol layer: announce handling, message delivery, RPC responses. They overlap at the assertion level (both check the same peer identity hash) but test different code paths. Pilot tests catch rendering regressions (like the RemoteStatusInfo.hostname crash); CLI tests catch protocol regressions. Both share the same in-process peer fixture.

## Research Summary

### Functional operations to verify (MeshDeviceDetailScreen)

Each tab in MeshDeviceDetailScreen represents a testing path:

**MESH INFO panel (always visible)**
- [ ] Name, Type, Identity, LXMF hash, Hops, Via, Last Seen all render with expected values
- [ ] "Message" button → navigates to Chat tab
- [ ] "Add Contact" button → adds to contacts list
- [ ] "Copy Hash" button → copies LXMF hash to clipboard

**Status tab**
- [ ] RPC status request fires and returns peer system info (CPU, RAM, uptime, version)
- [ ] Loading spinner shown during request, repla…
