---
id: styrene-rs-serial-kiss
title: "Serial/KISS interface — edge hardware transport"
status: decided
parent: styrene-rs-architecture
dependencies: [styrene-rs-s3-bytestream-trait]
open_questions: []
branches: ["feature/styrene-rs-serial-kiss"]
openspec_change: styrene-rs-serial-kiss
---

# Serial/KISS interface — edge hardware transport

## Overview

The stated reason for the Rust port is constrained edge devices (RNode, RP2040, ESP32). Without serial transport, the binary only runs over TCP/UDP. Add serial.rs to styrene-rns transport/iface/ using tokio-serial. HDLC framing is already implemented (reusable). KISS framing is a separate encoder (FEND/FESC byte stuffing, ~150 LOC). Depends on S3 (ByteStream trait) to avoid duplicating the HDLC pipeline. Also relevant for BLE/RNode Tier 2 mobile support.

## Decisions

### Decision: RNodeInterface as KISS superset with FrameCodec trait

**Status:** decided
**Rationale:** KissCodec and HdlcCodec as parallel implementations. RNode is KISS superset, not separate abstraction. BLE variant lives in Dioxus app crate.

## Open Questions

*No open questions.*
