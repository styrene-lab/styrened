# COP-First Home Screen Reorganization

## Intent

Reorganize the TUI Home screen from identity/metadata-first to Common Operating Picture (COP)-first layout. Replace the two-panel HOME STATUS + COMMS split with: (1) a compact 1-2 line status bar showing all state dimmed with anomalies promoted (SCADA pattern), (2) a compact read-only HomeNodeSummaryTable as the primary display (Name|Status|Recency|Unread, sorted abnormal-first, Enter drills into peer workspace), (3) a compact activity feed showing recent events with timestamps. Also implement the already-decided footer consolidation: hide c/b bindings per tui-navigation-ux decision, dropping visible footer items from 10 to ~6. All widgets already exist in the codebase — this is reorganization and composition, not greenfield development. Derived from the tui-ux-assessment-2026-03 design node (decided).

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
