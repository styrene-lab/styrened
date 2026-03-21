# Cross-Enclave Features for Hub-Only Peers — Tasks

## 1. Independent Cross-Enclave Features (Clipboard, Discovery, Jobs)

- [x] 1.1 Implement: Dual-path design: LXMF always, DirectLink when available, RBAC per-feature

## 2. TURN-Style Link Relay via Hub

- [x] 2.1 Implement: Link lifecycle: disconnect propagation with permanent-link exception
- [x] 2.2 Implement: Relay data path: channel-based multiplexed forwarding
- [x] 2.3 Implement: Hybrid data path: Channel for control, request forwarding for data
- [x] 2.4 Implement: Relay coordination uses hub-mediated request/accept plus RelayService RBAC enforcement
