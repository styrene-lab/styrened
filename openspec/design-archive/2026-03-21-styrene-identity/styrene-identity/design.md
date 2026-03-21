# Styrene Identity System — Design

## Architecture Decisions

### Decision: Third-party attestations are additive, opt-in, and non-coercive

**Status:** decided
**Rationale:** A CAC, corporate PKI, or any other X.509-backed identity can sign a binding attestation: "I, holder of this verified credential, assert that this StyreneID public key is mine." That attestation travels with the identity manifest as an optional attestations[] array. Peers who trust the issuing PKI chain can verify it. Peers who don't care ignore it entirely. This is additive — it says nothing about what the peer can do on the network, only provides a verifiable claim about who they are. No Styrene peer is forced to trust any attestation chain. This is explicitly different from CAC-as-hardware-token (using the CAC device for key derivation/protection) vs. CAC-as-attestation (the DoD cert chain vouches for the StyreneID holder). Both use cases are supported and composable: a DoD operator can use their CAC as the hardware token AND publish its attestation.

### Decision: IdentitySigner is an abstract trait with four pluggable backend tiers

**Status:** decided
**Rationale:** Hardware (YubiKey) and software (Bitwarden) credential stores differ in extractability and portability but are both valid identity backends. Rather than privileging one, Styrene defines an IdentitySigner trait (Rust) / interface (Python) with tier-annotated implementations: HardwareHsm (YubiKey PIV/FIDO2), DeviceHsm (Secure Enclave / Android Keystore), CredentialManager (Bitwarden, 1Password, system keychain), EncryptedFile (default). Tier C (CredentialManager) is the right default for most operators — cross-device portability without a physical token, with Vaultwarden available for self-hosted deployments. Tier A (YubiKey) is the escalation path for high-threat users. All tiers feed the same HKDF derivation hierarchy — the backend is only involved in holding the root secret and performing the root Ed25519 signing operation.

### Decision: Use Bitwarden as raw key store (SSH key / secure note), not as FIDO2 signer

**Status:** decided
**Rationale:** FIDO2 passkeys wrap signatures in authenticatorData + clientDataJSON with rpId binding — not suitable for signing arbitrary RNS packets without protocol friction. The cleaner path: store the Styrene root secret or Ed25519 private key as a Bitwarden SSH key item or secure note. styrened retrieves it via Bitwarden SDK or rbw CLI at startup, holds it in memory for the session, clears on shutdown. This is identical to how the Bitwarden SSH agent handles SSH keys. The passkey feature (FIDO2) remains relevant for web-facing authentication (Styrene web UI login), not for mesh identity signing.

### Decision: Tier B is platform-native credential system, not raw Secure Enclave — hardware backing is an implementation detail

**Status:** decided
**Rationale:** The previous framing of Tier B as "Secure Enclave / Android Keystore" conflated hardware backing (an implementation detail) with the user-facing credential management tier. The correct Tier B is iCloud Keychain / Apple Passwords on Apple platforms and Android Credential Manager on stock Android. These happen to use Secure Enclave / Keystore with StrongBox under the hood on capable hardware, but the tier is defined by the UX: OS-integrated, biometric unlock, no additional software. This makes the tier ladder coherent from a user perspective: hardware token → platform native → FOSS manager → encrypted file.

### Decision: Hybrid Ed25519+ML-DSA-65 root; Ed25519 travels on-wire, ML-DSA lives in manifest only

**Status:** decided
**Rationale:** ML-DSA-65's 1952-byte pubkey is incompatible with bandwidth-constrained RNS links (RNode LoRa: ~235 byte packets). Ed25519 is YubiKey-compatible today and sufficient for mesh routing. The hybrid gives harvest-now-decrypt-later protection without breaking existing infrastructure: Ed25519 pubkey (32 bytes) travels in RNS announces as the network identity; ML-DSA-65 pubkey lives only in the full identity manifest fetched on demand. Nodes without StyreneID awareness see a normal RNS peer. Identity manifest fingerprint in app_data is SHA-256(ed25519_pubkey || ml_dsa_pubkey)[:16] — 16 bytes, fits alongside existing fields. Full manifest distributed via /meta or NomadNet /id page, cached locally with TTL, propagated by hubs via LXMF store-and-forward. No gossip protocol needed at launch.

