---
id: styrene-identity
title: Styrene Identity System
status: exploring
tags: [identity, cryptography, post-quantum, yubikey, rns, lxmf, yggdrasil, wireguard, i2p, key-derivation, architecture]
open_questions:
  - "Root algorithm: Ed25519-only (YubiKey-compatible today), hybrid Ed25519+ML-DSA-65, or ML-DSA-65-only? Which assurance level justifies the on-wire size cost of ML-DSA?"
  - Does RNS use a key format compatible with HKDF derivation from a root secret? (secp256k1? EC prime256v1? Custom?) Can we derive a valid RNS identity seed deterministically, or must it be independently generated and cross-signed?
  - "Identity manifest distribution: RNS app_data is bandwidth-constrained. Should the manifest fingerprint (32 bytes) travel in announces with full manifest fetchable via /meta or NomadNet, or is there a more efficient gossip mechanism?"
  - "Key revocation and rotation: if a protocol-specific derived key is compromised (e.g., WireGuard private key exposed), how does the operator revoke just that binding without invalidating the root StyreneID or their existing conversations?"
  - "Identity continuity/recovery: if the YubiKey is lost/destroyed, how does the operator prove to their peers that a new key is the same person? Social recovery (m-of-n trusted peers co-sign a migration)? A recovery seed phrase?"
  - "Constrained device support: RP2040/ESP32 nodes cannot afford ML-DSA key storage (~4KB private key) or compute. Do embedded nodes get a \"lite\" StyreneID (Ed25519 only) that is managed by their operator's full node, or is there a different trust model for constrained peers?"
---

# Styrene Identity System

## Overview

A unified root identity for Styrene that sits above all protocol-specific identities. The StyreneID is the single source of truth: it can be hardware-backed (YubiKey first-class), and all protocol-specific keys (RNS, LXMF, Yggdrasil, WireGuard, I2P, BATMAN, …) are derived from or cross-signed by it. This eliminates the hash confusion problem discovered in the TUI audit (multiple disconnected peer_hash spaces) and creates a stable, portable, extensible identity primitive that can grow to include new protocols without retroactive breakage.

## Research

### Why this is necessary — the hash audit as motivating evidence

The TUI adversarial audit (2026-03-10) found 8 distinct bugs all tracing to the same root: there is no canonical Styrene identity, so every protocol layer carries its own independent hash, and the code has no authoritative place to resolve one to the others. Concretely:

- A single Styrene peer has at minimum THREE independent hash values: RNS identity_hash, RNS destination_hash (per-aspect), LXMF delivery destination_hash. For a node also on Yggdrasil/I2P that adds two more address spaces.
- The TUI's `MeshDevice.identity` property returns `destination_hash` (historical accident), not `identity_hash`. Every screen that uses `device.identity` as a conversation key hits the wrong hash space.
- `ChatWidget.peer_hash = device.destination_hash` → messages stored under LXMF hash → 0 messages displayed.
- Dashboard unread badge queries `unread_counts[destination_hash]` but the map is keyed by LXMF hash → badge always shows 0.
- `PeerWorkspaceContext.peer_identity_hash` stores destination_hash in all current callers.
- `bridge.set_contact(peer_hash=destination_hash)` → contact's peer_hash can't cross-reference conversations keyed by LXMF hash.

These bugs cannot be patched cleanly one by one. They're symptoms of needing a resolution layer that maps all known protocol hashes for a given entity to a single canonical StyreneID. The StyreneID becomes the key for everything: cache, contacts, conversations, presence, RBAC, UI navigation.

### Algorithm selection — ML-KEM vs ML-DSA vs classical

User proposed: ML-KEM (or "KL-MEM") at 512. Clarification and correction:

**ML-KEM (FIPS 203 / CRYSTALS-Kyber)** — Key Encapsulation Mechanism
- Purpose: establishing shared secrets (encryption/key exchange), NOT signing
- Variants: ML-KEM-512 (~AES-128 security), ML-KEM-768 (~AES-192), ML-KEM-1024 (~AES-256)
- YubiKey support: not yet (as of early 2026)
- Use case in Styrene: session key establishment for WireGuard or Yggdrasil handshakes (future)

