# TUI Comms Workspace Model — Tasks

## 1. LXMF Group Discussion Model

- [x] 1.1 Implement: Group threads should be first-class conversation scopes separate from direct identity threads and forum/topic threads
- [x] 1.2 Implement: Cryptographic isolation should be per group thread with membership epochs
- [x] 1.3 Implement: Hub-assisted group key exchange is acceptable if the hub is not the long-term plaintext trust anchor
- [x] 1.4 Implement: Use a Signal-style sender-key group model as the initial design reference, adapted to LXMF's asynchronous delivery model
- [x] 1.5 Implement: Initial private group-thread lifecycle should use pairwise-encrypted control messages and room-scoped epoch keys
- [x] 1.6 Implement: Direct, Group, and Forum should be distinct conversation scope kinds in both UX and state models
- [x] 1.7 Implement: Group invitations should be identity-targeted and transport-unified, with delivery choosing the highest authoritative route available at send time
- [x] 1.8 Implement: Room UX should expose capability-aware media friction and ask before expensive transfers on constrained paths such as LoRa
- [x] 1.9 Implement: Group rooms remain room-centric across transports, with participants shown at their highest authoritative interface at the moment
- [x] 1.10 Implement: Group-thread storage and richer features should be tiered, with hardware-informed first-run defaults and explicit operator override
