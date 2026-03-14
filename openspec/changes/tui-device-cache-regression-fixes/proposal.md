# TUI Device Cache Regression Fixes

## Intent

Repair regressions introduced during the DeviceCache migration and splash-first startup integration: preserve fallback semantics when the shared cache is empty or unprimed, prevent bare-screen app access from masquerading as daemon failure, update tests for the Home/Nodes ownership split, and reconcile splash-first startup expectations.

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