**ML-DSA (FIPS 204 / CRYSTALS-Dilithium)** — Digital Signature Algorithm
- Purpose: signing — what you actually want for a ROOT IDENTITY KEY
- Variants: ML-DSA-44 (~128-bit), ML-DSA-65 (~192-bit), ML-DSA-87 (~256-bit)
- Public key size: 1312 / 1952 / 2592 bytes
- Signature size: 2420 / 3293 / 4595 bytes
- LARGE compared to Ed25519 (32 byte pubkey, 64 byte sig) — matters for mesh bandwidth

**SLH-DSA (FIPS 205 / SPHINCS+)** — Hash-based signatures
- Stateless, no lattice math — simpler security argument
- Much larger signatures (~8KB), slower
- Better for long-lived root keys (less risk of algorithm break)

**Practical recommendation — Hybrid root:**
Ed25519 (hardware-compatible today, 32-byte pubkey) + ML-DSA-65 (PQ signing) as a hybrid signature scheme. The classical component gives YubiKey compatibility today; the PQ component gives forward security. Systems that understand only classical see Ed25519. Systems that understand the Styrene identity see both.

The hybrid approach is how the IETF and Signal are approaching this — not replacing classical but layering PQ on top.

**Derivation vs. cross-signing strategy:**
- For protocols where we control the key format (Yggdrasil Ed25519, WireGuard Curve25519): HKDF-derive from the root secret with protocol-specific salt → deterministic, recoverable from root seed
- For protocols we don't control (RNS, I2P): generate the key separately, then the Styrene root signs a binding attestation manifest: `{styrene_id, rns_identity_hash, lxmf_destination_hash, ygg_address, wg_pubkey, timestamp, signature}`
- The manifest is the cross-protocol identity proof. Distributed via RNS announces (app_data), NomadNet page, or LXMF identity message.

