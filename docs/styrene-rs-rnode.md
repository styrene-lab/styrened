---
id: styrene-rs-rnode
title: RNode Interface Layer — KISS codec, radio config, BLE, telemetry
status: resolved
parent: styrene-rs-serial-kiss
tags: [rnode, lora, kiss, serial, ble, telemetry, edge, radio]
open_questions: []
---

# RNode Interface Layer — KISS codec, radio config, BLE, telemetry

## Overview

RNode is not just a serial device — it has a layered protocol above KISS with radio configuration and telemetry commands. Python RNS has three distinct interface types: KISSInterface (generic AX.25 TNC, FEND/FESC only), RNodeInterface (extends KISS with CMD_FREQUENCY/BANDWIDTH/SF/CR/TXPOWER + CMD_STAT_RSSI/SNR/BAT/TEMP/CHTM + CMD_BT_CTRL for BLE), and RNodeMultiInterface (multi-channel). The serial.rs stub we created needs to grow into this full hierarchy. RNode is also the primary hardware for mobile Tier 2 (BLE-connected RNode gives a phone LoRa connectivity via Core Bluetooth).

## Research

### Three-layer protocol hierarchy: KISS → RNode commands → multi-interface

Python RNS exposes three separate interface classes, each a superset of the previous:

**Layer 1 — KISS framing (KISSInterface)**
Pure FEND/FESC byte stuffing. Constants:
- FEND=0xC0, FESC=0xDB, TFEND=0xDC, TFESC=0xDD
- CMD_DATA=0x00 (the only command used for data frames)
- CMD_RETURN=0xFF (exit KISS mode)
Escape rule: replace 0xDB→0xDB 0xDD, 0xC0→0xDB 0xDC. Frame: FEND + CMD + escaped_data + FEND.
Used for: generic AX.25 TNCs and KISS-capable hardware that is NOT RNode.

**Layer 2 — RNode command protocol (RNodeInterface)**
Extends KISS with a full radio control and telemetry API:

Radio config (sent TO RNode):
- CMD_FREQUENCY=0x01 — set carrier frequency (4 bytes, Hz)
- CMD_BANDWIDTH=0x02 — LoRa bandwidth (2 bytes)
- CMD_TXPOWER=0x03 — transmit power (1 byte, dBm)
- CMD_SF=0x04 — spreading factor (1 byte, 7-12)
- CMD_CR=0x05 — coding rate (1 byte, 5-8)
- CMD_RADIO_STATE=0x06 — enable/disable radio
- CMD_RADIO_LOCK=0x07 — lock/unlock config changes
- CMD_DETECT=0x08 — detect RNode presence
- CMD_LEAVE=0x0A — request RNode to relinquish control

Telemetry (received FROM RNode):
- CMD_STAT_RX=0x21 — packets received count
- CMD_STAT_TX=0x22 — packets transmitted count
- CMD_STAT_RSSI=0x23 — RSSI of last received packet (1 byte, value - 292 = dBm)
- CMD_STAT_SNR=0x24 — SNR of last received packet (1 byte, signed, / 4 = dB)
- CMD_STAT_CHTM=0x25 — channel utilization metrics
- CMD_STAT_PHYPRM=0x26 — current PHY parameters echo
- CMD_STAT_BAT=0x27 — battery percentage (on portable RNode variants)
- CMD_STAT_CSMA=0x28 — CSMA statistics
- CMD_STAT_TEMP=0x29 — MCU temperature (on some variants)

Device control:
- CMD_BLINK=0x30 — LED blink (for visual identification)
- CMD_BT_CTRL=0x46 — Bluetooth control (BLE on/off, pairing)
- CMD_PLATFORM=0x48 — query platform (PLATFORM_AVR=0x90, PLATFORM_ESP32=0x80, PLATFORM_NRF52=0x70)
- CMD_MCU=0x49 — query MCU type
- CMD_FW_VERSION=0x50 — firmware version
- CMD_RESET=0x55 — reset device

**Layer 3 — Multi-channel (RNodeMultiInterface)**
1149 LOC. Handles hardware with multiple simultaneous LoRa radios (e.g. dual-band nodes). Multiple virtual interfaces over a single physical connection. Each "sub-interface" has its own frequency/SF/BW config and appears as a separate RNS interface.

### Where RNode touches every layer of the Styrene stack

**Transport layer (styrene-rns)**
RNode IS the LoRa transport for field deployments. Without it, styrened-rs is TCP/UDP only — useful but not unique to the mesh communication mission. The serial.rs stub we created is the foundation; KISS codec and RNode command layer are what make it real.