### Decision: Per-binding revocation via superseding manifest; root rotation via signed migration assertion

**Status:** decided
**Rationale:** HKDF is one-way — a compromised derived key (WireGuard, Yggdrasil) does not expose the root secret. Per-binding rotation: publish a new manifest with a replacement binding for that protocol, signed by the root key, with a later issued_at timestamp. Peers accept the newer manifest; old binding is superseded. Root key rotation (root itself compromised) requires a signed migration assertion: {old_styrene_id_sig, new_styrene_id_pubkey, issued_at} signed by BOTH old and new root keys, distributed to trusted peers who then update their resolution tables. This shares a solution path with recovery (Q4).

### Decision: Constrained devices (RP2040/ESP32) are operator-managed sub-identities, not root peers

**Status:** decided
**Rationale:** RP2040/ESP32 cannot store a 4KB ML-DSA key or compute lattice signatures. They remain pure RNS nodes. Operator's StyreneID manifest includes a managed_nodes section: [{rns_identity_hash, device_type, label}], signed by the operator's root. Trust in the embedded node is delegated trust in its operator. No ML-DSA storage or compute required on device. Same trust model as RBAC managed endpoints.

### Decision: Recovery: BIP-39 seed phrase primary; social recovery optional opt-in

**Status:** decided
**Rationale:** Seed phrase (BIP-39, 24 words) deterministically recovers the root secret and therefore all derived keys — no social coordination required, no trusted peers need to be online. Generated at setup, stored offline by the operator. Social recovery (m-of-n trusted peers co-sign a migration assertion) is an optional upgrade for operators willing to accept the coordination dependency in exchange for resilience against seed phrase loss. The two mechanisms are composable: an operator can have both. Social recovery without a seed phrase is the highest-convenience/highest-trust option; seed phrase only is the default self-sovereign path. No recovery mechanism at all is explicitly disallowed — setup wizard requires at minimum the seed phrase be written down before proceeding.

### Decision: CredentialManager tier uses `keyring` crate at launch; explicit Bitwarden SDK is opt-in

**Status:** decided
**Rationale:** The `keyring` crate (Rust, cross-platform) abstracts macOS Keychain, GNOME Keyring/libsecret (SecretService D-Bus), KWallet, and Windows Credential Store from one API — covering Tier B on desktop macOS and Tier C on Linux without bespoke integrations. Bitwarden on Linux stores items via GNOME Keyring, so it is accessible through SecretService without the Bitwarden app running. Explicit Bitwarden SDK / rbw CLI integration is an optional named-item path for operators who want to reference a specific vault item by name. No 1Password, KeePassXC, or other manager integrations at launch — the SecretService abstraction covers them where they support it.

## Research Context

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



### Credential manager backends — Bitwarden, 1Password, system keychain

The user's question is sharp: if YubiKey works by holding an Ed25519 private key in hardware, can a credential manager like Bitwarden that stores passkeys serve the same role?

**Short answer: yes, at a different security tier. The threat model degrades gracefully and explicitly.**

---

**What Bitwarden actually stores when it stores a "passkey"**

A passkey (FIDO2 discoverable credential) is an Ed25519 (or P-256) keypair bound to a relying party ID (rpId). The private key lives inside Bitwarden's encrypted vault (AES-256-CBC + HMAC-SHA256, KDF from master password). It is software-encrypted — accessible to anyone who can unlock the vault.

Bitwarden also stores SSH keys natively (since 2023). The Bitwarden SSH agent exposes stored keys for signing operations without ever writing the raw key material to disk outside the vault. This is the directly applicable feature: store the Styrene root Ed25519 key as a Bitwarden SSH key, use it for signing via the Bitwarden agent.

**What Bitwarden does NOT provide vs. YubiKey:**
- The private key IS in software — someone with your master password can export it
- No physical presence requirement for signing (Bitwarden unlocks vault on login, then signs without re-prompting)
- The key can be synced to any device where Bitwarden is installed

