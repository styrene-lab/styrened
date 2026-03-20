---
id: styrene-mesh-content-distribution
title: "Styrene Mesh Content Distribution — P2P file sharing over RNS/Yggdrasil"
status: implementing
tags: [content, p2p, torrent, rns, resources, yggdrasil, fleet]
open_questions: []
branches: ["feature/styrene-mesh-content-distribution"]
openspec_change: styrene-mesh-content-distribution
---

# Styrene Mesh Content Distribution — P2P file sharing over RNS/Yggdrasil

## Overview

BitTorrent-inspired content distribution over the Styrene mesh. Builds on RNS Resources (chunked file transfer) and Styrene identity (authenticated content). A signed chunk manifest (StyreneResourceDescriptor) replaces .torrent files; multi-peer swarming requests different chunks from different peers; discovery via LXMF RESOURCE_AVAILABLE announces or NomadNet pages. Over Yggdrasil overlay: fully encrypted, authenticated participants, no cleartext metadata. Primary use cases: fleet firmware updates, emergency data packs, NomadNet page mirroring, encrypted document distribution. Reference: nyaa (provider/source trait pattern for TUI layer).

## Research

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
2. Multi-peer swarming: can only fetch from one peer per resource session
3. Persistent availability: a node must be online and hold the complete file to serve it
4. Manifest distribution: no standardized way to announce "I have file X, here's how to get it"

**The minimal additions needed:**
- `StyreneManifest`: a CBOR document containing `{content_id: Blake3, size: u64, chunk_size: u32, chunk_hashes: [Blake3], metadata: {name, description, created_at, creator_identity}, signature: Ed25519}`
- `RESOURCE_AVAILABLE` announce: a lightweight LXMF message or RNS announce carrying a manifest fingerprint and the announcing node's address
- Multi-source fetch: request different chunks from different peers who have announced availability
- Local chunk store: nodes persist completed chunks and re-announce availability

