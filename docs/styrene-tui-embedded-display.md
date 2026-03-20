---
id: styrene-tui-embedded-display
title: "styrene-tui Embedded Display — mousefood + Ratatui on RP2040/ESP32"
status: exploring
parent: styrene-rs-architecture
tags: [tui, embedded, ratatui, mousefood, rp2040, esp32, edge]
open_questions: []
---

# styrene-tui Embedded Display — mousefood + Ratatui on RP2040/ESP32

## Overview

Use mousefood (official Ratatui no_std embedded-graphics backend, now under the ratatui org) to render a minimal operator dashboard on an attached OLED/LCD display for RP2040/ESP32 edge nodes. Same Ratatui widget code (Block, List, Gauge) renders to a 128x64 OLED instead of a terminal. The styrene-tui crate (currently empty scaffold) is the target. Reference: mnyaoo32 (ESP32 IRC client proving the pattern) and mousefood itself. Ratatui 0.30.0 added official no_std support enabling this.

## Research

### Phone-OS — full app framework for ESP32 CYD touchscreen (primary reference)

Julien-cpsn/Phone-OS: A phone OS proof-of-concept for the ESP32 CYD (Cheap Yellow Display) board — ~$10 ESP32 with built-in 320×240 ILI9341 capacitive touchscreen (ft6206 driver). Written in Rust. Uses mousefood for Ratatui rendering + embedded-graphics.

Key features already implemented:
- Async event/UI architecture with synchronized world time
- Persistent storage via SD card
- Touch buttons and AZERTY/symbols touch keyboard
- WiFi app: AP scan, password entry, auto-connect to known networks
- App framework: `trait App` with home screen navigation between apps
- esp-idf-svc for WiFi and ESP32 services (PSRAM enabled)

**Direct applicability to Styrene edge node console:**
- The `App` trait + home screen → Styrene workspace model
- WiFi settings app → `styrened doctor --setup` wizard for embedded
- Touch keyboard → LXMF message composition
- The CYD board ($10-15) is a compelling Styrene operator console: WiFi + touchscreen + enough memory (16MB flash, 4MB PSRAM)

A Styrene CYD operator flow:
1. Boot → WiFi setup (already in Phone-OS)
2. Styrene identity setup (new app)
3. Hub connection + mesh status dashboard (new app)
4. Messages inbox + compose via touch keyboard (new app, touch keyboard from Phone-OS)

**Hardware target:** ESP32 CYD is distinct from RP2040 (no touchscreen). Both are relevant but serve different operator models:
- ESP32 CYD: standalone interactive operator console (~$10)
- RP2040: headless mesh node with small status OLED, no touch (cheaper, more constrained)

Cargo.toml deps: mousefood = "0.2.1", embedded-graphics = "0.8.1", ili9341 = "0.6.0", ft6206 driver, esp-idf-svc, heapless, crossbeam-channel.

Repo: https://github.com/Julien-cpsn/Phone-OS (WIP, ~36 stars, MIT-ish)

## Decisions

### Decision: Two distinct embedded targets: ESP32 CYD (interactive console) and RP2040 (headless status display)

**Status:** decided
**Rationale:** ESP32 CYD (~$10, 320×240 touch, WiFi, 16MB flash): full operator console with touch input, WiFi management, message composition. Phone-OS provides the reference app framework. RP2040 (~$4-6, small OLED, no touch, LoRa): headless mesh node with a minimal status display (peers, queue, signal). Different operator models — CYD is the dedicated mesh terminal, RP2040 is the embedded node that happens to have a display. styrene-tui targets both via mousefood backend; feature flags differentiate the UI surface.

## Open Questions

*No open questions.*