**What Bitwarden DOES provide that YubiKey doesn't:**
- Cross-device portability without a physical token — your identity follows you to any device with Bitwarden installed
- Self-hostable (Vaultwarden) — operator controls the vault server
- Optional hardware 2FA including YubiKey — vault unlock can require YubiKey touch even if the key is software

---

**The security tier ladder — now four explicit levels**

```
Tier A — Hardware HSM (YubiKey PIV/FIDO2, OpenPGP card)
  Private key: non-exportable, hardware-bound
  Physical presence: required for each signing op (touch)
  Cross-device: NO — key stays on the physical token
  Threat: device compromise cannot extract key; token theft = game over without PIN

Tier B — Device HSM (iOS Secure Enclave, Android Keystore StrongBox)
  Private key: non-exportable, device-bound
  Physical presence: biometric or PIN on that specific device
  Cross-device: NO — lost device = lost identity (unless backup exists)
  Threat: device compromise cannot extract key; device destruction = loss

Tier C — Credential Manager (Bitwarden, 1Password, macOS Keychain, GNOME Keyring)
  Private key: software-encrypted, accessible with master credential
  Physical presence: none beyond vault unlock
  Cross-device: YES (synced vault)
  Threat: master password compromise = key compromise; vault server breach mitigated by client-side encryption

Tier D — Encrypted file (~/.styrene/identity/styrene-id.key, argon2id + ChaCha20)
  Private key: software-encrypted on disk
  Physical presence: none
  Cross-device: if you copy the file
  Threat: passphrase compromise or key file exfiltration = game over
```

---

**Why Tier C is correct for most users**

The vast majority of Styrene operators are NOT in the YubiKey threat model. They want:
- Identity that works on their phone, laptop, and desktop
- No physical token to carry or lose
- Reasonable encryption at rest
- Ideally self-hostable

Bitwarden (or Vaultwarden) at Tier C delivers all of this. It's the right default for everyday operators. YubiKey is the right escalation for high-threat users (journalists, activists, military, first responders).

---

**FIDO2 passkeys vs. raw key storage — which Bitwarden feature to use**

Using Bitwarden's passkey (FIDO2) feature for Styrene signing would require constructing FIDO2 assertions for arbitrary data — the signature format wraps the actual data in `authenticatorData || SHA-256(clientDataJSON)` with rpId binding. This is adaptable but adds protocol friction.

**Simpler and cleaner: use Bitwarden as a raw key store, not as a FIDO2 signer.**

- Store the Styrene root secret (32 bytes) or Ed25519 key as a Bitwarden secure note or SSH key item
- `styrened` retrieves it via Bitwarden SDK or `rbw` (unofficial Bitwarden CLI) during startup
- Holds the key in memory for the session, clears on shutdown
- This is exactly what the Bitwarden SSH agent does for SSH keys

This way Styrene does its own Ed25519 signing natively — no FIDO2 protocol wrapper, no rpId binding, no clientDataJSON. Clean.

---

**The IdentitySigner trait (Rust) / interface (Python)**

This entire conversation implies that the identity system needs an abstract signing interface with pluggable backends:

```rust
#[async_trait]
trait IdentitySigner: Send + Sync {
    /// Sign arbitrary data. May prompt for user interaction (PIN, biometric, touch).
    async fn sign(&self, data: &[u8]) -> Result<Signature>;
    /// Public key — used to derive identity_hash and verify signatures.
    fn public_key(&self) -> &Ed25519PublicKey;
    /// Security tier — for UI display and policy enforcement.
    fn tier(&self) -> SignerTier;
}

enum SignerTier { HardwareHsm, DeviceHsm, CredentialManager, EncryptedFile }
```

Implementations:
- `YubikeySigner` — signs via PIV slot, requires touch
- `SecureEnclaveSigner` — iOS/macOS Secure Enclave, biometric prompt
- `BitwardenSigner` — unlocks vault via SDK, reads key, signs in memory
- `FileSigner` — decrypts key file with argon2id passphrase, signs in memory

The daemon displays the tier in `styrened identity` output and optionally enforces minimum tier for sensitive operations (e.g., RBAC admin actions require Tier A or B).

---

**Interaction with the root-secret / HKDF derivation model**