**The swarming property emerges naturally:**
- Node A publishes firmware v2.1 manifest to the mesh
- Node B downloads from A → now B also announces availability
- Nodes C, D, E can now swarm from both A and B
- Fleet of 50 nodes can fully distribute a 10MB update via 6-7 "hops" of parallel swarming
- No central tracker — discovery is pure mesh broadcast

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
    description: text,
    content_type: text,        // "firmware/styrened-rs", "data/emergency", etc.
    created_at:  uint,         // Unix timestamp
    version:     text,         // optional semver for firmware
  },
  creator:       bytes[32],    // Styrene identity hash
  signature:     bytes[64],    // Ed25519 signature over canonical CBOR above
}
```

Manifest size: ~100 bytes + 32 bytes per chunk. 10MB file at 256KB chunks = 40 chunks → ~1.4KB manifest. Fits in a single LXMF message.

**Announce protocol (RESOURCE_AVAILABLE):**
LXMF message type `0xE0` (new protocol type in styrene-mesh wire):
```
{
  content_id:   bytes[32],
  manifest_hash: bytes[16],   // Blake3[:16] of the manifest itself
  chunks_held:  bitset,       // which chunks this node currently has
  seeder_hash:  bytes[16],    // RNS identity_hash of announcing node
}
```
Broadcast to mesh on:
- Completing a full download (become a seeder)  
- Completing each chunk (partial seeding during download)
- Periodic re-announce every N minutes while holding chunks

**Chunk request:**
Direct LXMF request to a specific seeder: `{content_id, chunk_index}` → seeder responds with raw chunk bytes. Verification: Blake3(chunk) == chunk_hashes[i] from manifest.

**Discovery flow:**
1. Operator publishes manifest via LXMF or NomadNet page → manifest fingerprint travels in subsequent announce
2. Interested nodes hear the RESOURCE_AVAILABLE announce → fetch manifest from announcer
3. Verify manifest signature (trusted creator or web of trust)
4. Request chunks from multiple seeders simultaneously

**Fleet firmware update flow:**
1. Hub operator signs firmware manifest with operator Styrene identity
2. Broadcasts RESOURCE_AVAILABLE to fleet mesh
3. Fleet nodes fetch manifest → verify creator signature (matches hub operator identity in RBAC roster)
4. Nodes begin downloading chunks directly from hub + from each other as they complete chunks
5. On completion: verify Blake3(assembled) == manifest.content_id → apply update

**Security properties:**
- Content authenticity: Ed25519 signature on manifest by known creator identity
- Content integrity: Blake3 per-chunk verification
- Transport privacy: Yggdrasil E2E encryption for all chunk transfers
- No central tracker: pure mesh broadcast discovery
- Sybil resistance: manifest must be signed by a known identity in the web of trust
- Denial: nodes can refuse to serve chunks (rate limiting, identity-based policy)

### Use case prioritization and phasing

**Priority use cases (in order):**

1. **Fleet firmware updates** — the clear driver. Operators need to push styrened-rs binaries to 20-100 edge nodes. Sequential delivery doesn't scale. Swarming solves this.

2. **NomadNet page mirroring** — operators can publish Styrene pages as content-addressed archives. Other nodes can replicate and serve them. Improves resilience and availability of mesh-hosted content.

3. **Emergency data packs** — pre-packaged reference data (maps, frequencies, procedures) distributed to the mesh before events. Content-addressed, signed by authority identity.

4. **Encrypted document distribution** — operator-to-fleet document distribution. The manifest carries the content_id; the actual content is encrypted to the recipient's public key before chunking.

5. **General P2P file sharing** — the "torrent" use case. Lower priority than the above; depends on having a functional TUI browser surface (nyaa-style browsing of available content on the mesh).

**Phasing:**

Phase 1 (MVP): Manifest format + RESOURCE_AVAILABLE announce + single-seeder chunk fetch. Effectively "content-addressed LXMF large file transfer with verification." No swarming yet. Unlocks fleet firmware updates.

Phase 2: Multi-seeder swarming (bitset announces, parallel chunk requests). Unlocks the CDN-like fleet distribution scaling.

Phase 3: TUI browser surface (list available content, filter by type/creator, download, track progress). The nyaa architecture (source trait, search/browse/download workflow) is directly applicable here.

**Constrained device considerations:**
- RP2040 may not have enough RAM to buffer chunks during download (limited to smaller files or streaming applies)
- ESP32 with PSRAM (4MB) can handle 256KB chunks comfortably
- Hub nodes (full servers) act as persistent seeders with full chunk stores
- Edge nodes: download + forward but may not persist after reboot (configurable chunk store persistence)

### Async/sync boundary design — three-zone model

The four execution environments drive a three-zone architecture. Each zone has a compatibility profile:

```
Zone 0 — Pure types (no_std, no alloc, no async)
  StyreneManifest   — CBOR parse/serialize, signature verification
  ContentId         — Blake3 wrapper (blake3 is no_std compatible)
  ChunkProfile      — profiles enum (mesh-wifi/mesh-balanced/mesh-lora)
  ChunkBitset       — fixed-size [u8; 32] = 256 bits = 256 chunks max
  ManifestVerifier  — verify Ed25519 signature over manifest bytes

  Constraint: heapless for any collections (no Vec, no String)
  Works on: all four environments including RP2040 bare-metal

Zone 1 — Async traits (no_std, no alloc, AFIT)
  trait ChunkStore       — async read/write/has/evict (AFIT, no boxing)
  trait ContentTransport — async send/recv for announces + chunk exchange
  ContentDistributor<S: ChunkStore, T: ContentTransport>
                         — protocol state machine, generic over both traits

  Why AFIT not async_trait macro:
    - async_trait boxes the future → requires alloc → breaks no_alloc targets
    - AFIT is stable since Rust 1.75 (workspace is on 1.93)
    - AFIT future is a concrete opaque type → zero alloc overhead
    - Works with embassy executor on RP2040 and FreeRTOS tasks on ESP32
    - Works with tokio on full nodes

  Tradeoff: AFIT traits are NOT dyn-compatible.
    `Box<dyn ChunkStore>` does not compile.
    Solution: daemon code instantiates ContentDistributor with concrete types.
    `ContentDistributor<TokioFsChunkStore, LxmfTransport>` — no dyn needed
    at MVP. If heterogeneous store dispatch is ever needed, provide a
    manual DynChunkStore wrapper (rare case, defer until needed).

