---
id: styrene-rs-s4-module-structure
title: "S4: Replace include!() macros with proper module hierarchy"
status: decided
parent: styrene-rs-architecture
open_questions: []
---

# S4: Replace include!() macros with proper module hierarchy

## Overview

rpc/daemon.rs uses 16 include!() macros stitching ~8K lines into one compilation unit. Convert each to a proper submodule. Methods move to trait impls or free functions taking &amp;RpcDaemon. Pure refactor — no behavioral change. Enables IDE navigation, rust-analyzer, visibility control, and is prerequisite for S5 (AppContext) decomposition.

## Decisions

### Decision: Defer daemon include!() → module conversion until S5 (AppContext) decomposes RpcDaemon

**Status:** decided
**Rationale:** Attempted S4 conversion of rpc/daemon.rs include!() macros into proper submodules. Discovered that the ~8K lines of impl RpcDaemon methods are so deeply cross-referencing (private types, private methods across submodule boundaries) that the conversion produces 720 compile errors requiring a full pub(super) audit across every method. The correct sequencing: S5 (AppContext) will decompose the god-struct into focused services, naturally breaking the cross-dependency web. At that point, each service module will have clean boundaries and the include!() → module conversion follows trivially. S4 on the rpc/mod.rs level (types.rs, helpers.rs, params.rs) can proceed independently and is low-risk — deferred to a separate task.

## Open Questions

*No open questions.*