The existing research established that all protocol keys (RNS, Yggdrasil, WireGuard, etc.) are HKDF-derived from a single 32-byte root secret. The IdentitySigner holds that root secret (or derives it from the Ed25519 key). The derivation hierarchy remains unchanged regardless of which backend holds the root:

```
root_secret (held by IdentitySigner backend)
  ├─ Ed25519 signing key (for identity + mesh signatures)
  ├─ HKDF → RNS enc seed + RNS sign seed → RNS Identity
  ├─ HKDF → Yggdrasil Ed25519 key
  ├─ HKDF → WireGuard Curve25519 key
  └─ HKDF → ML-DSA-65 key (encrypted, unlocked by backend)
```

The abstraction boundary is clean: the backend holds the root secret, the IdentitySigner exposes signing and the public key, everything above is pure deterministic derivation.

### Revised four-tier model — platform-native as Tier B, FOSS manager as Tier C

The previous tier model conflated two orthogonal concerns: **key extractability** (hardware vs. software) and **user-facing credential management UX**. The correct taxonomy is UX-first, with hardware backing noted as an implementation detail within each tier.

```
Tier A — Hardware token (YubiKey, OpenPGP card, PIV smartcard)
  UX: physical device, explicit tap/touch per session unlock
  Key extractability: non-exportable (hardware-bound)
  Cross-device: YES (carry the token)
  Who: high-threat operators, journalists, activists, military

Tier B — Platform-native credential system
  iOS/macOS: iCloud Keychain / Apple Passwords app
  Android (stock): Android Credential Manager / Google Password Manager
  UX: integrated with OS — FaceID/TouchID/fingerprint unlock, no extra app
  Key extractability: implementation detail — iCloud Keychain uses Secure Enclave
                      on-device + end-to-end encrypted iCloud sync; Android Keystore
                      with StrongBox on capable devices (Pixel, Galaxy S)
  Cross-device: YES (within ecosystem — iCloud across Apple; Google across Android)
  Who: everyday "normie" users who already use the platform password manager

Tier C — FOSS credential manager (preferred open-source global solution)
  Examples: Bitwarden (self-hosted via Vaultwarden), 1Password, KeePassXC
  UX: separate app, master password or biometric unlock
  Key extractability: software-encrypted, exportable with master credential
  Cross-device: YES (cross-platform, cross-ecosystem — the only option that
                works identically on iOS, Android, Linux, macOS, Windows,
                and de-Googled Android where Tier B is unavailable)
  Who: privacy-conscious users, de-Googled Android users, cross-platform operators

Tier D — Encrypted file (graceful low-tech fallback)
  Storage: ~/.styrene/identity/styrene-id.key (argon2id + ChaCha20-Poly1305)
  UX: passphrase at daemon startup
  Key extractability: software-encrypted, passphrase-required
  Cross-device: manual (copy the file)
  Who: embedded/edge devices (Pi Zero, edge servers), airgapped deployments,
       developers, nodes with no interactive user

---

Hardware backing as implementation detail (not a separate tier):
- Tier B on iOS: iCloud Keychain stores item in Secure Enclave-protected area
- Tier B on Android: Android Credential Manager uses Keystore with StrongBox on capable hardware
- Tier C (Bitwarden): software AES-256 encryption; can optionally require YubiKey for vault unlock (Tier A + C combined)
- These implementation details improve security within the tier but don't change the user-facing category

---

Why Tier C is preferred over Tier B for privacy-first users:
- Tier B on iOS routes through iCloud — Apple observes encrypted metadata (sync timing, device list)
- Tier B on Android requires Google Password Manager — unavailable on de-Googled devices
- Tier C (Bitwarden/Vaultwarden): fully self-hostable, Google-free, cross-platform
- For Styrene's explicit first-class de-Googled Android target: Tier C is the natural credential layer

Hierarchy of recommendations in the onboarding wizard:
1. Have a YubiKey? → Tier A (highest security)
2. No YubiKey, OK with platform ecosystem? → Tier B (Apple Passwords / Android Credential Manager)
3. Privacy-first, cross-platform, or de-Googled Android? → Tier C (Bitwarden/Vaultwarden)
4. Embedded device, airgapped, or none of the above? → Tier D (encrypted file, prompted at setup)