Zone 2 — Implementations (feature-gated, environment-specific)
  RamChunkStore         — feature = "alloc" — in-memory HashMap, ephemeral
  TokioFsChunkStore     — feature = "tokio" — tokio::fs backed, persistent
  FlashChunkStore       — feature = "embedded-storage" — embedded-storage
                          trait, works with ESP32 NVS and RP2040 flash
  EspFsChunkStore       — feature = "esp-idf" — uses esp-idf's VFS/SPIFFS

  Implementations live in impls/ submodules, each gated by feature.
  The traits themselves (Zone 1) have no feature requirements.
```

Feature flag structure:
```toml
[features]
default = []              # Zone 0 + Zone 1 only — no_std, no alloc
alloc = []                # enables RamChunkStore, dynamic collections
std = ["alloc"]           # enables std::io, filesystem access
tokio = ["std", "dep:tokio"]        # enables TokioFsChunkStore
embedded-storage = ["dep:embedded-storage"]  # enables FlashChunkStore
esp-idf = ["std", "dep:embedded-svc"]       # enables EspFsChunkStore
```

ChunkBitset design (Zone 0, no alloc):
- Fixed `[u8; 32]` = 256 bits = max 256 chunks
- 256 chunks × 4KB (lora) = 1MB max on RP2040
- 256 chunks × 256KB (wifi) = 64MB max on full nodes
- Both are reasonable limits for their respective targets
- If larger files needed: manifest can declare chunk_count > 256, but
  nodes report partial bitsets (first 256 chunks). Protocol handles this
  gracefully — nodes just won't announce chunks they can't track.

Zero-copy read interface (avoids alloc in hot path):
```rust
trait ChunkStore {
    type Error;
    // Caller provides buffer — no Vec allocation
    async fn read_chunk(
        &self,
        content_id: ContentId,
        index: u32,
        buf: &mut [u8],
    ) -> Result<usize, Self::Error>;
    
    async fn write_chunk(
        &mut self,
        content_id: ContentId,
        index: u32,
        data: &[u8],
    ) -> Result<(), Self::Error>;
    
