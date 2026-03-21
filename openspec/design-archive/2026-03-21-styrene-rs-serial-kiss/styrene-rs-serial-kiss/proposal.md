# Serial/KISS interface — edge hardware transport

## Intent

The stated reason for the Rust port is constrained edge devices (RNode, RP2040, ESP32). Without serial transport, the binary only runs over TCP/UDP. Add serial.rs to styrene-rns transport/iface/ using tokio-serial. HDLC framing is already implemented (reusable). KISS framing is a separate encoder (FEND/FESC byte stuffing, ~150 LOC). Depends on S3 (ByteStream trait) to avoid duplicating the HDLC pipeline. Also relevant for BLE/RNode Tier 2 mobile support.

## Dependencies

- S3: ByteStream trait — dedup interface layer (implemented)
