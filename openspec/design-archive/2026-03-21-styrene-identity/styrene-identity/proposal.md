# Styrene Identity System

## Intent

A unified root identity for Styrene that sits above all protocol-specific identities. The StyreneID is the single source of truth: it can be hardware-backed (YubiKey first-class), and all protocol-specific keys (RNS, LXMF, Yggdrasil, WireGuard, I2P, BATMAN, …) are derived from or cross-signed by it. This eliminates the hash confusion problem discovered in the TUI audit (multiple disconnected peer_hash spaces) and creates a stable, portable, extensible identity primitive that can grow to include new protocols without retroactive breakage.
