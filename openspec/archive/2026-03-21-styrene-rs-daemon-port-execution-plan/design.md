# styrene-rs Daemon Port Execution Plan — Design

## Overview

The next Rust daemon port wave should be treated as one coherent architectural migration implemented in bounded slices. The execution plan centers on three clarified architectural nodes:

- **S4**: narrowed to pre-S5 low-risk module hygiene only
- **S2**: MeshTransport trait designed from consumer contracts
- **S5**: AppContext as composition root and service registry, not a renamed god-object

Dependent work such as Unix socket IPC and PropagationClient should follow only after the daemon/service interfaces stabilize.

## Architecture Decisions

### Decision: Organize the daemon port into four waves: prepare, abstract transport, decompose daemon, then unlock dependents

**Status:** decided  
**Rationale:**
- **Wave 0 — Prepare:** perform narrowed S4 low-risk cleanup, inventory RpcDaemon responsibilities, and define target service boundaries and file scope.
- **Wave 1 — Abstract transport:** land S2 MeshTransport with deterministic mocks and explicit lifecycle semantics.
- **Wave 2 — Decompose daemon:** execute S5 in bounded slices: identity/config/status-fleet, messaging/conversations/node-store, protocol/inbound handling, events/tunnel, then RpcDaemon field collapse.
- **Wave 3 — Unlock dependents:** start Unix socket IPC and PropagationClient atop the stabilized daemon/service interfaces.

This sequencing minimizes churn, preserves testability, and creates natural cleave boundaries.

### Decision: Cleave boundaries follow change coupling, not node boundaries

**Status:** decided  
**Rationale:** The existing design nodes are architectural units, but the most efficient implementation split is by coupling and test surface. A good cleave plan should keep each child either interface-first or service-slice-first, with narrow file overlap and explicit dependency order. Transport trait extraction and MockTransport tests can be isolated from later AppContext delegation slices, while pre-S5 daemon module hygiene remains separate from post-S5 daemon breakup.

### Decision: Initial implementation work packages: inventory, transport contract, transport mocks/tests, AppContext foundation, service slices, facade collapse, dependent unlocks

**Status:** decided  
**Rationale:** To maximize execution clarity and parallelism, the daemon port should be broken into small work packages with narrow ownership:

- **Package A** — RpcDaemon inventory + service boundary/file-scope map
- **Package B** — MeshTransport contract and TokioTransport adaptation
- **Package C** — MockTransport and transport contract tests
- **Package D** — AppContext foundation and service registration skeleton
- **Package E** — service slice 1: identity/config/status-fleet delegation
- **Package F** — service slice 2: messaging/conversations/node-store delegation
- **Package G** — service slice 3: protocol/inbound handling delegation
- **Package H** — service slice 4: events/tunnel delegation
- **Package I** — RpcDaemon field collapse + Daemon trait conformance cleanup
- **Package J** — dependent unlock prep for Unix socket IPC and PropagationClient

These packages create a natural serial/parallel graph for cleave.

### Decision: Recommended dependency graph for implementation packages

**Status:** decided  
**Rationale:**
- Package **A** precedes everything because it defines file scope and ownership.
- Package **B** depends on A.
- Package **C** depends on B's contract shape but may proceed in parallel with B's concrete TokioTransport adaptation once semantics are fixed.
- Package **D** depends on A.
- Packages **E–H** each depend on D; **E** should start first to establish the delegation pattern.
- Packages **F/G/H** may then proceed in cautious sequence or limited parallelism depending on file overlap.
- Package **I** depends on E–H being green.
- Package **J** depends on I.

This graph supports fast iteration while respecting the architectural risks identified in assessment.

### Decision: Use one OpenSpec change for the daemon port wave, but multiple cleave children under a single reviewed file-scope map

**Status:** decided  
**Rationale:** These packages are part of one coherent architectural migration and should live under one reviewed OpenSpec change so specs, design, and verification remain unified. Implementation should still be split into multiple cleave children after the file-scope map is established. The first child should produce or validate the file-scope/ownership matrix; later children should cite that matrix to minimize cross-branch conflict.

## Research Context

### Execution sequencing constraints for the next daemon port wave

The daemon port wave is shaped by three clarified truths:

1. **S4** is no longer a full standalone refactor and should be restricted to pre-S5 low-risk module hygiene.
2. **S2** must be designed from consumer-facing contract needs rather than extracted mechanically from TokioTransport.
3. **S5** is the architectural pivot and should decompose RpcDaemon into bounded services without recreating a god-object.

Therefore the port should be staged as: preparation and interface definition first, then bounded service migration slices, then follow-on IPC/client roles.

## File Scope

- `styrene-rs/crates/**/transport*.rs` — transport abstraction, adapters, and mocks for S2
- `styrene-rs/crates/**/rpc/daemon*.rs` — RpcDaemon facade reduction, delegated service calls, and eventual field collapse
- `styrene-rs/crates/**/rpc/mod.rs` — pre-S5 low-risk module hygiene and non-daemon structural cleanup
- `styrene-rs/crates/**/services/*.rs` — new or expanded daemon domain services introduced by S5 slices
- `styrene-rs/crates/**/ipc*.rs` — Daemon trait integration and follow-on Unix socket IPC consumers
- `styrene-rs/crates/**/tests/**/*.rs` — unit/integration coverage for transport abstraction and daemon slice migration

## Constraints

- Implementation planning should treat S4 daemon include breakup as post-S5 work, not part of the initial wave.
- Every wave must preserve compilation and add tests before collapsing old paths.
- Parallel work should avoid overlapping ownership of RpcDaemon internals unless explicitly serialized.
- Unix socket IPC and PropagationClient should not begin until the new daemon/service interfaces are stable enough to consume.
- Package A should produce the authoritative file-scope map and service ownership matrix used by all later tasks.
- Packages B and C may run in parallel once the transport contract is fixed, but C must not invent semantics independently of B.
- Package D should land before service-slice packages E-H begin.
- Packages E-H should be serialized or narrowly parallelized only when file overlap is acceptably low.
- Package I should be last within the daemon wave; it depends on prior service delegation slices being green.
- Package J should remain blocked until Package I proves stable daemon interfaces.