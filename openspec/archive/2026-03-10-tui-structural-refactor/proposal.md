# TUI Structural Refactor — Typed Services, IPC-Only, Keymap

## Intent

Fix foundational TUI issues: (1) Define typed TUIServices protocol replacing implicit app contract and all type:ignore[attr-defined] patterns. (2) Migrate 42 direct daemon service imports in screens/widgets to IPC bridge calls, adding ~5 missing IPC commands. (3) Remove LifecycleMode.LEGACY — daemon is the only runtime. (4) Document keymap contract. (5) Remove db_engine leak from UI layer.

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