**Content distribution (styrene-content)**
The 4KB LoRa chunk profile was specifically calibrated for RNode's 235-byte MTU at SF10. RNode provides the radio channel through which firmware updates reach remote edge nodes. RNode's RSSI/SNR telemetry (CMD_STAT_RSSI, CMD_STAT_SNR) feeds the link quality assessment that could drive adaptive chunk sizing.

**Mobile Tier 2 (styrene-mobile-background-arch)**
BLE-connected RNode is explicitly listed as the Tier 2 mobile path. RNode firmware (ESP32/nRF52 variants) supports BLE GATT transport for sending/receiving KISS frames wirelessly. On iOS, Core Bluetooth background mode maintains a BLE connection to a nearby RNode — giving the phone LoRa connectivity in background without any special Apple entitlement. This is simpler than Tier 3 (Network Extension) and provides physical radio connectivity.

**Fleet telemetry**
CMD_STAT_BAT (battery %) and CMD_STAT_TEMP are critical for remote node health monitoring. An edge node reporting low battery or thermal throttling can trigger a fleet alert. The AnnounceRecord already has rssi and snr fields — RNode feeds these directly.

**Duty cycle and the LoRa regulatory constraint**
European LoRa operates at 868MHz with 1% duty cycle. RNode firmware enforces this. Our content distribution timing and speedtest code already accounts for LoRa-hardened timeouts. The CSMA stats (CMD_STAT_CSMA, CMD_ST_ALOCK, CMD_LT_ALOCK) are how nodes detect channel congestion and coordinate transmissions.

**styrene-edge / forge provisioner**
RNode firmware is reflashed via the forge provisioner. An edge node's "provision" flow includes detecting an attached RNode, checking its firmware version (CMD_FW_VERSION), and flashing if needed. This is already partially designed in the provision screen work.

**RSSI/SNR already in the data model**
AnnounceRecord already has rssi: Option&lt;f64&gt; and snr: Option&lt;f64&gt; fields (from Python daemon). These map directly to CMD_STAT_RSSI and CMD_STAT_SNR on inbound LoRa packets from RNode. The Rust side just needs to populate these during inbound packet processing in the RNodeInterface handler.

### Implementation decomposition — what needs to be built

**1. KissCodec (in styrene-rns/src/transport/iface/)**
The FEND/FESC byte stuffing encoder/decoder. Parallel to `Hdlc`. Plugs into `run_hdlc_rx_loop` / `run_hdlc_tx_loop` — actually, these loops are generic over `AsyncRead`/`AsyncWrite` with HDLC codec baked in. The right abstraction is a `FrameCodec` trait (noted as TODO in serial.rs) that both `HdlcCodec` and `KissCodec` implement. The RX/TX loops become generic over `FrameCodec`.
~150 LOC.

**2. RNodeInterface (in styrene-rns/src/transport/iface/rnode.rs)**
Wraps KissCodec serial transport with:
- Initialization handshake (CMD_DETECT, CMD_PLATFORM, CMD_FW_VERSION)
- Radio configuration (CMD_FREQUENCY, CMD_BANDWIDTH, CMD_SF, CMD_CR, CMD_TXPOWER, CMD_RADIO_STATE)
- Inbound RSSI/SNR extraction (every received KISS frame from RNode includes signal quality metadata)
- Telemetry subscription (CMD_STAT_BAT, CMD_STAT_TEMP, CMD_STAT_CHTM on a periodic timer)
- BLE control (CMD_BT_CTRL) for enabling/disabling BLE pairing
~400-600 LOC.

**3. RNodeConfig (in daemon config layer)**
Per-interface config for RNode:
```
frequency: u32      # Hz, e.g. 868100000
bandwidth: u32      # Hz, e.g. 125000
spreading_factor: u8  # 7-12
coding_rate: u8     # 5-8
tx_power: u8        # dBm
```
These map to CMD_FREQUENCY etc during initialization.

**4. RNodeBleInterface (mobile Tier 2, in Dioxus app)**
BLE GATT transport for RNode. Sends KISS frames over BLE characteristics instead of serial. Uses iOS Core Bluetooth / Android BLE APIs via Dioxus. Distinct from the USB serial path but same KISS codec and RNode command protocol.
Lives in the Dioxus app crate, not in styrene-rns (no tokio-serial needed).

**5. RNodeMultiInterface (deferred)**
Multi-channel support. Lower priority than single-channel RNode. Needed for dual-band hardware.

**Build order within RNode work:**
1. `KissCodec` + `FrameCodec` trait refactor of stream loops
2. `RNodeInterface` (USB serial path)
3. `RNodeConfig` in daemon config
4. `RNodeBleInterface` (deferred to when Dioxus mobile app begins)
5. `RNodeMultiInterface` (deferred)

## Decisions

