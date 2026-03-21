---
id: meshtastic-bridge
title: Meshtastic Bridge Service
status: decided
parent: cop-activity-summary
related: [meshtastic-canary-shape]
tags: [transport, meshtastic, bridge, lora]
open_questions: []
branches: ["feature/meshtastic-bridge"]
openspec_change: meshtastic-bridge
---

# Meshtastic Bridge Service

## Overview

Optional bolt-on service bridging styrened to the Meshtastic mesh via local radio (serial/BLE). Translates LXMF ↔ Meshtastic messages. Meshtastic devices appear in COP as DeviceType.MESHTASTIC with transport tag [Mesh]. User-toggleable in Settings like I2P/Yggdrasil adapters.

## Decisions

### Decision: Radio-only, no MQTT — local serial/BLE interface to Meshtastic hardware

**Status:** decided
**Rationale:** MQTT undermines styrened's security model: public default broker, no auth, no forward secrecy, internet-wide metadata exposure. Radio-only bounds the attack surface to physical proximity — consistent with styrened's threat model. Internet reach is already served by TCP/I2P/Yggdrasil with better security properties. Users who want MQTT can enable it on their Meshtastic node independently; styrened bridges to the radio side only.

### Decision: Explicit bolt-on with hard boundary — no protocol convergence, no deep integration

**Status:** decided
**Rationale:** Meshtastic is a fundamentally different protocol with different security properties (PSK-only, no identity auth, no forward secrecy, 228-byte payloads). Deep integration would mean weakening styrened's security model to accommodate Meshtastic's constraints. Instead: read-only visibility of the Meshtastic mesh (node list, SNR, hop count, channel activity) with optional one-way text bridging. Meshtastic nodes are UNTRUSTED by definition — they never get RBAC roles, never participate in PQC sessions, never receive RPC commands. The bridge is a window, not a door. This is philosophically intentional: styrened builds its own mesh with its own security guarantees. Meshtastic is a neighbor we can see and wave at, not a peer we trust.

### Decision: Daemon service with optional meshtastic dependency, same toggle pattern as I2P/Yggdrasil

**Status:** decided
**Rationale:** Runs as a daemon service (not sidecar) — same lifecycle as I2P/Yggdrasil adapters: Settings toggle, BinaryProvisioner not needed (pure Python meshtastic package), enabled via core-config.yaml meshtastic.enabled. The meshtastic Python package is an optional dependency (pip install styrened[meshtastic]). Service connects to a local Meshtastic node via serial/BLE, subscribes to mesh traffic, and exposes read-only node/message data to the TUI. Bolt-on means bolt-off: disabling the toggle fully removes the service from the event loop.

### Decision: No LXMF-to-Meshtastic translation — read-only ingest plus optional plaintext relay out

**Status:** decided
**Rationale:** Trying to map LXMF fields into 228-byte Meshtastic payloads is a losing game that would produce a leaky abstraction. Instead: (1) INBOUND — Meshtastic text messages appear in a dedicated 'Meshtastic' tab or COP feed line, attributed to Meshtastic node ID, clearly labeled as untrusted/unverified. No attempt to create synthetic LXMF envelopes. (2) OUTBOUND — optional operator-initiated plaintext relay: user can choose to broadcast a short text to a Meshtastic channel, explicitly acknowledging it leaves the Styrene security boundary. No automatic forwarding of LXMF messages to Meshtastic. The bridge never pretends Meshtastic messages are LXMF messages.

### Decision: Meshtastic nodes are permanently UNTRUSTED — no RBAC roles, no PQC, no RPC, no identity binding

**Status:** decided
**Rationale:** Meshtastic has no cryptographic identity model compatible with RNS/LXMF. PSK channels provide confidentiality (if non-default key) but zero authentication — any node with the key is indistinguishable. Styrened's security model (Ed25519 identity → RBAC role → PQC session → capability-gated RPC) cannot extend to Meshtastic without becoming meaningless. Therefore: Meshtastic nodes exist in a permanent UNTRUSTED tier below STRANGER. They appear in the COP with a distinct visual treatment (dimmed, different icon, [Mesh] tag) making the trust boundary immediately obvious. No RBAC promotion possible. No PQC handshake attempted. No RPC commands accepted from or sent to Meshtastic nodes.

### Decision: Single [Mesh] transport label for all non-RNS LoRa mesh protocols

**Status:** decided
**Rationale:** Meshtastic, MeshCore, and future LoRa mesh protocols all present the same to the operator: nearby radio nodes with no RNS identity. Separate COP labels ([Mshtc], [MCore]) would be noise — the operator cares about 'LoRa nodes are visible' not which firmware they run. One [Mesh] tag, separate adapter classes internally (different serial protocols), shared UNTRUSTED presentation. The adapter class name (MeshtasticBridge, MeshCoreBridge) distinguishes them in config/logs, but the COP doesn't need to.

## Open Questions

*No open questions.*
