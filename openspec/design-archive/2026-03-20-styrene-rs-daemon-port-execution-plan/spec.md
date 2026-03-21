# styrene-rs Daemon Port Execution Plan — Design Spec (extracted)

> Auto-extracted from docs/styrene-rs-daemon-port-execution-plan.md at decide-time.

## Decisions

### Organize the daemon port into four waves: prepare, abstract transport, decompose daemon, then unlock dependents (decided)

Wave 0 (prepare) performs narrowed S4 low-risk cleanup, inventories RpcDaemon responsibilities, and identifies target service boundaries and file scope. Wave 1 (abstract transport) lands S2 MeshTransport with deterministic mocks and explicit lifecycle semantics. Wave 2 (decompose daemon) executes S5 in bounded slices: identity/config/status-fleet, messaging/conversations/node-store, protocol/inbound handling, events/tunnel, then RpcDaemon field collapse. Wave 3 (unlock dependents) starts Unix socket IPC and PropagationClient on top of the new daemon/service interfaces. This sequencing minimizes churn, preserves testability, and creates natural cleave boundaries.

### Cleave boundaries follow change coupling, not node boundaries (decided)

The existing design nodes are architectural units, but the most efficient implementation split is by coupling and test surface. A good cleave plan should keep each child either interface-first or service-slice-first, with narrow file overlap and explicit dependency order. For example, transport trait extraction and MockTransport tests can be isolated from later AppContext delegation slices, while pre-S5 daemon module hygiene remains separate from post-S5 daemon breakup. This reduces merge conflicts and shortens feedback loops.

### Initial implementation work packages: inventory, transport contract, transport mocks/tests, AppContext foundation, service slices, facade collapse, dependent unlocks (decided)

To maximize execution clarity and parallelism, the daemon port should be broken into small work packages with narrow ownership: (A) RpcDaemon inventory + service boundary/file-scope map, (B) MeshTransport contract and TokioTransport adaptation, (C) MockTransport and transport contract tests, (D) AppContext foundation and service registration skeleton, (E) service slice 1 — identity/config/status-fleet delegation, (F) service slice 2 — messaging/conversations/node-store delegation, (G) service slice 3 — protocol/inbound handling delegation, (H) service slice 4 — events/tunnel delegation, (I) RpcDaemon field collapse + Daemon trait conformance cleanup, (J) dependent unlock prep for Unix socket IPC and PropagationClient. These packages create a natural serial/parallel graph for cleave.

### Recommended dependency graph for implementation packages (decided)

Package A precedes everything because it defines file scope and ownership. Package B depends on A. Package C depends on B's contract shape but may proceed in parallel with B's concrete TokioTransport adaptation once semantics are fixed. Package D depends on A and may begin once the service map is stable. Packages E-H each depend on D; E should start first to establish the delegation pattern, F/G/H can then proceed in cautious sequence or limited parallelism depending on file overlap. Package I depends on E-H being green. Package J depends on I. This graph supports fast iteration while respecting the architectural risks identified in assessment.

### Use one OpenSpec change for the daemon port wave, but multiple cleave children under a single reviewed file-scope map (decided)

These packages are part of one coherent architectural migration and should live under one reviewed OpenSpec change so specs, design, and verification remain unified. However implementation should be split into multiple cleave children after the file-scope map is established. This avoids premature fragmentation at the spec layer while still enabling parallel execution where safe. The first child should produce or validate the file-scope/ownership matrix; later children should cite that matrix to minimize cross-branch conflict.

## Research Summary

### Execution sequencing constraints for the next daemon port wave

The daemon port wave is shaped by three clarified truths: (1) S4 is no longer a full standalone refactor and should be restricted to pre-S5 low-risk module hygiene; (2) S2 must be designed from consumer-facing contract needs rather than extracted mechanically from TokioTransport; (3) S5 is the architectural pivot and should decompose RpcDaemon into bounded services without recreating a god-object. Therefore the port should be staged as: preparation and interface definition first, then bounded se…
