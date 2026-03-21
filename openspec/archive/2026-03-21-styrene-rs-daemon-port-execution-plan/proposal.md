# styrene-rs Daemon Port Execution Plan

## Intent

Define the formal execution plan for the next Rust daemon port wave inside `styrened`, without starting implementation in this pass.

This change turns the resolved architecture work into an implementation-ready planning artifact for the `styrene-rs` daemon port. It sequences:

- **S4** narrowed to pre-S5 low-risk module hygiene
- **S2** MeshTransport abstraction
- **S5** AppContext/service-registry decomposition
- dependent unlocks for Unix socket IPC and PropagationClient

## Why

The Rust daemon is the truest path toward a full-Rust Styrene runtime. TUI work should follow stable daemon/service interfaces rather than co-evolving against a moving internal structure.

The purpose of this change is to create a reviewed plan that supports:

- OpenSpec-driven implementation
- safe decomposition into cleave children
- narrow file ownership and reduced merge conflict risk
- incremental migration with tests and green builds at every step

## Scope

This planning change covers:

1. execution waves and dependency order
2. work-package boundaries for cleave
3. file-scope expectations
4. migration constraints and guardrails
5. handoff structure for future implementation

This change does **not** itself implement the daemon port.