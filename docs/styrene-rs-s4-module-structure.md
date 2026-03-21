---
id: styrene-rs-s4-module-structure
title: "S4: Replace include!() macros with proper module hierarchy"
status: implemented
parent: styrene-rs-architecture
open_questions: []
---

# S4: Replace include!() macros with proper module hierarchy

## Overview

rpc/daemon.rs uses 16 include!() macros stitching ~8K lines into one compilation unit. Convert each to a proper submodule. Methods move to trait impls or free functions taking &amp;RpcDaemon. Pure refactor — no behavioral change. Enables IDE navigation, rust-analyzer, visibility control, and is prerequisite for S5 (AppContext) decomposition.

## Research

### Assessment: current node title overstates scope; daemon include! conversion is not independently viable pre-S5

Deep assessment confirms the node currently conflates two different refactors: (1) low-risk rpc/mod.rs module cleanup and (2) high-risk rpc/daemon.rs include! breakup. The existing decision already proves the second half is not independently executable because the 8K-line god-impl creates extreme private cross-reference churn. Therefore S4 should be treated as a sequencing and scoping cleanup node, not as a standalone full-tree module conversion task. The viable pre-S5 work is limited to non-daemon module hygiene; the daemon include! breakup is a follow-on enabled by S5 service boundaries.

## Decisions

### Decision: Defer daemon include!() → module conversion until S5 (AppContext) decomposes RpcDaemon

**Status:** decided
**Rationale:** Attempted S4 conversion of rpc/daemon.rs include!() macros into proper submodules. Discovered that the ~8K lines of impl RpcDaemon methods are so deeply cross-referencing (private types, private methods across submodule boundaries) that the conversion produces 720 compile errors requiring a full pub(super) audit across every method. The correct sequencing: S5 (AppContext) will decompose the god-struct into focused services, naturally breaking the cross-dependency web. At that point, each service module will have clean boundaries and the include!() → module conversion follows trivially. S4 on the rpc/mod.rs level (types.rs, helpers.rs, params.rs) can proceed independently and is low-risk — deferred to a separate task.

### Decision: Narrow S4 to pre-S5 low-risk module hygiene; treat daemon include! breakup as a post-S5 follow-on

**Status:** decided
**Rationale:** The failed prior attempt already established that a full rpc/daemon.rs include! conversion before AppContext decomposition produces hundreds of visibility and ownership errors. Keeping S4 framed as a full standalone module-hierarchy conversion invites repeated false starts. The correct interpretation is: S4 may still perform low-risk rpc/mod.rs structure cleanup and any extraction that does not require broad pub(super) churn, but the daemon include! breakup should be explicitly sequenced after S5 creates service boundaries.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- Do not attempt full rpc/daemon.rs include! breakup before S5 service decomposition lands.
- Pre-S5 scope should be restricted to low-risk module hygiene outside the daemon god-impl.
- Any S4 implementation plan should explicitly separate 'pre-S5 cleanup' from 'post-S5 daemon breakup' work packages.