**Key sizes on-wire for Reticulum:**
RNS app_data is limited. A full ML-DSA-65 pubkey (1952 bytes) in every announce would be costly. Options:
1. Announce only a hash of the StyreneID pubkey (32 bytes) + full pubkey fetchable via /meta or NomadNet page
2. Use a shorter hash fingerprint (like Signal's Safety Number concept)
3. Ed25519 only in announces + PQ cert fetchable on demand

### YubiKey integration model — first-class hardware backing

**Current YubiKey 5 capabilities (as of 2026):**
- PIV slots: RSA-2048/4096, ECC P-256/P-384/P-521
- FIDO2: Ed25519 resident keys (firmware 5.2.3+), ed25519-sk with discoverable credentials (5.4+)
- OpenPGP: RSA, ECC P-256/P-384, Ed25519, Cv25519 (for encryption)
- ML-DSA (post-quantum): NOT YET supported in hardware. YubiKey has not shipped PQ PIV firmware as of early 2026.

**Practical YubiKey strategy today:**
- Store Ed25519 signing key in PIV slot or FIDO2 resident key on YubiKey
- This is the classical half of the hybrid root
- ML-DSA key lives in software (encrypted at rest, unlocked via PIN/passphrase derived from YubiKey HMAC-SHA1 challenge-response)
- When YubiKey adds PQ support: migrate ML-DSA key to hardware, keep backward compat

**YubiKey challenge-response for key derivation:**
YubiKey slot 2 supports HMAC-SHA1 challenge-response (static secret on device). This can be used to:
- Derive the encryption key for the software PQ private key storage (challenge = machine fingerprint or random nonce stored in config, response = decryption key)
- This means: PQ key is encrypted on disk, only decryptable with YubiKey present
- Effectively hardware-backing the PQ key without native PQ PIV support

**Three-tier identity hardware model:**
1. **YubiKey present**: Ed25519 signing in hardware + HMAC-derived key unlocks ML-DSA software key → full hybrid PQ identity
2. **Software only (default)**: Ed25519 + ML-DSA both in software, password-protected → same crypto, lower assurance
3. **Minimal/embedded**: Ed25519 only (for constrained devices like RP2040 that can't afford ML-DSA storage/compute)

**PIV vs FIDO2 for signing:**
- PIV: better tooling, more control, requires PIN, works for SSH/TLS/email
- FIDO2: more portable, WebAuthn compat, resident keys require touch
- Recommendation: PIV for the signing key (more control over the raw Ed25519 key), FIDO2 optionally for web-facing use
- The `styrened doctor --setup` wizard would detect YubiKey and configure the appropriate slot

### Protocol key binding — the derivation/attestation map

**Core concept: StyreneID is the anchor. Protocol keys are bound to it.**

For each protocol, there are two approaches:

### Deterministic derivation (preferred where possible)

Root secret → HKDF(secret, salt="styrene-{protocol}-v1", info=protocol_params) → protocol key material

| Protocol | Key type | Derivable? | Notes |
|---|---|---|---|
| Yggdrasil | Ed25519 | YES | ygg_privkey = HKDF(root, "styrene-ygg-v1") |
| WireGuard | Curve25519 | YES | wg_privkey = HKDF(root, "styrene-wg-v1") |
| RNS Identity | EC (proprietary curve) | MAYBE | RNS uses secp256k1 or similar — needs investigation |
| LXMF delivery | Derived from RNS | AUTO | LXMF destination = RNS identity + "lxmf" + "delivery" |
| BATMAN-adv | MAC-layer | N/A | No cryptographic identity, use RNS as overlay |
| I2P | ElGamal+ECDSA or X25519+EdDSA | PARTIAL | Newer "ECIES" format uses X25519 + EdDSA, HKDF-derivable |
| TLS/HTTPS | P-256 or Ed25519 cert | YES | Self-signed cert, HKDF-derived, signed by StyreneID |
| SSH host key | Ed25519 | YES | ssh_hostkey = HKDF(root, "styrene-ssh-host-v1") |
| SSH user key | Ed25519 | YES | per-user-label: HKDF(root, "styrene-ssh-user-{label}-v1") |

### Cross-signing (for protocols where derivation is impractical)

Generate an independent key, then publish a signed attestation:
```json
{
  "styrene_id_pubkey": "...",  // Ed25519 + ML-DSA hybrid pubkey
  "version": 1,
  "issued_at": 1234567890,
  "bindings": {
    "rns_identity_hash": "abc123...",
    "lxmf_destination_hash": "def456...",
    "ygg_address": "200:dead:beef::1",
    "wg_pubkey": "xyz789...",
    "i2p_address": "example.b32.i2p"
  },
  "signature": "..."  // Ed25519 + ML-DSA hybrid signature over canonical JSON
}
```
This "identity manifest" is:
- Fetchable via NomadNet page at a well-known path (/id or /identity)
- Distributable via LXMF as an identity announcement message
- Embedded (truncated fingerprint) in RNS app_data
- Cached locally with TTL (mesh nodes remember each other's manifests)

### The StyreneID as a NAB (Name-and-Bindings) record

This is conceptually similar to a self-sovereign identity (SSI) DID document, but:
- Self-signed (no external PKI dependency)
- Mesh-native distribution (not DNS/blockchain)
- Upgradeable (new bindings added without invalidating old ones)
- Backward compatible (RNS still works without the manifest; manifest just adds cross-protocol proof)

### Hash resolution layer (the fix for the TUI bug)

The daemon maintains a local index:
```
styrene_id → {rns_identity_hash, rns_destination_hash, lxmf_destination_hash, ygg_address, ...}
rns_identity_hash → styrene_id
rns_destination_hash → styrene_id
lxmf_destination_hash → styrene_id
ygg_address → styrene_id
```
ALL TUI state (contacts, conversations, unread counts, RBAC, cache) is keyed by `styrene_id`, not by any protocol-specific hash. The resolution layer translates any inbound hash to styrene_id and from there to all other protocol addresses.

This directly fixes every bug from the TUI audit: there's one canonical key, and the system knows how to translate between all the protocol-specific representations.

### Relationship to existing RNS identity — adoption, not replacement

**Critical constraint**: Existing Reticulum infrastructure uses RNS identity as its fundamental trust anchor. We cannot replace this — we can only extend it.

**The "adopt downward" model:**
- StyreneID does NOT replace the RNS identity. RNS still uses its own identity for routing.
- StyreneID wraps and binds to the RNS identity.
- For existing nodes: the StyreneID is created and immediately binds to their existing RNS identity_hash.
- For new nodes: optionally derive the RNS key seed from the StyreneID root secret, establishing a tighter coupling.

**Migration path for existing users:**
1. User has existing RNS identity (stored in ~/.reticulum/storage/identities/)
2. `styrened identity --upgrade` creates a StyreneID, imports current RNS identity_hash as a binding
3. The StyreneID manifest is published — the rest of the mesh sees continuity (same RNS hash)
4. The StyreneID is the new persistence and backup primitive

**The self-signed default:**
Without a YubiKey, the StyreneID is a software key:
- Generated once during `styrened doctor --setup` or first run
- Stored encrypted at `~/.styrene/identity/styrene-id.key` (argon2id + ChaCha20-Poly1305)
- The Ed25519 component is also registered as an additional RNS identity (allows RNS path requests)
- The ML-DSA component adds PQ signing even without hardware

**What "superset" means in practice:**
- RNS peers without StyreneID: normal RNS routing still works (backward compatible)
- Styrene peers with StyreneID: additionally publish manifest, support cross-protocol lookup
- Hub/propagation nodes: cache and forward manifests (like LXMF propagation)
- The TUI shows enhanced info for peers with known StyreneID: all their addresses, cross-protocol reachability

### Q2 RESOLVED: RNS identity is fully HKDF-derivable from root secret

Audited RNS/Identity.py directly (installed at site-packages/RNS/Identity.py).

**RNS Identity internals:**
```
KEYSIZE = 256*2 = 512 bits total
TRUNCATED_HASHLENGTH = 128 bits (16 bytes = 32 hex chars)

Private key (64 bytes):
  [0:32]  = X25519PrivateKey — ECDH encryption key
  [32:64] = Ed25519PrivateKey — signing key

Public key (64 bytes):
  [0:32]  = X25519PublicKey (derived from prv)
  [32:64] = Ed25519PublicKey (derived from sig_prv)

identity_hash = SHA-256(pub_bytes + sig_pub_bytes)[:16]  (truncated to 128 bits)
```

**Critical: both private components accept arbitrary 32-byte seeds:**
```python
X25519PrivateKey.generate()           → from_private_bytes(os.urandom(32))
Ed25519PrivateKey.generate()          → from_private_bytes(os.urandom(32))
Identity.load_private_key(prv_bytes)  → splits 64-byte input as [0:32] + [32:64]
```

Both are raw 32-byte seeds with no special constraints (X25519 does internal bit-clamping in the library, but `from_private_bytes` accepts any 32 bytes). This means **full HKDF derivation is possible:**

```python
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256

rns_enc_seed  = HKDF(SHA256, length=32, salt=b"styrene-v1", info=b"rns-encryption").derive(root_secret)
rns_sign_seed = HKDF(SHA256, length=32, salt=b"styrene-v1", info=b"rns-signing").derive(root_secret)
rns_prv_bytes = rns_enc_seed + rns_sign_seed  # 64 bytes

identity = RNS.Identity(create_keys=False)
identity.load_private_key(rns_prv_bytes)
# identity.hash is now deterministic from root_secret
```

**Implication:** The RNS identity_hash is 100% derivable and stable from the StyreneID root. No cross-signing needed for new installs. The StyreneID root IS the single seed for the entire key hierarchy.

**LXMF follows automatically:** LXMF delivery destination_hash is derived from the RNS identity + "lxmf" + "delivery" (by RNS Destination hashing), so it's also deterministic. No separate derivation step.

**Migration case:** Existing nodes with a pre-StyreneID RNS identity keep their existing keys. They generate a StyreneID, publish a cross-signed manifest binding their existing rns_identity_hash to the new StyreneID pubkey. Going forward, the old RNS identity persists for network continuity. This is the "adopt downward" path. A clean reinstall would derive a new RNS identity from the StyreneID root (new rns_identity_hash, network needs to relearn the peer).

**Key sizes confirmed:**
- RNS identity_hash: 16 bytes / 32 hex chars (not 32 bytes as sometimes assumed)
- Destination_hash: also 16 bytes / 32 hex chars
- These are TRUNCATED SHA-256, not full hashes

### Q3 DEEP SECURITY ANALYSIS: fingerprint-in-announce vs full-key



## Decisions

### Decision: Third-party attestations are additive, opt-in, and non-coercive

**Status:** decided
**Rationale:** A CAC, corporate PKI, or any other X.509-backed identity can sign a binding attestation: "I, holder of this verified credential, assert that this StyreneID public key is mine." That attestation travels with the identity manifest as an optional attestations[] array. Peers who trust the issuing PKI chain can verify it. Peers who don't care ignore it entirely. This is additive — it says nothing about what the peer can do on the network, only provides a verifiable claim about who they are. No Styrene peer is forced to trust any attestation chain. This is explicitly different from CAC-as-hardware-token (using the CAC device for key derivation/protection) vs. CAC-as-attestation (the DoD cert chain vouches for the StyreneID holder). Both use cases are supported and composable: a DoD operator can use their CAC as the hardware token AND publish its attestation.

## Open Questions

- Root algorithm: Ed25519-only (YubiKey-compatible today), hybrid Ed25519+ML-DSA-65, or ML-DSA-65-only? Which assurance level justifies the on-wire size cost of ML-DSA?
- Does RNS use a key format compatible with HKDF derivation from a root secret? (secp256k1? EC prime256v1? Custom?) Can we derive a valid RNS identity seed deterministically, or must it be independently generated and cross-signed?
- Identity manifest distribution: RNS app_data is bandwidth-constrained. Should the manifest fingerprint (32 bytes) travel in announces with full manifest fetchable via /meta or NomadNet, or is there a more efficient gossip mechanism?
- Key revocation and rotation: if a protocol-specific derived key is compromised (e.g., WireGuard private key exposed), how does the operator revoke just that binding without invalidating the root StyreneID or their existing conversations?
- Identity continuity/recovery: if the YubiKey is lost/destroyed, how does the operator prove to their peers that a new key is the same person? Social recovery (m-of-n trusted peers co-sign a migration)? A recovery seed phrase?
- Constrained device support: RP2040/ESP32 nodes cannot afford ML-DSA key storage (~4KB private key) or compute. Do embedded nodes get a "lite" StyreneID (Ed25519 only) that is managed by their operator's full node, or is there a different trust model for constrained peers?

## Proposal

Include only a 32-byte SHA-256 fingerprint of the StyreneID public key in RNS announces (app_data). Full key fetchable on demand via /meta or NomadNet page.

## Why the size matters

- ML-DSA-65 public key: 1952 bytes
- Ed25519 public key: 32 bytes
- Hybrid pubkey: ~1984 bytes
- RNS announce app_data budget: typically ~256 bytes practical limit on LoRa (1152 MTU minus headers, routing, etc.)
- A full hybrid pubkey in every announce would dwarf the actual payload and likely exceed LoRa packet limits entirely, causing fragmentation or rejection.
- 32-byte fingerprint: fits easily in any app_data budget

## Threat models analyzed

### 1. Fingerprint forgery (preimage attack)
Attacker wants to claim they are StyreneID X by announcing fingerprint F = SHA-256(X_pubkey).
They cannot produce a forged key that hashes to F without breaking SHA-256 preimage resistance (2^256 work). **SAFE.**

### 2. Fingerprint collision (birthday attack)
Attacker generates two StyreneIDs where SHA-256(key_A) == SHA-256(key_B). Birthday bound for SHA-256 is 2^128. **SAFE** — SHA-256 is collision resistant for any attacker today or in the quantum era (Grover's on SHA-256 gives 2^128 classical equivalent, not broken by quantum).

### 3. MITM during /meta fetch
When peer A fetches the full StyreneID key via /meta from peer B:
- Attack: adversary intercepts the /meta response and substitutes a forged key K_fake
- Defense: after fetch, peer A checks SHA-256(fetched_pubkey) == announced_fingerprint
- For this to succeed, attacker needs SHA-256(K_fake) == F → preimage attack → 2^256 work. **SAFE if verification step is performed.**
- **REQUIRED**: the fetch verification step MUST be implemented and MUST happen before trusting the key. This is non-negotiable.

### 4. Announce replay with stale fingerprint
Attacker replays an old announce packet containing a valid fingerprint F.
- RNS already handles announce replay via timestamp/sequence in the transport layer
- Even if replayed: fingerprint still points to the correct real key → no harm beyond normal announce replay (which RNS handles)
- **SAFE, handled by RNS transport.**

### 5. TOFU (Trust On First Use) window
The first time peer A sees peer B's fingerprint, the full key hasn't been fetched yet.
- Risk: if peer A takes action based on StyreneID claims before fetch+verify completes, it's acting on an unverified identity
- Mitigation: treat peers as "RNS-authenticated only" until StyreneID is fetched and verified. No StyreneID-specific features (cross-protocol addresses, attestations) are exposed until verification. Basic RNS routing still works (independent of StyreneID). 
- The TUI should show a "⧖ StyreneID pending" indicator rather than showing unverified data.
- **SAFE if verification is gated: don't expose StyreneID features until SHA-256(fetched_key) == announced_fingerprint is confirmed.**

### 6. Fingerprint downgrade (announcing with no fingerprint)
A Styrene node could suppress its StyreneID fingerprint from announces, hiding its cross-protocol addresses.
- This is operator choice, not an attack. The operator simply chooses not to publish their StyreneID.
- Peers see the node as "StyreneID unknown" — they can still communicate via RNS/LXMF normally.
- **NOT a security issue; intentional behavior.**

### 7. Selective fingerprint (announcing someone else's fingerprint)
Malicious node M announces fingerprint F belonging to legitimate node L.
- Peer fetches full key K_L via /meta from node M. But M can't return K_L (doesn't have it) and can't forge a key with hash F (preimage resistance).
- M could return garbage → SHA-256(garbage) ≠ F → verification fails → peer marks StyreneID as invalid for M.
- M could return K_L's pubkey — but then M is correctly attributing the identity to L, not claiming it as their own. The StyreneID is tied to the RNS identity that signed the announce: `SHA-256(manifest.rns_identity_hash)` must match the known RNS identity of M. If the manifest says rns_identity_hash = L's hash but the announce came from M's RNS identity, the binding check fails.
- **SAFE if manifest verification includes confirming rns_identity_hash matches the announce's RNS identity.**

### 8. Bandwidth/storage for cached fingerprints
32 bytes per known peer. For a hub with 10,000 known nodes: 320KB of fingerprint cache. Negligible. **SAFE.**

### 9. Fingerprint as contact lookup key
After the full key is fetched and fingerprint is verified, the fingerprint is a stable 32-byte identifier for the peer. It can be used as a database key for cached manifests. This is actually better than using rns_identity_hash (16 bytes) because it's collision-resistant at 256 bits vs 128 bits.

## Verdict: APPROVED with mandatory verification

Fingerprint-in-announce is cryptographically sound provided:
1. **SHA-256(fetched_pubkey) == announced_fingerprint** is verified before trusting the key (closes MITM fetch attack)
2. **manifest.rns_identity_hash matches the announcing RNS identity** (closes fingerprint theft attack)
3. **StyreneID features are gated** on verification completion (closes TOFU window)
4. **Fingerprint is optional** — absence means "no StyreneID, RNS-only node" (not a failure)

These are all implementable constraints, not showstoppers.

## On-wire encoding

In app_data, the fingerprint field is 32 bytes. Suggest compact binary encoding (not hex) to preserve announce space. A sentinel byte prefix (e.g. 0x53 = 'S') identifies the field as a StyreneID fingerprint, allowing future field additions without breaking existing parsers. Total overhead: 33 bytes in app_data.
