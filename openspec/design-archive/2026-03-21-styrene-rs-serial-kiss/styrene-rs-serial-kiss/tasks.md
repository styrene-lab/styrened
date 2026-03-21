# Serial/KISS interface — edge hardware transport — Tasks

## 1. RNode Interface Layer — KISS codec, radio config, BLE, telemetry

- [x] 1.1 Implement: Introduce FrameCodec trait — KissCodec and HdlcCodec as parallel implementations
- [x] 1.2 Implement: RNodeInterface is a superset of KissInterface — not a separate abstraction
- [x] 1.3 Implement: BLE RNodeInterface lives in the Dioxus app crate — not in styrene-rns
- [x] 1.4 Implement: Add optional signal quality to RxMessage — RNodeInterface populates, others leave None
- [x] 1.5 Implement: Support both explicit config and auto-detection — explicit config is primary, auto-detect is opt-in
