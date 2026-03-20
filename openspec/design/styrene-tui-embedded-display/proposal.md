# styrene-tui Embedded Display — mousefood + Ratatui on RP2040/ESP32

## Intent

Use mousefood (official Ratatui no_std embedded-graphics backend, now under the ratatui org) to render a minimal operator dashboard on an attached OLED/LCD display for RP2040/ESP32 edge nodes. Same Ratatui widget code (Block, List, Gauge) renders to a 128x64 OLED instead of a terminal. The styrene-tui crate (currently empty scaffold) is the target. Reference: mnyaoo32 (ESP32 IRC client proving the pattern) and mousefood itself. Ratatui 0.30.0 added official no_std support enabling this.

See [styrene-tui Embedded Display — mousefood + Ratatui on RP2040/ESP32 design doc](../../../docs/styrene-tui-embedded-display.md) for full context.
