# Styrene Identity System — Design Spec (extracted)

> Auto-extracted from docs/styrene-identity.md at decide-time.

## Decisions

### Third-party attestations are additive, opt-in, and non-coercive (decided)

A CAC, corporate PKI, or any other X.509-backed identity can sign a binding attestation: "I, holder of this verified credential, assert that this StyreneID public key is mine." That attestation travels with the identity manifest as an optional attestations[] array. Peers who trust the issuing PKI chain can verify it. Peers who don't care ignore it entirely. This is additive — it says nothing about what the peer can do on the network, only provides a verifiable claim about who they are. No Styrene peer is forced to trust any attestation chain. This is explicitly different from CAC-as-hardware-token (using the CAC device for key derivation/protection) vs. CAC-as-attestation (the DoD cert chain vouches for the StyreneID holder). Both use cases are supported and composable: a DoD operator can use their CAC as the hardware token AND publish its attestation.

### IdentitySigner is an abstract trait with four pluggable backend tiers (decided)

Hardware (YubiKey) and software (Bitwarden) credential stores differ in extractability and portability but are both valid identity backends. Rather than privileging one, Styrene defines an IdentitySigner trait (Rust) / interface (Python) with tier-annotated implementations: HardwareHsm (YubiKey PIV/FIDO2), DeviceHsm (Secure Enclave / Android Keystore), CredentialManager (Bitwarden, 1Password, system keychain), EncryptedFile (default). Tier C (CredentialManager) is the right default for most operators — cross-device portability without a physical token, with Vaultwarden available for self-hosted deployments. Tier A (YubiKey) is the escalation path for high-threat users. All tiers feed the same HKDF derivation hierarchy — the backend is only involved in holding the root secret and performing the root Ed25519 signing operation.

### Use Bitwarden as raw key store (SSH key / secure note), not as FIDO2 signer (decided)

FIDO2 passkeys wrap signatures in authenticatorData + clientDataJSON with rpId binding — not suitable for signing arbitrary RNS packets without protocol friction. The cleaner path: store the Styrene root secret or Ed25519 private key as a Bitwarden SSH key item or secure note. styrened retrieves it via Bitwarden SDK or rbw CLI at startup, holds it in memory for the session, clears on shutdown. This is identical to how the Bitwarden SSH agent handles SSH keys. The passkey feature (FIDO2) remains relevant for web-facing authentication (Styrene web UI login), not for mesh identity signing.

### Tier B is platform-native credential system, not raw Secure Enclave — hardware backing is an implementation detail (decided)

The previous framing of Tier B as "Secure Enclave / Android Keystore" conflated hardware backing (an implementation detail) with the user-facing credential management tier. The correct Tier B is iCloud Keychain / Apple Passwords on Apple platforms and Android Credential Manager on stock Android. These happen to use Secure Enclave / Keystore with StrongBox under the hood on capable hardware, but the tier is defined by the UX: OS-integrated, biometric unlock, no additional software. This makes the tier ladder coherent from a user perspective: hardware token → platform native → FOSS manager → encrypted file.

### Hybrid Ed25519+ML-DSA-65 root; Ed25519 travels on-wire, ML-DSA lives in manifest only (decided)

ML-DSA-65's 1952-byte pubkey is incompatible with bandwidth-constrained RNS links (RNode LoRa: ~235 byte packets). Ed25519 is YubiKey-compatible today and sufficient for mesh routing. The hybrid gives harvest-now-decrypt-later protection without breaking existing infrastructure: Ed25519 pubkey (32 bytes) travels in RNS announces as the network identity; ML-DSA-65 pubkey lives only in the full identity manifest fetched on demand. Nodes without StyreneID awareness see a normal RNS peer. Identity manifest fingerprint in app_data is SHA-256(ed25519_pubkey || ml_dsa_pubkey)[:16] — 16 bytes, fits alongside existing fields. Full manifest distributed via /meta or NomadNet /id page, cached locally with TTL, propagated by hubs via LXMF store-and-forward. No gossip protocol needed at launch.

### Per-binding revocation via superseding manifest; root rotation via signed migration assertion (decided)

HKDF is one-way — a compromised derived key (WireGuard, Yggdrasil) does not expose the root secret. Per-binding rotation: publish a new manifest with a replacement binding for that protocol, signed by the root key, with a later issued_at timestamp. Peers accept the newer manifest; old binding is superseded. Root key rotation (root itself compromised) requires a signed migration assertion: {old_styrene_id_sig, new_styrene_id_pubkey, issued_at} signed by BOTH old and new root keys, distributed to trusted peers who then update their resolution tables. This shares a solution path with recovery (Q4).

### Constrained devices (RP2040/ESP32) are operator-managed sub-identities, not root peers (decided)

RP2040/ESP32 cannot store a 4KB ML-DSA key or compute lattice signatures. They remain pure RNS nodes. Operator's StyreneID manifest includes a managed_nodes section: [{rns_identity_hash, device_type, label}], signed by the operator's root. Trust in the embedded node is delegated trust in its operator. No ML-DSA storage or compute required on device. Same trust model as RBAC managed endpoints.

### Recovery: BIP-39 seed phrase primary; social recovery optional opt-in (decided)

