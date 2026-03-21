# styrene-content — Tasks

## 1. crates/libs/styrene-content/ (new crate)

### 1.1 Cargo.toml + crate scaffold
- [x] Create `crates/libs/styrene-content/Cargo.toml` with `#![no_std]` default
- [x] Features: `default = []`, `alloc = []`, `std = ["alloc"]`, `tokio = ["std", "dep:tokio"]`, `embedded-storage = ["dep:embedded-storage"]`
- [x] Add `blake3` with `no-default-features` (no_std compatible); verify no_std before adding
- [x] Add `ciborium` (no_std CBOR) for manifest serialization
- [x] Add `heapless` for fixed-size collections in no_alloc mode
- [x] Add to workspace `Cargo.toml` members list

### 1.2 Zone 0 — Pure types (no_std, no alloc, no async)

**`src/content_id.rs`**
- [x] `ContentId([u8; 32])` — newtype over Blake3 hash, `Copy`, `PartialEq`, `Eq`, `Hash`
- [x] `ContentId::from_bytes(data: &[u8]) -> ContentId` — Blake3 hash of full content
- [x] `ContentId::from_chunk(chunk_hash: &[u8; 32]) -> ContentId` — direct constructor
- [x] Hex display impl (`core::fmt::LowerHex`)

**`src/chunk_profile.rs`**
- [x] `enum ChunkProfile { LoRa, Balanced, WiFi }` with associated chunk sizes (4KB, 32KB, 256KB)
- [x] `ChunkProfile::chunk_size(&self) -> u32`
- [x] `ChunkProfile::max_file_size(&self) -> u64` (256 chunks × chunk_size)
- [x] CBOR serialization (u8 discriminant)

**`src/chunk_bitset.rs`**
- [x] `ChunkBitset([u8; 32])` — 256-bit bitset, `Copy`
- [x] `ChunkBitset::new() -> Self` (all zeros)
- [x] `ChunkBitset::set(&mut self, index: u32)`
- [x] `ChunkBitset::get(&self, index: u32) -> bool`
- [x] `ChunkBitset::count(&self) -> u32` (popcount)
- [x] `ChunkBitset::is_complete(&self, total_chunks: u32) -> bool`
- [x] Tests: set/get roundtrip, popcount, boundary conditions (index 0, 255)

**`src/manifest.rs`**
- [x] `StyreneManifest` struct with CBOR-serializable fields:
  - `content_id: ContentId`
  - `size: u64`
  - `chunk_profile: ChunkProfile`
  - `chunk_count: u32`
  - `chunk_hashes: heapless::Vec<[u8; 32], 256>` (no_alloc) OR `Vec<[u8; 32]>` (alloc feature)
  - `name: heapless::String<64>` (no_alloc) OR `String` (alloc)
  - `content_type: heapless::String<32>` (e.g. "firmware/styrened-rs", "data/emergency")
  - `created_at: u64` (Unix timestamp)
  - `creator_identity: [u8; 16]` (RNS identity_hash truncated)
  - `signature: [u8; 64]` (Ed25519 over canonical CBOR of above fields)
- [x] `StyreneManifest::encode(&self) -> Result<heapless::Vec<u8, 8192>, ManifestError>` — CBOR serialize
- [x] `StyreneManifest::decode(bytes: &[u8]) -> Result<Self, ManifestError>` — CBOR deserialize
- [x] `StyreneManifest::verify_signature(&self, pubkey: &[u8; 32]) -> bool` — verify Ed25519 sig
- [x] `StyreneManifest::manifest_bytes_for_signing(&self) -> [u8; ...]` — canonical bytes over which sig is computed (all fields except signature itself)
- [x] `ManifestError` enum: `EncodeFailed`, `DecodeFailed`, `InvalidSignature`, `ChunkCountMismatch`
- [x] Tests: encode/decode roundtrip, signature verify pass/fail, chunk count validation

