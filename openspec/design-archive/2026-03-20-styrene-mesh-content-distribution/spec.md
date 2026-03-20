# Styrene Mesh Content Distribution — P2P file sharing over RNS/Yggdrasil — Design Spec (extracted)

> Auto-extracted from docs/styrene-mesh-content-distribution.md at decide-time.

## Decisions

### Blake3 for content and chunk hashing — faster than SHA-256 on ARM, tree-native (decided)

Blake3 is faster than SHA-256 and MD5 on ARM (relevant for RP2040/ESP32), produces 32-byte digests, and has a native tree hashing mode that naturally supports chunked content verification. The Blake3 tree hash of the full content equals the content_id regardless of chunking strategy, providing a consistent identifier across different chunk size configurations. The blake3 crate is no_std compatible. RNS already uses Blake2b internally — Blake3 is a successor with better performance characteristics.

### Fleet firmware update is the primary driver — Phase 1 scoped to single-seeder content-addressed transfer (decided)

The fleet firmware update use case is immediately valuable, clearly scoped, and doesn't require multi-peer swarming to be useful. Phase 1 delivers: StyreneManifest format, RESOURCE_AVAILABLE announce, single-seeder chunk fetch with per-chunk verification. This is essentially "content-addressed LXMF large file transfer" and is a superset of what's needed for firmware distribution. Multi-seeder swarming (Phase 2) is an optimization that becomes important at fleet scale (20+ nodes) but isn't needed to prove the protocol.

### Chunk size is a publisher-selected profile in the manifest — not negotiated per-transfer (decided)

RNS Resources handles transport fragmentation internally — a 256KB chunk will be fragmented into ~1100 LoRa packets by the RNS layer. The content-layer chunk size is independent of the RNS MTU. The decisive constraint is RAM on RP2040 (264KB total SRAM): a 256KB chunk cannot be buffered for Blake3 verification on constrained devices. Three profiles defined in the manifest spec: mesh-wifi (256KB, hub nodes and ESP32 with PSRAM), mesh-lora (4KB, RP2040 and strict LoRa paths), mesh-balanced (32KB, mixed topologies and most ESP32). Publisher selects at publish time based on the target network and device class. Nodes that cannot buffer the specified chunk size cannot participate as leeches — a documented limitation not a bug.

### ChunkStore is an abstract trait — persistence determined by content type and node capability, not network type (decided)

Firmware content: download → verify → apply → discard. Chunks are ephemeral; RamChunkStore is sufficient and avoids flash wear. Data content (maps, reference material, emergency packs): should persist across reboots to enable re-seeding. FlashChunkStore (NVS on ESP32, SD card, or filesystem on full nodes) with configurable TTL. Hub nodes always persist. The ChunkStore trait (store_chunk, get_chunk, has_chunk, evict) abstracts the backing store; implementations are selected at daemon startup based on content_type in the manifest and node configuration. This also cleanly separates the protocol logic from storage concerns for testability.

### Lives in `styrene-content` Rust crate, exposed to Python hub via `styrene-native` PyO3 bindings (decided)

Fleet firmware updates must work on both Python hub (styrened) and Rust edge nodes (styrened-rs). Implementing in Rust as a new `styrene-content` crate and exposing via the existing `styrene-native` PyO3 bindings path (already scaffolded) gives both: the Python hub imports StyreneManifest and ContentDistributor from styrene_native; the Rust daemon uses the crate directly. No parallel Python implementation needed — this is a new feature with no Python code to migrate from. Consistent with the incremental PyO3 migration strategy already decided. The manifest format and wire types (0xE0 RESOURCE_AVAILABLE) belong in `styrene-mesh`; the distribution protocol logic belongs in `styrene-content`.

## Research Summary

### What RNS Resources already provides and what's missing

**RNS Resources (existing):**
- Chunked file transfer over an established RNS Link
- Per-chunk hash verification (Blake2b)
- Retransmission with exponential backoff
- Proof-of-work stamp for anti-spam
- Request/response model: one requester, one provider
- Max practical size: limited by link stability and memory on constrained devices

**What's missing for mesh content distribution:**
1. Content-addressed discovery: no way to ask "who has file X" without knowing a specific node to ask
2. Multi-p…

### Protocol sketch — StyreneManifest and chunk swarming

**Content ID:** Blake3(full_content) truncated to 32 bytes. Canonical, collision-resistant, fast on constrained devices (Blake3 is faster than SHA-256 on ARM).

**Manifest format (CBOR, signed by creator's Styrene identity):**
```
{
  content_id:    bytes[32],    // Blake3 of full content
  size:          uint,
  chunk_size:    uint,         // default: 256KB (tunable per network type)
  chunk_count:   uint,
  chunk_hashes:  [bytes[32]],  // Blake3 per chunk
  metadata: {
    name:        text,
…

### Use case prioritization and phasing

**Priority use cases (in order):**

1. **Fleet firmware updates** — the clear driver. Operators need to push styrened-rs binaries to 20-100 edge nodes. Sequential delivery doesn't scale. Swarming solves this.

2. **NomadNet page mirroring** — operators can publish Styrene pages as content-addressed archives. Other nodes can replicate and serve them. Improves resilience and availability of mesh-hosted content.

3. **Emergency data packs** — pre-packaged reference data (maps, frequencies, procedur…
