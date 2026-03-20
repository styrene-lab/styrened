# Styrene Mobile — Background Execution Architecture — Design Tasks

## 1. Open Questions

- [ ] 1.1 For iOS Network Extension (Tier 3): how does the Dioxus main app UI communicate with the PacketTunnelProvider extension process? NETunnelProviderSession IPC has strict message size limits. Does styrened-rs need a dedicated IPC protocol for this, or can it reuse the Unix socket / broadcast channel architecture?
- [ ] 1.2 Hub push gateway: self-hosted operators must supply their own APNs .p8 key + team ID + bundle ID. This means the mobile app bundle ID is fixed (or operators build their own IPA). What's the distribution model — App Store with Styrene's APNs credentials, or TestFlight/AltStore/sideload for self-hosted deployments?
