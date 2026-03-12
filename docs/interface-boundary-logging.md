---
id: interface-boundary-logging
title: Interface Boundary Logging — Differentiated Error Telemetry Across Tech Stacks
status: implemented
tags: [logging, observability, rns, lxmf, yggdrasil, i2p, wireguard, diagnostics, dx]
open_questions: []
branches: ["feature/interface-boundary-logging"]
openspec_change: interface-boundary-logging
---

# Interface Boundary Logging — Differentiated Error Telemetry Across Tech Stacks

## Overview

Styrene is absorbing multiple independent networking stacks (RNS, LXMF, Yggdrasil, I2P, WireGuard, launchd/systemd, NomadNet page protocol) each with its own error taxonomy, log format, and thread model. When something breaks it's currently hard to tell which layer failed — an RNS path-not-found looks similar to an LXMF delivery timeout which looks similar to a WireGuard handshake failure at the log level we surface.

Goal: a structured "up-flow" logging layer that tags errors with their interface boundary of origin, normalises severity across stacks, and gives the operator (and doctor) enough signal to diagnose cross-stack failures without grepping through interleaved third-party log lines.

Motivating example: the RNS ratchet persist race (d246a39 / b405828) required reading CPython threading internals to determine it was benign. With boundary logging that context would be encoded in the log record itself.

## Research

### Motivating Cases

- **RNS ratchet persist race** (b405828): daemon thread `FileNotFoundError` in `RNS/Identity.py:persist_job` — required reading CPython threading internals to classify as benign. Fixed with a targeted `threading.excepthook`. With boundary logging this would be tagged `boundary=rns, severity=transient, retryable=True` and suppressed/contextualised automatically.
- **DirectLink establish hang** (known issue): `DirectLinkService.establish()` timeout after 60s — unclear whether failure is at the RNS path-discovery layer, the link handshake layer, or the IPC bridge timeout layer.
- **Page browser link failure** (known issue): TUI reports "Link establishment failed" even when standalone RNS client succeeds — the boundary between the shared RNS instance and the daemon-managed link is invisible in current logs.
- **Hub peer mismatch** (fixed v0.10.49): config had `192.168.0.200:4242` instead of `rns.styrene.io` — no log distinguished "RNS TCPClientInterface connect failed" from "no Styrene peers found".

## Decisions

### Decision: Interface boundary tag enum

**Status:** decided
**Rationale:** 11-value InterfaceBoundary(str, Enum): RNS, LXMF, NOMADNET, YGGDRASIL, I2P, WIREGUARD (transport overlays, future — zero cost to define now, avoids future breaking change), IPC, RPC, SERVICE_MANAGER, ASYNC_WORKER, INTERNAL. Stable string values so TUI and doctor can filter without string matching.

### Decision: Structured log records only — no BoundaryError hierarchy

**Status:** decided
**Rationale:** Third-party stacks raise their own exceptions — we intercept after the fact via threading.excepthook, sys.unraisablehook, and try/except in adapters. Re-raising as BoundaryError changes stack traces. logging.LogRecord extra= dict is zero-overhead, composable, and doesn't require callers to change exception handling. Schema: boundary (InterfaceBoundary), severity (transient|degraded|fatal), retryable (bool), stack_name (str), operation (str). Future: __cause__/__context__ wrapping in adapter code if interactive debugging needs it — no hierarchy required.

### Decision: Doctor consumption via ring buffer + optional NDJSON sink

**Status:** decided
**Rationale:** BoundaryLogHandler(logging.Handler) appends boundary-tagged records to a collections.deque(maxlen=200) — O(1), thread-safe, zero file I/O. Doctor reads it via a new CMD_BOUNDARY_SNAPSHOT IPC command when daemon is running; falls back to point-in-time checks when daemon is not running. Optional NDJSON sink at ~/.local/share/styrene/boundary.log (size-rotated, off by default, enabled via logging.boundary_sink: true) for post-mortem debugging. Explicitly does NOT plug into NotificationService — wrong abstraction. TUI live feed deferred: can add a thin forwarder (deque → EVENT_ACTIVITY with event_type=boundary_error) as a follow-on without redesign.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/daemon.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes

### Constraints

- Must not require changes to RNS/LXMF/Yggdrasil/I2P library internals — all instrumentation lives in styrened adapters and hooks
- threading.excepthook and sys.unraisablehook are the two entry points for third-party daemon thread errors — both need boundary-aware handlers
- Log records must be machine-readable (JSON sink option) to support future doctor ring-buffer consumption
- Boundary tags should be stable enum values so TUI and doctor can filter/group by them without string matching