Seed phrase (BIP-39, 24 words) deterministically recovers the root secret and therefore all derived keys — no social coordination required, no trusted peers need to be online. Generated at setup, stored offline by the operator. Social recovery (m-of-n trusted peers co-sign a migration assertion) is an optional upgrade for operators willing to accept the coordination dependency in exchange for resilience against seed phrase loss. The two mechanisms are composable: an operator can have both. Social recovery without a seed phrase is the highest-convenience/highest-trust option; seed phrase only is the default self-sovereign path. No recovery mechanism at all is explicitly disallowed — setup wizard requires at minimum the seed phrase be written down before proceeding.

### CredentialManager tier uses `keyring` crate at launch; explicit Bitwarden SDK is opt-in (decided)

The `keyring` crate (Rust, cross-platform) abstracts macOS Keychain, GNOME Keyring/libsecret (SecretService D-Bus), KWallet, and Windows Credential Store from one API — covering Tier B on desktop macOS and Tier C on Linux without bespoke integrations. Bitwarden on Linux stores items via GNOME Keyring, so it is accessible through SecretService without the Bitwarden app running. Explicit Bitwarden SDK / rbw CLI integration is an optional named-item path for operators who want to reference a specific vault item by name. No 1Password, KeePassXC, or other manager integrations at launch — the SecretService abstraction covers them where they support it.

## Research Summary

### Why this is necessary — the hash audit as motivating evidence

The TUI adversarial audit (2026-03-10) found 8 distinct bugs all tracing to the same root: there is no canonical Styrene identity, so every protocol layer carries its own independent hash, and the code has no authoritative place to resolve one to the others. Concretely:

- A single Styrene peer has at minimum THREE independent hash values: RNS identity_hash, RNS destination_hash (per-aspect), LXMF delivery destination_hash. For a node also on Yggdrasil/I2P that adds two more address spaces.
- Th…

### Algorithm selection — ML-KEM vs ML-DSA vs classical

User proposed: ML-KEM (or "KL-MEM") at 512. Clarification and correction:

**ML-KEM (FIPS 203 / CRYSTALS-Kyber)** — Key Encapsulation Mechanism
- Purpose: establishing shared secrets (encryption/key exchange), NOT signing
- Variants: ML-KEM-512 (~AES-128 security), ML-KEM-768 (~AES-192), ML-KEM-1024 (~AES-256)
- YubiKey support: not yet (as of early 2026)
- Use case in Styrene: session key establishment for WireGuard or Yggdrasil handshakes (future)

**ML-DSA (FIPS 204 / CRYSTALS-Dilithium)** — …

### YubiKey integration model — first-class hardware backing

**Current YubiKey 5 capabilities (as of 2026):**
- PIV slots: RSA-2048/4096, ECC P-256/P-384/P-521
- FIDO2: Ed25519 resident keys (firmware 5.2.3+), ed25519-sk with discoverable credentials (5.4+)
- OpenPGP: RSA, ECC P-256/P-384, Ed25519, Cv25519 (for encryption)
- ML-DSA (post-quantum): NOT YET supported in hardware. YubiKey has not shipped PQ PIV firmware as of early 2026.

**Practical YubiKey strategy today:**
- Store Ed25519 signing key in PIV slot or FIDO2 resident key on YubiKey
- This is …

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
| LXMF delivery | Derived from RNS | AUTO | LXMF destination = RNS identity + …

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
This "identity manifest" i…

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
ALL TUI state (contacts, conversations, unread counts, RBAC, cache) is keyed by `styrene_id`, not by any protocol-specific hash. The resolution layer translates any inbound hash to styrene_id and from there to all other protocol addres…

### Relationship to existing RNS identity — adoption, not replacement

**Critical constraint**: Existing Reticulum infrastructure uses RNS identity as its fundamental trust anchor. We cannot replace this — we can only extend it.

**The "adopt downward" model:**
- StyreneID does NOT replace the RNS identity. RNS still uses its own identity for routing.
- StyreneID wraps and binds to the RNS identity.
- For existing nodes: the StyreneID is created and immediately binds to their existing RNS identity_hash.
- For new nodes: optionally derive the RNS key seed from the S…

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

identity_hash = SHA-256(pub_bytes + sig_pub_bytes)[:1…

### Q3 DEEP SECURITY ANALYSIS: fingerprint-in-announce vs full-key



### Credential manager backends — Bitwarden, 1Password, system keychain

The user's question is sharp: if YubiKey works by holding an Ed25519 private key in hardware, can a credential manager like Bitwarden that stores passkeys serve the same role?

**Short answer: yes, at a different security tier. The threat model degrades gracefully and explicitly.**

---

**What Bitwarden actually stores when it stores a "passkey"**

A passkey (FIDO2 discoverable credential) is an Ed25519 (or P-256) keypair bound to a relying party ID (rpId). The private key lives inside Bitwarde…

### Revised four-tier model — platform-native as Tier B, FOSS manager as Tier C

The previous tier model conflated two orthogonal concerns: **key extractability** (hardware vs. software) and **user-facing credential management UX**. The correct taxonomy is UX-first, with hardware backing noted as an implementation detail within each tier.

```
Tier A — Hardware token (YubiKey, OpenPGP card, PIV smartcard)
  UX: physical device, explicit tap/touch per session unlock
  Key extractability: non-exportable (hardware-bound)
  Cross-device: YES (carry the token)
  Who: high-threat …
