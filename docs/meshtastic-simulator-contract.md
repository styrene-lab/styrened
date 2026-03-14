---
id: meshtastic-simulator-contract
title: Meshtastic Simulator Canary Contract
status: exploring
parent: meshtastic-canary-shape
tags: [meshtastic, canary, simulator, ci, contract]
open_questions: []
---

# Meshtastic Simulator Canary Contract

## Overview

Define the exact proof surface for the simulator-backed Meshtastic canary used in routine CI: what inputs it must emulate, what bridge behaviors styrened must observe, and how results must be labeled so operators do not confuse simulated success with real radio-path success.

## Research

### Simulator canary should prove bridge semantics, not firmware fidelity

The simulator-backed canary should be intentionally narrow. Its job is not to prove that Meshtastic firmware, RF propagation, or hardware serial behavior exactly match reality. Its job is to prove that styrened's Meshtastic bridge can boot, subscribe to a local Meshtastic-like surface, ingest a neighbor/node snapshot, observe inbound text, and exercise the outbound plaintext relay path against a deterministic counterpart. This makes it a contract test for the bridge boundary, not a substitute for hardware validation.

## Open Questions

*No open questions.*