    async fn has_chunk(&self, content_id: ContentId, index: u32) -> bool;
    async fn chunks_held(&self, content_id: ContentId) -> ChunkBitset;
    async fn evict(&mut self, content_id: ContentId) -> Result<(), Self::Error>;
}
```

### dyn-compatibility resolution — why ContentDistributor doesn't need it

The AFIT dyn-incompatibility (can't write `Box<dyn ChunkStore>`) is often raised as a showstopper. It isn't one here, for a specific reason.

The concern: the tokio daemon needs to store a ContentDistributor in a struct field. If the daemon wants to swap implementations at runtime (e.g., RamChunkStore during testing, TokioFsChunkStore in production), it needs dyn dispatch.

Why this doesn't apply to styrene-content:

1. **ContentDistributor is instantiated once at daemon startup** with a concrete type selected by configuration. The type doesn't change at runtime. `ContentDistributor<TokioFsChunkStore, LxmfTransport>` is fine.

2. **Testing** uses the same concrete-type approach with a different implementation: `ContentDistributor<RamChunkStore, MockTransport>`. The type changes at compile time, not runtime.

3. **The AppContext owns the distributor** (following the S5 design). AppContext is already generic over its service types in the design. A concrete type in AppContext is the norm.

The only scenario where dyn would be needed: if the daemon needs to dispatch to DIFFERENT distributors at runtime based on network type (one for LoRa, one for WiFi). This is an optimization concern, not a correctness concern. If it's ever needed, the solution is a manual vtable wrapper:

```rust
// Not needed at Phase 1 — here for reference
struct DynChunkStore(Box<dyn ErasedChunkStore>);
// ErasedChunkStore uses async_trait macro internally for boxing
```

Decision: defer dyn-compatibility entirely. Concrete types throughout Phase 1 and 2. Revisit only if the daemon needs heterogeneous distributor dispatch, which is unlikely given the single-node-role model.

Contrast with styrene-tunnel's TunnelBackend: that uses async_trait because the daemon legitimately needs to dispatch to EITHER StrongSwan OR WireGuard at runtime based on configuration — a genuine dynamic dispatch requirement. ChunkStore has no equivalent runtime ambiguity.

### ESP32 + esp-idf async pattern — FreeRTOS tasks, not tokio

Phone-OS on ESP32 uses:
- `esp-idf-svc` — provides std shim (std::thread, std::sync::Mutex, etc.)
- `crossbeam-channel` — for task communication
- `once_cell` — for lazy statics
- embassy-style async NOT used — esp-idf uses FreeRTOS under the hood

This means on ESP32:
- `async fn` with AFIT traits works because esp-idf provides an executor via embassy integration OR via blocking thread-per-task model
- tokio is NOT available (tokio requires epoll/kqueue which aren't in esp-idf)
- BUT: esp-idf-svc does have async support via `embassy-time-driver` feature (Phone-OS uses it)

The practical consequence for ChunkStore on ESP32:
- FlashChunkStore backed by NVS (Non-Volatile Storage) via esp-idf
- Async operations are driven by the embassy executor embedded in esp-idf-svc
- The same AFIT trait works — the future just gets polled by the esp-idf/embassy executor

The `esp-idf = ["std", "dep:embedded-svc"]` feature flag enables this path.
No special handling needed — AFIT + embassy executor on ESP32 is the same code path as AFIT + embassy on RP2040.

Key: Phone-OS already demonstrates this pattern works for WiFi (async AP scan, async connection) using the same executor. ChunkStore operations are simpler than WiFi — this is solved ground.

For RP2040 (no std):
- embassy-executor drives the futures
- FlashChunkStore uses embedded-storage trait (works with rp2040-hal flash)
- The only additional constraint: static futures (embassy requires 'static futures)
- ContentDistributor must be stored in a static or 'static-bounded scope
- This is a placement constraint, not a type constraint — the types are the same

## Decisions

### Decision: Blake3 for content and chunk hashing — faster than SHA-256 on ARM, tree-native

**Status:** decided
**Rationale:** Blake3 is faster than SHA-256 and MD5 on ARM (relevant for RP2040/ESP32), produces 32-byte digests, and has a native tree hashing mode that naturally supports chunked content verification. The Blake3 tree hash of the full content equals the content_id regardless of chunking strategy, providing a consistent identifier across different chunk size configurations. The blake3 crate is no_std compatible. RNS already uses Blake2b internally — Blake3 is a successor with better performance characteristics.

### Decision: Fleet firmware update is the primary driver — Phase 1 scoped to single-seeder content-addressed transfer

**Status:** decided
**Rationale:** The fleet firmware update use case is immediately valuable, clearly scoped, and doesn't require multi-peer swarming to be useful. Phase 1 delivers: StyreneManifest format, RESOURCE_AVAILABLE announce, single-seeder chunk fetch with per-chunk verification. This is essentially "content-addressed LXMF large file transfer" and is a superset of what's needed for firmware distribution. Multi-seeder swarming (Phase 2) is an optimization that becomes important at fleet scale (20+ nodes) but isn't needed to prove the protocol.

### Decision: Chunk size is a publisher-selected profile in the manifest — not negotiated per-transfer

**Status:** decided
**Rationale:** RNS Resources handles transport fragmentation internally — a 256KB chunk will be fragmented into ~1100 LoRa packets by the RNS layer. The content-layer chunk size is independent of the RNS MTU. The decisive constraint is RAM on RP2040 (264KB total SRAM): a 256KB chunk cannot be buffered for Blake3 verification on constrained devices. Three profiles defined in the manifest spec: mesh-wifi (256KB, hub nodes and ESP32 with PSRAM), mesh-lora (4KB, RP2040 and strict LoRa paths), mesh-balanced (32KB, mixed topologies and most ESP32). Publisher selects at publish time based on the target network and device class. Nodes that cannot buffer the specified chunk size cannot participate as leeches — a documented limitation not a bug.

### Decision: ChunkStore is an abstract trait — persistence determined by content type and node capability, not network type

**Status:** decided
**Rationale:** Firmware content: download → verify → apply → discard. Chunks are ephemeral; RamChunkStore is sufficient and avoids flash wear. Data content (maps, reference material, emergency packs): should persist across reboots to enable re-seeding. FlashChunkStore (NVS on ESP32, SD card, or filesystem on full nodes) with configurable TTL. Hub nodes always persist. The ChunkStore trait (store_chunk, get_chunk, has_chunk, evict) abstracts the backing store; implementations are selected at daemon startup based on content_type in the manifest and node configuration. This also cleanly separates the protocol logic from storage concerns for testability.

### Decision: Lives in `styrene-content` Rust crate, exposed to Python hub via `styrene-native` PyO3 bindings

**Status:** decided
**Rationale:** Fleet firmware updates must work on both Python hub (styrened) and Rust edge nodes (styrened-rs). Implementing in Rust as a new `styrene-content` crate and exposing via the existing `styrene-native` PyO3 bindings path (already scaffolded) gives both: the Python hub imports StyreneManifest and ContentDistributor from styrene_native; the Rust daemon uses the crate directly. No parallel Python implementation needed — this is a new feature with no Python code to migrate from. Consistent with the incremental PyO3 migration strategy already decided. The manifest format and wire types (0xE0 RESOURCE_AVAILABLE) belong in `styrene-mesh`; the distribution protocol logic belongs in `styrene-content`.

### Decision: Use AFIT (not async_trait macro) for ChunkStore and ContentTransport traits

**Status:** decided
**Rationale:** async_trait macro boxes futures (Box&lt;dyn Future&gt;) requiring alloc — this breaks RP2040 no_alloc targets and adds heap allocation overhead on ESP32. AFIT (async fn in trait, stable since Rust 1.75, workspace is on 1.93) generates concrete opaque future types with zero alloc overhead. Works with embassy (RP2040, ESP32), FreeRTOS tasks (esp-idf), and tokio (full nodes) — any executor that can drive a Future. Contrast with TunnelBackend in styrene-tunnel which correctly uses async_trait because it needs dyn dispatch between StrongSwan and WireGuard at runtime; ChunkStore has no equivalent runtime ambiguity and uses concrete types throughout.

### Decision: Three-zone architecture: pure types (no_std/no_alloc) → async traits (AFIT) → implementations (feature-gated)

**Status:** decided
**Rationale:** Zone 0 (pure types: StyreneManifest, ContentId, ChunkProfile, ChunkBitset) has zero runtime dependencies — works on RP2040 bare-metal with no heap. Zone 1 (async traits: ChunkStore, ContentTransport, ContentDistributor) adds async I/O contracts via AFIT — still no alloc, works everywhere. Zone 2 (implementations) is entirely feature-gated: RamChunkStore (alloc), TokioFsChunkStore (tokio), FlashChunkStore (embedded-storage), EspFsChunkStore (esp-idf). This means pulling in styrene-content with default features gives you only the protocol types and traits — usable on RP2040 with no overhead. Feature selection determines which runtime you compile for.

### Decision: ChunkStore uses zero-copy read interface — caller provides buffer, no Vec allocation in hot path

**Status:** decided
**Rationale:** read_chunk(&self, content_id, index, buf: &mut [u8]) → Result&lt;usize&gt; — caller owns the buffer. This avoids a Vec allocation on every chunk read, which matters on RP2040 where heap is absent or severely limited. The caller (ContentDistributor) can use a stack-allocated buffer sized to the chunk profile. For the tokio path, the same interface works — the caller just provides a heap-allocated buf. Consistent with embedded Rust convention (embedded-hal, embedded-io all use caller-provided buffers). This is the correct design for a trait that must work at both extremes of the memory spectrum.

### Decision: ChunkBitset is fixed [u8; 32] = 256 bits max — not dynamically sized

**Status:** decided
**Rationale:** A dynamic bitset requires alloc. Fixed [u8; 32] = 256 chunk slots covers: 256 × 4KB (lora) = 1MB on RP2040; 256 × 256KB (wifi) = 64MB on full nodes. Both are appropriate limits for their device classes. If a manifest declares chunk_count > 256, protocol nodes simply report bitsets for the first 256 chunks and cannot announce partial seeding beyond that; the protocol handles this gracefully. This is a documented protocol limit, not a silent failure. Revisit when a use case requires >64MB single-file distribution, which is not anticipated for firmware or data packs at this stage.

### Decision: Defer dyn ChunkStore compatibility — ContentDistributor uses concrete types throughout Phase 1 and 2

**Status:** decided
**Rationale:** ContentDistributor is instantiated once at daemon startup with a concrete type pair (e.g. ContentDistributor&lt;TokioFsChunkStore, LxmfTransport&gt;). No runtime type-switching is needed — configuration selects the implementation at compile time. dyn-compatibility would require either async_trait boxing (breaks no_alloc) or a manual vtable wrapper (complexity without benefit at MVP). The only scenario requiring dyn is heterogeneous dispatch across multiple simultaneously active distributor types, which is not a Phase 1 or Phase 2 requirement. If needed in Phase 3 (TUI browser with multiple content sources), add a DynChunkStore wrapper at that point.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `crates/libs/styrene-content/` (new) — New library crate — StyreneManifest, ContentDistributor, ChunkStore trait + RamChunkStore + FlashChunkStore
- `crates/libs/styrene-mesh/src/wire.rs` (modified) — Add StyreneMessageType::ResourceAvailable = 0xE0 and payload types for RESOURCE_AVAILABLE announce
- `crates/bindings/styrene-native/src/lib.rs` (modified) — Expose StyreneManifest, ContentId, ChunkProfile via PyO3 for Python hub
- `crates/bindings/styrene-native/src/content.rs` (new) — PyO3 bindings module for styrene-content types

### Constraints

- StyreneManifest must be signed by a Styrene identity — depends on styrene-identity design decisions
- Content ID must be stable regardless of chunk size — Blake3 tree hash satisfies this
- Protocol wire type 0xE0 (RESOURCE_AVAILABLE) must be added to styrene-mesh wire.rs
- LoRa path MTU (235 bytes) means chunk requests/responses must fragment through RNS Resources — chunk size must be a profile, not a constant
- Phase 1 does not require multi-peer swarming — single-seeder with verification is sufficient for fleet firmware
- The TUI browser surface (Phase 3) depends on styrene-tui Ratatui work being further along
- styrene-content must be no_std compatible for RP2040/ESP32 targets (use heapless for fixed-size collections)
- ChunkStore trait must work with both async (tokio) and sync (embedded) execution models — use core::future or feature-gate
- Blake3 crate is no_std compatible — verify before adding dependency
- FlashChunkStore on ESP32 uses NVS (Non-Volatile Storage) via esp-idf-svc; on RP2040 uses embedded-storage trait
- Content type field in manifest must map to ChunkStore policy at daemon startup — not hardcoded in the crate
- AFIT requires Rust 1.75+ — workspace is on 1.93, no issue
- Zone 0 and Zone 1 code must compile with #![no_std] and without the alloc crate
- Zone 2 implementations are only compiled when their feature flag is active — CI must test all four feature combinations: default, alloc, tokio, embedded-storage
- ContentDistributor must be 'static-bounded for embassy compatibility — no non-static references in the struct itself
- read_chunk buffer size must be documented as 'at least chunk_profile.chunk_size bytes' — callers size their buffers against the manifest's chunk_profile
- Blake3 no_std: verify blake3 crate's no_std support before adding dependency (blake3 supports no_std via no-default-features)