### Decision: Introduce FrameCodec trait — KissCodec and HdlcCodec as parallel implementations

**Status:** decided
**Rationale:** The stream_iface loops (run_hdlc_rx_loop, run_hdlc_tx_loop) have HDLC baked in. Adding KISS requires either duplicating the loops (anti-pattern, already avoided by S3) or abstracting the codec. A FrameCodec trait — encode(data) → bytes, find(buf) → Option&lt;(start,end)&gt;, decode(frame, output) — allows both HdlcCodec and KissCodec to plug into the same generic loops. This was noted as a TODO in serial.rs. RNode makes it concrete and necessary.

### Decision: RNodeInterface is a superset of KissInterface — not a separate abstraction

**Status:** decided
**Rationale:** The RNode protocol is KISS data framing + additional command frames on the same serial connection. RNodeInterface initializes the radio config on connection, then operates like a KissInterface for data frames, AND dispatches inbound command frames (RSSI, SNR, battery) to telemetry handlers. This is a has-a relationship (RNodeInterface contains a KissCodec), not an is-a relationship requiring inheritance. The distinction from generic KISS: RNode frames always include a signal quality byte appended to inbound data frames (RSSI after the KISS CMD_DATA payload).

### Decision: BLE RNodeInterface lives in the Dioxus app crate — not in styrene-rns

**Status:** decided
**Rationale:** BLE transport for RNode uses platform BLE APIs (iOS Core Bluetooth, Android BLE) which are not available in a cross-platform no_std Rust library. The KISS codec and RNode command protocol live in styrene-rns (reusable), but the BLE I/O adapter lives in the Dioxus app crate where platform APIs are accessible. The interface boundary: Dioxus app provides a BLE stream (a type implementing AsyncRead + AsyncWrite over BLE GATT), and the styrene-rns KissCodec + RNodeCommandHandler runs on top of it — same code path, different transport.

### Decision: Add optional signal quality to RxMessage — RNodeInterface populates, others leave None

**Status:** decided
**Rationale:** RxMessage currently has { address: AddressHash, packet: Packet } — no signal quality. AnnounceRecord has rssi/snr fields in storage but nothing populates them today. The fix: add `rssi: Option&lt;f32&gt;` and `snr: Option&lt;f32&gt;` to RxMessage. RNodeInterface extracts these from the trailing byte of each inbound KISS data frame (Python RNodeInterface does this — RSSI is byte value minus 292 to get dBm, SNR is signed byte divided by 4 to get dB). UDP/TCP interfaces set both to None. Downstream, the announce handler copies rssi/snr from RxMessage into AnnounceRecord before persisting. This is a minimal, non-breaking change — RxMessage gains two optional fields, all existing code paths just see None until RNode is active. f32 not f64 — signal quality at 0.1dB precision is more than sufficient and keeps RxMessage smaller.

### Decision: Support both explicit config and auto-detection — explicit config is primary, auto-detect is opt-in

**Status:** decided
**Rationale:** Edge nodes (RP2040, Pi Zero) have deterministic hardware — they know exactly which UART the RNode is on (/dev/ttyUSB0 or a specific hardware UART). Auto-detection adds startup latency (scanning ports, sending CMD_DETECT, waiting for responses) that is unnecessary and potentially problematic on embedded (touching random serial ports can confuse other peripherals). However, desktop/laptop users plugging in a USB RNode benefit from auto-detect — they shouldn't have to find the port name.

Decision: config file specifies `port: /dev/ttyUSB0` (explicit) or `port: auto` (scan). Default is explicit — auto must be opted into. Auto-detect scans platform serial ports (serialport crate enumerate), sends CMD_DETECT to each, waits up to 2s for response. On Linux, filter to /dev/ttyUSB* and /dev/ttyACM* to avoid touching GPS receivers, modems, etc. On macOS, /dev/cu.usbmodem* and /dev/cu.usbserial*. On embedded (no_std), auto-detect is not compiled — always explicit UART config.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- KissCodec must be no_std compatible — needed for RP2040 embedded builds where RNode attaches via UART
- FrameCodec trait refactor changes the signature of run_hdlc_rx_loop and run_hdlc_tx_loop — breaking change to stream_iface.rs API (acceptable, no external consumers yet)
- RNode command protocol runs on a SEPARATE logical channel from KISS data frames — command responses arrive as KISS frames with non-DATA command bytes (0x01, 0x02, etc.) that must be dispatched to the command handler, not the packet deserializer
- EU 868MHz duty cycle (1% / 10 mW default) must be respected — RNode firmware enforces this but styrened-rs should not flood the channel with content distribution chunks faster than the duty cycle allows
- tokio-serial must be added to styrene-rns Cargo.toml under the serial feature flag
