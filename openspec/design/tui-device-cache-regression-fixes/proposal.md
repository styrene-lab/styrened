# TUI Device Cache Regression Fixes

## Intent

Repair the regressions introduced during the DeviceCache migration and splash-first startup integration: preserve usable fallback semantics when the shared cache is empty or unprimed, avoid bare-screen app access crashes, update tests for the Home/Nodes ownership split, and reconcile startup expectations around the splash screen.

See [TUI Device Cache Regression Fixes design doc](../../../docs/tui-device-cache-regression-fixes.md) for full context.