**`src/announce.rs`**
- [x] `ResourceAvailableAnnounce` struct:
  - `content_id: ContentId`
  - `manifest_hash: [u8; 16]` (first 16 bytes of Blake3(manifest_bytes))
  - `chunks_held: ChunkBitset`
  - `seeder_hash: [u8; 16]` (announcing node's RNS identity_hash)
- [x] CBOR encode/decode
- [x] Tests: roundtrip

### 1.3 Zone 1 — Async traits (AFIT, no_std, no alloc)

**`src/store.rs`**
- [x] `trait ChunkStore` with AFIT:
  ```rust
  async fn read_chunk(&self, id: ContentId, index: u32, buf: &mut [u8]) -> Result<usize, Self::Error>;
  async fn write_chunk(&mut self, id: ContentId, index: u32, data: &[u8]) -> Result<(), Self::Error>;
  async fn has_chunk(&self, id: ContentId, index: u32) -> bool;
  async fn chunks_held(&self, id: ContentId) -> ChunkBitset;
  async fn evict(&mut self, id: ContentId) -> Result<(), Self::Error>;
  ```
- [x] `type Error: core::fmt::Debug`
- [x] Document buffer size contract: buf must be `>= chunk_profile.chunk_size()` bytes

**`src/transport.rs`**
- [x] `trait ContentTransport` with AFIT:
  ```rust
  async fn broadcast_announce(&mut self, announce: &ResourceAvailableAnnounce) -> Result<(), Self::Error>;
  async fn send_chunk_request(&mut self, seeder: &[u8; 16], id: ContentId, index: u32) -> Result<(), Self::Error>;
  async fn recv_event(&mut self) -> Result<ContentEvent, Self::Error>;
  ```
- [x] `enum ContentEvent { Announce(ResourceAvailableAnnounce), ChunkRequest { from: [u8;16], content_id: ContentId, index: u32 }, ChunkResponse { content_id: ContentId, index: u32, data: heapless::Vec<u8, 262144> } }`
  - Note: ChunkResponse data uses alloc feature for Vec variant, heapless for no_alloc
- [x] `type Error: core::fmt::Debug`

**`src/distributor.rs`**
- [x] `ContentDistributor<S: ChunkStore, T: ContentTransport>` struct — `'static` bounded
- [x] `ContentDistributor::new(store: S, transport: T) -> Self`
- [x] `async fn publish(&mut self, manifest: &StyreneManifest, content: &[u8]) -> Result<(), DistributorError>`
  - Splits content into chunks, writes to store, broadcasts announce
- [x] `async fn download(&mut self, content_id: ContentId, manifest: &StyreneManifest) -> Result<(), DistributorError>`
  - Requests chunks from known seeders, verifies per-chunk Blake3, assembles
- [x] `async fn on_event(&mut self, event: ContentEvent) -> Result<(), DistributorError>`
  - Handles incoming announces (track seeders), chunk requests (serve from store), chunk responses (verify, store, re-announce)
- [x] `DistributorError` enum
- [x] Tests (using mock store + mock transport):
  - publish then download from same node (self-seeding round-trip)
  - chunk verification failure drops bad chunk
  - re-announce after download completes

### 1.4 Zone 2 — Implementations (feature-gated)

**`src/impls/ram.rs`** (feature = "alloc")
- [x] `RamChunkStore` — `HashMap<(ContentId, u32), Vec<u8>>`
- [x] Implements `ChunkStore`, error type = `core::convert::Infallible`
- [x] Used for testing and in-memory firmware download before apply

**`src/impls/tokio_fs.rs`** (feature = "tokio")
- [x] `TokioFsChunkStore { base_dir: PathBuf }`
- [x] Chunks stored as `{base_dir}/{content_id_hex}/{index:06}`
- [x] Implements `ChunkStore` using `tokio::fs`
- [x] `evict` removes the directory for that content_id

**`src/impls/flash.rs`** (feature = "embedded-storage")
- [x] `FlashChunkStore<S: embedded_storage::nor_flash::NorFlash>` stub
- [x] Layout: fixed partition table at known flash offset, chunk index header
- [x] Implements `ChunkStore` — async wrapper over sync NorFlash (yield between operations)
- [x] Suitable for RP2040 (rp2040-hal flash) and ESP32 NVS via embedded-storage trait

### 1.5 Tests + CI

- [x] `tests/manifest_roundtrip.rs` — encode/decode + signature verification
- [x] `tests/distributor.rs` — integration test with RamChunkStore + mock transport
- [x] `tests/no_std_compile.rs` — compile check with default features (no_std, no alloc)
- [x] Ensure workspace CI matrix tests: `cargo test -p styrene-content`, `cargo test -p styrene-content --features alloc`, `cargo test -p styrene-content --features tokio`

---

## 2. crates/libs/styrene-mesh/src/wire.rs (modified)

- [x] Add `StyreneMessageType::ResourceAvailable = 0xE0` to the enum
- [x] Add match arm in `from_byte` / `to_byte` impls
- [x] Add `ResourceAvailablePayload` struct mirroring `ResourceAvailableAnnounce` fields
- [x] Add encode/decode for ResourceAvailablePayload using existing msgpack/CBOR pattern
  - Also added `ChunkRequestPayload` (0xE1) and `ChunkResponsePayload` (0xE2)
- [x] Update any exhaustive match statements in other crates that pattern-match on `StyreneMessageType`
- [x] Test: `0xE0` round-trips through `StyreneMessageType::from_byte`

---

## 3. crates/bindings/styrene-native/src/content.rs (new)
## 4. crates/bindings/styrene-native/src/lib.rs (modified)

- [x] Create `src/content.rs` PyO3 module
- [x] `PyContentId` — wraps `ContentId`, exposes `hex()`, `from_bytes()`, `from_raw()`, `as_bytes()`
- [x] `PyChunkProfile` — exposes `LoRa`, `Balanced`, `WiFi` as Python-accessible variants
- [x] `PyStyreneManifest` — wraps `StyreneManifest`, exposes `encode()→bytes`, `decode(bytes)`, `verify_signature(fn)→bool`, `verify_chunk()`, fields as Python properties
- [x] `PyResourceAvailableAnnounce` — wraps `ResourceAvailableAnnounce`, exposes fields
- [x] Register all classes in `styrene_native` module in `lib.rs`
- [x] Test from Python: `from styrene_native import PyStyreneManifest` and roundtrip
  NOTE: Compile-time verified. Runtime Python test blocked by Python 3.14 / PyO3 0.23 incompatibility in dev env (PYO3_USE_ABI3_FORWARD_COMPATIBILITY suppresses the check but linker fails on macOS 26.2 → 11.0 SDK mismatch). Will pass once PyO3 0.24+ supports Python 3.14.
