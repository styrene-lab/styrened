---
id: tui-exploration-row-key-collision
title: Exploration row-key collisions on duplicate identities
status: implemented
parent: tui-startup-ipc-backpressure
tags: [tui, nodes, bug, regression]
open_questions: []
issue_type: bug
priority: 1
---

# Exploration row-key collisions on duplicate identities

## Overview

ExplorationScreen can crash on startup when Reticulum discovery returns multiple non-Styrene or pages entries that share an identity hash. The current tables key DataTable rows by identity_hash even when the dataset is only deduplicated by destination_hash, so duplicate identities trigger Textual DuplicateKey during table rebuild.

## Research

### Root cause from live dev-tui crash

The startup crash occurs in ReticumAnnounceTable._rebuild_table() when Textual add_row() receives a duplicate row key. ExplorationScreen._load_all_devices() deduplicates raw discovery only by destination_hash, but ReticumAnnounceTable and StyreneFleetTable currently key rows by identity_hash. On large meshes it is valid to encounter multiple announces/endpoints that share an identity hash while differing by destination or service aspect, so the table can attempt to render distinct rows with the same identity-based key and crash during on_mount.

### Regression coverage confirmed the destination-key fix

After switching Exploration row keys to destination hashes and resolving selections back to MeshDevice identities, targeted verification passed for the crash path and downstream detail/chat flows. Regression tests now cover duplicate-identity rows in Other and Pages tabs plus selection routing when row keys are destination based.

## Decisions

### Decision: Exploration tables should key rows by destination hash and map selection back to identity-aware flows

**Status:** decided
**Rationale:** DataTable row keys must be unique per rendered row. destination_hash already identifies the concrete announce/endpoint row and is the axis used for raw deduplication, so it is the correct table key. Identity-oriented downstream flows like MeshDeviceDetailScreen can still receive device.identity_hash after the selected destination row is resolved back to its MeshDevice. This fixes the crash without suppressing legitimate multi-endpoint rows or reintroducing per-screen caches.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/exploration.py` (modified) — Use destination-hash row keys in exploration tables and translate selected rows back to identity-oriented detail/chat flows.
- `tests/tui/screens/test_exploration.py` (modified) — Add regressions covering duplicate-identity rows in Other/Pages tabs and selection routing when row keys are destination hashes.

### Constraints

- Do not suppress legitimate multi-endpoint rows merely to avoid DuplicateKey collisions.
- Keep MeshDeviceDetailScreen identity-oriented even if table selection keys switch to destination hashes.
