---
id: styrene-trust-model
title: Styrene Trust Model — Web of Trust, Attestations, and Sybil Resistance
status: exploring
parent: styrene-identity
open_questions:
  - How should trust accumulate over time across the network — identities, hubs, and content — without a central authority, and how do we resist bot-brigading Sybil attacks on the trust graph?
  - "Content signature UX: how does a NomadNet page indicate it is signed, and what does the TUI show for unverified vs. verified vs. verified-by-trusted-identity pages? Does unsigned content become a first-class warning or just an absence of a badge?"
  - "Hub reputation specifically: beyond \"operated by StyreneID X,\" what makes a hub trustworthy as infrastructure? Uptime history? Signed software manifest? Operator attestations from other hub operators? What is the hub trust display in the TUI?"
  - "PGP ecosystem integration depth: WKD-only (domain-verified email), keyserver lookups (hkps://keys.openpgp.org), or also Keybase-style cross-proofs (Twitter/GitHub/domain)? Each adds verification surface but also external dependency and operational complexity."
  - "ABS tier enforcement: for the hardened \"ABS\" topology, should minimum endorsement thresholds (e.g., 3 trusted-path endorsers required before any content is rendered) be enforced at the network level, or remain operator-configurable policy?"
---

# Styrene Trust Model — Web of Trust, Attestations, and Sybil Resistance

## Overview

> Parent: [Styrene Identity System](styrene-identity.md)
> Spawned from: "How should trust accumulate over time across the network — identities, hubs, and content — without a central authority, and how do we resist bot-brigading Sybil attacks on the trust graph?"

*To be explored.*

## Research

### Three distinct trust surfaces — identities, infrastructure, and content

The trust question spans three surfaces that need separate but composable mechanisms:

**1. Identity trust** — "Is this StyreneID who they claim to be?"
- Anchored by external attestations: PGP key, CAC cert, corporate PKI, etc.
- Accumulated by peer endorsements over time (WoT)
- A journalist signing with a PGP key they've used since 2015 (publicly linked from published work) is providing a strong, independently verifiable attestation. The PGP key itself has its own WoT history.

**2. Infrastructure trust** — "Is this hub/node running honest software operated by who they claim?"
- Hubs include their StyreneID fingerprint + a signed software manifest in announces
- Software is built from source signed by the project's developer key (styrene-lab GitHub key or equivalent)
- "This hub runs styrened v0.15.1, binary matches signed release, operated by StyreneID XYZ"
- Similar to Certificate Transparency: operators make public commitments that can be audited

**3. Content trust** — "Was this NomadNet page actually published by who it claims, and has it been tampered with?"
- Pages include an inline signature header or companion .sig file
- Signature covers: SHA-256(content + destination_hash + timestamp)
- Any node that knows the publisher's StyreneID can verify independently
- A journalist's page on NomadNet can be signed by their StyreneID, attested by their PGP key — the whole chain is verifiable without trusting Styrene at all

These three surfaces share the same underlying primitive (StyreneID signature verification) but serve different purposes. A peer's node can be trusted infrastructure without trusting the person, and a person can be a trusted identity without operating trusted infrastructure.

### PGP attestation path — journalists, activists, and public figures

PGP fits the Styrene model as an attestation source in the same way CAC does — the PGP key holder signs a binding over the StyreneID pubkey, the signature travels in the identity manifest, and any peer who has/trusts the PGP key can independently verify the binding.

**Why PGP is particularly valuable here:**
- PGP keys have verifiable history: a key on keyservers since 2012 with 50 signatures from other journalists is hard to fake
- WKD (Web Key Directory) lets PGP keys be verified against domain-controlled email: `journalist@nytimes.com` → WKD fetch → PGP key → signed StyreneID binding
- Keybase-style cross-proofs work here: "I am @journalist on Twitter, my PGP key is X, my Styrene identity is Y" — each of the three can verify the others
- For sources wanting to contact a journalist: they find the journalist's StyreneID via their PGP fingerprint (which they already have from Signal/SecureDrop/published articles), verify the binding, and reach them over the mesh regardless of internet availability

**The attestation structure (same model as CAC):**
```json
{
  "type": "pgp",
  "pgp_fingerprint": "DEADBEEF...",
  "signed_binding": "<PGP clearsign of: styrene-binding:STYRENE_ID_FINGERPRINT:TIMESTAMP>",
  "wkd_url": "https://nytimes.com/.well-known/openpgpkey/...",  // optional, for auto-fetch
  "keyserver_url": "hkps://keys.openpgp.org/...",              // optional
  "timestamp": 1234567890
}
```

**Verification flow:**
1. Peer sees StyreneID manifest with PGP attestation
2. Peer already has journalist's PGP key (from prior exchange, keyserver, WKD) OR fetches it via the optional URL hints
3. Peer verifies: PGP sig over the `styrene-binding:FINGERPRINT:TIMESTAMP` string is valid
4. Peer verifies: SHA-256(styrene_pubkey) == FINGERPRINT in the binding
5. Result: the holder of that PGP key has explicitly bound themselves to this StyreneID. The trust level assigned to the PGP identity transfers as attestation weight.

**What PGP attestation does NOT do:**
- Does not automatically grant any RBAC capability (you still explicitly assign roles)
- Does not bypass the Sybil problem (a person can have multiple PGP keys)
- Does not guarantee the key hasn't been compromised (only that whoever holds the PGP key signed the binding — same as PGP itself)

### Web-of-trust accumulation — peer endorsements and the brigading problem

**The core WoT mechanic:**
Any StyreneID holder can issue a signed endorsement of another StyreneID: "I, StyreneID A, have verified StyreneID B's identity to my satisfaction." Endorsements accumulate in the recipient's manifest. Peers receiving the manifest can check: do any of my trusted contacts also endorse this peer?

**This is where the Sybil/brigading problem lives:**

### Attack: Bot farm endorsement

Attacker creates 100 fake StyreneIDs. They all endorse each other. The attacker's "real" identity now has 100 endorsements. This looks like a highly trusted identity to any newcomer.

### Why classic PGP WoT fails here:

PGP's trust model requires you to explicitly assign trust to signers before their signatures matter. But on a new mesh, you may not know anyone yet — you have to bootstrap from zero, which means endorsement counts from strangers are meaningless for a newcomer.

### Mitigations that actually work:

**1. Transitive trust with depth attenuation (PGP model, hardened)**
- Trust from a peer you've explicitly trusted (depth 1) = full credit
- Trust derived through one hop from someone you trust (depth 2) = partial credit (~50%)
- Two hops (depth 3) = ~25%. Three hops = ~12.5%. Beyond 3 hops = zero.
- Bot farms are effective only if the attacker can compromise a node in YOUR trusted set. If they're all strangers to you, their endorsements carry zero weight at depth 0.
- Key property: **trust doesn't flow uphill** — endorsements from untrusted strangers never bootstrap into trust without you explicitly trusting someone in that chain first.

**2. Attestation weight asymmetry**
Endorsements are not equal. A StyreneID with:
- A PGP key on keyservers since 2008 with 200 cross-signatures
- A CAC attestation
- WKD-verified email at a known organization
...carries fundamentally more endorsement weight than a brand-new StyreneID with no external attestations. 
Weight formula (sketch): `endorsement_weight = base_weight × attestation_multiplier × time_decay_of_endorser`

**3. Endorsement cost (rate limiting)**
A StyreneID can issue at most N endorsements per rolling window (e.g., 10/day, 50/month). This is enforced locally by peers who check timestamps and reject excess endorsements. Bot farms need to either:
- Create many identities (Sybil), each endorsing once — caught by the attenuation model
- Use a small set of high-value identities and spam endorsements — caught by rate limiting

**4. Reciprocity suspicion signal**
If a cluster of identities all endorse each other and have no endorsements from outside the cluster, and have no external attestations, peers can flag this pattern locally. Not a hard block — just a signal. A tight mutual-endorsement cluster with no external connections is a Sybil red flag.

**5. Local primacy — you are always the ultimate arbiter**
Your explicit trust assignments always override any computed/transitive trust. If you've explicitly set a peer to BLOCKED, no amount of endorsements changes that. The WoT layer only affects peers you haven't explicitly assigned. This is the fundamental property that prevents any external party from overriding your trust decisions.

**6. The "cold start" problem — mesh onboarding**
A new peer joining a mesh for the first time has no trust relationships. Two paths:
- **Manual bootstrap**: operator explicitly assigns PEER to someone they've verified out-of-band (Signal, in-person, etc.). Trust graph grows from that seed.
- **Hub-mediated introduction**: the hub operator (who you've verified) endorses new members they've vetted. The hub acts as a trust anchor for new members, not as a central authority — you're trusting the hub operator's judgment, which you've independently established.

**7. What WoT fundamentally cannot solve:**
A determined attacker who has compromised a node in your trusted set can use that node to endorse malicious identities. This is not a WoT problem — it's a key compromise problem. The answer is the same as in PGP: key hygiene, hardware backing (YubiKey/CAC), and monitoring for suspicious signing patterns from trusted nodes.

### Relationship to existing RBAC — WoT as the layer beneath explicit assignment

The existing RBAC system (BLOCKED / PEER / OPERATOR / ADMIN) is already the right model for explicit trust. The WoT layer sits BENEATH it — it only influences treatment of peers for whom you have no explicit assignment yet.

**Current RBAC as local trust:**
- BLOCKED = explicit reject (always wins, WoT cannot override)
- UNKNOWN = no assignment (default for strangers)
- PEER = I trust this identity in my mesh
- OPERATOR = I trust this identity with management capability
- ADMIN = full trust

**WoT influence on UNKNOWN peers:**
When you encounter a peer with UNKNOWN status (no explicit assignment), the WoT layer computes a derived trust hint:
- 0 endorsers from your trusted set → treat as stranger (current behavior, unchanged)
- 1+ marginal endorsers → auto-elevate to PEER-equivalent for content display (unread preview, page rendering) but NOT for capabilities (no RBAC advancement without explicit assignment)
- 2+ full endorsers → prompt operator: "3 of your trusted contacts endorse this peer. Assign PEER?"
- Any external attestation from a verified source → show badge in TUI, but still no automatic RBAC

**The key design constraint: WoT influences display and discovery, never RBAC capabilities.**
Transitive trust can show you a "probably trustworthy" signal, but actually granting message relay, exec, datalink, etc. ALWAYS requires an explicit operator decision. This prevents automated privilege escalation through endorsement chains.

**RBAC tiers map to WoT tiers:**
```
WoT "verified"    → suggests PEER assignment (operator confirms)
WoT "attested"    → suggests PEER with display of attestation source
WoT "endorsed"    → suggests PEER with chain shown (X endorsed by Y whom you trust)
WoT "unknown"     → no suggestion, treat as stranger
```

**This also means:**
The existing `relay.request`, `terminal`, `exec` etc. capabilities are NEVER affected by WoT. WoT is about knowing who you're talking to, not about what they're allowed to do. Those are orthogonal decisions that remain entirely in the operator's hands.

### Guha et al. 2004 — formal model and empirical findings mapped to Styrene

Reference: R. Guha, R. Kumar, P. Raghavan, A. Tomkins. "Propagation of Trust and Distrust." WWW 2004, pp. 403–412. Dataset: Epinions.com, 131,829 nodes, 841,372 labeled trust/distrust edges.

### 2024 academic landscape — what has changed since Guha 2004



### Nostr WoT — most analogous deployed system to Styrene trust design

Nostr (launched 2022, >100M pubkeys) is the closest existing deployed system to what Styrene needs. It's a decentralized social network built on public key cryptography, no central authority, and event propagation — directly analogous to LXMF propagation on the mesh.

**How Nostr WoT works today:**
- NIP-51 "follow lists": a user publishes a signed list of pubkeys they follow (positive endorsement)
- trust.nostr.band: builds a directed graph from follow events, assigns initial weights to NIP-05 verified accounts, propagates via EigenTrust-like power iteration
- nostr-wot browser extension: queries a trust oracle to show trust distance between any two pubkeys
- Trust scoring stops at 3 hops from your seed (matches the Guha 2004 γ=0.5 × 3-hop finding that 4+ hops is noise)

**Key differences from Styrene:**
- Nostr has no distrust signal in the protocol (no NIP for "block" that others can see) — this is intentional (privacy) but means no signed-network behavior
- Nostr relies on internet relays for propagation; Styrene must work on mesh/LoRa
- Nostr's follow lists are fully public — exactly PGP's mistake at scale. Styrene's endorsements should be opt-in public or DP-private.

**What to adopt from Nostr WoT:**
1. The 3-hop cutoff (independently derived from γ=0.5, validated by Nostr deployment)
2. NIP-05-style domain verification as an attestation anchor (maps to WKD for PGP attestations)
3. The oracle pattern: heavy trust computation runs on a capable node (hub), results cached and served to lightweight nodes (LoRa edges). Not all mesh nodes can run full EigenTrust.

**Active implementations in the Nostr ecosystem:**
- `nostr-wot/nostr-wot-extension` (TypeScript) — browser extension + oracle
- `Karma3Labs/farcaster-openrank-neynar` — Python, Farcaster graph with EigenTrust
- `wds4/DCoSL` — minimalist decentralized WoT protocol in spirit of Nostr/Bitcoin

**The oracle pattern is critical for Styrene's constrained devices:**
RP2040/ESP32 "lite" nodes cannot run EigenTrust or Appleseed locally. The design should separate:
- **Full node** (Styrene daemon on Pi/desktop): runs local Appleseed computation, caches results, serves trust scores over /meta to requesters
- **Lite node** (RP2040/ESP32): requests trust scores from a trusted full node via /meta or /info. Delegates WoT computation upstream.
This maps exactly to how Nostr clients delegate to relays for heavy computation.

### Implementation inventory — Rust and Python candidates for Styrene



### Revised algorithm architecture — three-layer trust engine

Combining the academic landscape, implementation inventory, and Styrene-specific constraints (offline mesh, constrained nodes, no global coordination), the right architecture is three composable layers:

### Upstream validation corrections and early warnings — post-research audit



## Decisions

### Decision: WLC propagation with γ=0.5 depth attenuation and combined atomic operators

**Status:** decided
**Rationale:** Empirically grounded in Guha et al. 2004. Trust score uses weighted linear combination of four atomic propagation operators: direct (α₁=0.4), co-citation (α₂=0.4), transpose (α₃=0.1), trust coupling (α₄=0.1). Per-hop discount γ=0.5 (trust halves at each WoT hop). Majority rounding: a peer's trust is read from the majority label of their local trusted neighborhood, not a global statistic. This yields depth 1=100%, depth 2=50%, depth 3=25%, depth 4+=≤12.5% — beyond 4 hops the signal is noise. Co-citation weight at 0.4 (equal to direct) reflects the finding that multiple independent endorsers are as informative as a direct trust relationship.

### Decision: Continuous Appleseed score (not binary tiers), discretized at RBAC boundary only

**Status:** decided
**Rationale:** Binary tiers (PGP: unknown/marginal/full) are too coarse and don't leverage the information in the endorsement graph. Continuous 0–1 Appleseed scores are the right internal representation. They naturally encode depth attenuation and co-citation weight without any threshold engineering. Discretization happens only at the RBAC boundary: the TUI displays the continuous score and suggests tier assignments, but the operator maps to RBAC roles explicitly. Threshold consensus (m-of-n) is still valid as a UI heuristic — "3 of your OPERATOR contacts endorse this peer" is a useful prompt — but it's not how the score is computed internally. Grounded in Guha 2004 (co-citation weight = 0.4) and Appleseed (spreading activation is inherently continuous).

### Decision: Endorsements are encrypted-in-transit, operator-controlled publication, DP aggregate

**Status:** decided
**Rationale:** Three-level privacy model that avoids PGP's public-graph mistake while still enabling useful trust propagation: (1) Individual endorsement edges are only revealed when a peer explicitly fetches your manifest — not broadcast, not gossiped. (2) Operators choose whether to include endorsements in their public manifest at all (default: included, opt-out to suppress). (3) Aggregate trust scores published by hubs use differential privacy noise injection (ITCS 2025 framework: (ε,δ,G)-TGDP) to prevent social graph inference from the published scores. (4) Future Phase 3: ZK trust proofs (zk-eigentrust pattern) allow proving "score ≥ threshold" without revealing graph structure. This gives a mathematically principled spectrum from "fully private" to "DP-private" to "fully public" rather than a binary choice.

### Decision: EigenTrust Layer 3 pre-trusted vector seeded from OPERATOR+ RBAC roster

**Status:** decided
**Rationale:** EigenTrust power iteration requires a pre-trusted peer seed vector. Without it the algorithm defaults to uniform trust — meaningless. For hub-computed Layer 3, the pre-trusted vector is: resolve_role(h) >= Role.OPERATOR → weight=1.0, all others → 0.0. This maps directly onto the existing RBAC system, produces personalized hub scores, and is only changed by explicit operator roster mutation. Grounded in the original Kamvar 2003 paper's security analysis: pre-trusted set must be small, well-known, and non-compromisable. The OPERATOR+ roster satisfies all three properties by design.

### Decision: CTAP2 canonical CBOR for all signed manifest and endorsement structures

**Status:** decided
**Rationale:** RFC 8949 §4.2 defines multiple incompatible canonical forms (CDE, CTAP2 canonical, old canonical). COSE signatures are canonical-form-sensitive — a signature computed over CTAP2-canonical CBOR will not verify against a CDE-encoded payload. Since StyreneID manifest signing must be compatible with YubiKey PIV and hardware-backed FIDO2 keys, which already implement CTAP2 canonical CBOR, we declare CTAP2 canonical as the wire protocol constant for all signed structures. All verifiers must normalize to CTAP2 canonical before signature verification. This is documented in the wire protocol spec as a constant, not left implementation-defined.

### Decision: f32 for all daemon and Pi-class targets; u16 fixed-point for bare-metal MCU only

**Status:** decided
**Rationale:** Pi Zero 2W is Cortex-A53 (ARMv8-A) with hardware VFPv4 + NEON — f32/f64 arithmetic is hardware-accelerated. Only the RP2040 (Cortex-M0+, thumbv6m-none-eabi) genuinely lacks an FPU and requires software float emulation (~10× slower). The trust score type is therefore f32 for all Rust daemon builds targeting Linux/aarch64/armhf. A u16 fixed-point representation (0–65535 = 0.0–1.0) is used only for the bare-metal MCU port where the target triple is thumbv6m-none-eabi or similar no-FPU targets. The γ=0.5 attenuation step is a right-shift in fixed-point, which is free on any processor including Cortex-M0+.

### Decision: TrustEngineConfig — configurable weights with named profiles; SybilRank labeled candidate not scheduled

**Status:** decided
**Rationale:** Guha α=(0.4, 0.4, 0.1, 0.1) and γ=0.5 are empirically grounded on Epinions (consumer reviews, large social network). No validation exists for operational mesh topology. Weights are made configurable via TrustEngineConfig { alpha: [f32; 4], gamma: f32, max_depth: u8, base_energy: f32 }. Two named profiles ship by default: (1) "guha" — α=(0.4, 0.4, 0.1, 0.1), empirically grounded baseline; (2) "mesh-operational" — α=(0.5, 0.2, 0.2, 0.1), higher direct+transpose, lower co-citation, more appropriate for operational trust relationships. Appleseed energy budget derived at compute time as log₂(|reachable_nodes|) × base_energy to scale with mesh size. SybilRank (Phase 2 Layer 2) labeled "candidate" not "scheduled" — homophily assumption unvalidated for small operational mesh graphs. Phase 1 Sybil pre-filter is the reciprocity heuristic only. SybilHP (MDPI 2023) is the better SybilRank variant if Phase 2 proceeds to random-walk detection.

## Open Questions

- How should trust accumulate over time across the network — identities, hubs, and content — without a central authority, and how do we resist bot-brigading Sybil attacks on the trust graph?
- Content signature UX: how does a NomadNet page indicate it is signed, and what does the TUI show for unverified vs. verified vs. verified-by-trusted-identity pages? Does unsigned content become a first-class warning or just an absence of a badge?
- Hub reputation specifically: beyond "operated by StyreneID X," what makes a hub trustworthy as infrastructure? Uptime history? Signed software manifest? Operator attestations from other hub operators? What is the hub trust display in the TUI?
- PGP ecosystem integration depth: WKD-only (domain-verified email), keyserver lookups (hkps://keys.openpgp.org), or also Keybase-style cross-proofs (Twitter/GitHub/domain)? Each adds verification surface but also external dependency and operational complexity.
- ABS tier enforcement: for the hardened "ABS" topology, should minimum endorsement thresholds (e.g., 3 trusted-path endorsers required before any content is rendered) be enforced at the network level, or remain operator-configurable policy?

## Factual corrections

### Correction 1: Pi Zero 2W CPU is Cortex-A53, NOT ARMv6
The original analysis said "Pi Zero 2W (ARMv6, soft-float)" — this was wrong. The Pi Zero 2W uses the BCM2710A1 (4× Cortex-A53, ARMv8-A, 64-bit, hardware VFPv4 + NEON). Only the **original Pi Zero** (BCM2835, ARM1176JZF-S) was ARMv6 with unreliable soft-float. The Pi Zero 2W has full hardware floating point — f32/f64 is not a performance concern.

The u16 fixed-point recommendation stands only for **RP2040** (dual Cortex-M0+, ARMv6-M, genuinely no FPU — Rust target: `thumbv6m-none-eabi`). The daemon and all Pi-class edge targets should use f32.

Revised rule:
- Pi Zero 2W, Pi 4B, desktops, any Linux target: `f32` — hardware VFP present
- RP2040, bare-metal MCU targets (`thumbv6m-none-eabi`): `u16` fixed-point (0–65535 = 0.0–1.0)

### Correction 2: CBOR deterministic encoding requires explicit canonical form declaration
RFC 8949 §4.2 defines multiple partially-incompatible canonical forms. The ImperialViolet (Adam Langley) analysis shows:
- **Old Canonical CBOR** — two-step map key ordering (deprecated)
- **CDE (Core Deterministic Encoding)** — one-step ordering, RFC 8949 §4.2 as updated
- **CTAP2 canonical CBOR** — used by FIDO2 and YubiKey security keys; three-step ordering; explicitly different from CDE

A COSE signature computed over CTAP2-canonical CBOR will NOT verify against the same payload re-encoded in CDE format. Since StyreneID manifest signing must be compatible with YubiKey PIV and hardware-backed keys, the canonical form MUST be declared explicitly.

**Decision required:** Use CTAP2 canonical CBOR for all signed manifest and endorsement structures. Rationale: YubiKey already implements it, FIDO2 spec uses it, and it's stable. This means all Styrene manifest signing is CTAP2-canonical. Document this as a wire protocol constant.

### Correction 3: "3-hop cutoff empirically validated by Nostr" is overstated
The 3-hop practical limit in Nostr WoT is not an independent empirical social science finding — it's a practical consequence of the γ=0.5 per-hop attenuation (depth 4 = 6.25% of full trust → noise). The Nostr NIP-XX proposal says "1 hop SHOULD yield 1.0, implementations SHOULD factor in hop distance" without mandating a hard cutoff. The 3-hop limit is a reasonable engineering choice, not a validated universal constant.

Reframe in design docs: "3 hops is the practical cutoff because γ=0.5 attenuation renders depth 4 (≤6.25%) below the noise threshold of the scoring system."

## Early warnings from upstream research

### Warning 1: EigenTrust pre-trusted peer bootstrapping gap (CRITICAL)
EigenTrust (Kamvar 2003) requires a pre-trusted peer vector for power iteration. Without it, the algorithm defaults to uniform trust across all nodes — equivalent to random scoring. The paper's security guarantees hold only when the pre-trusted set is not compromised.

In the current design, Layer 3 EigenTrust runs on hubs with no specification of who the pre-trusted peers are.

**Resolution (must be explicit):** Hub's EigenTrust pre-trusted vector = peers with `resolve_role(h) >= Role.OPERATOR` in the hub's RBAC roster. This maps cleanly onto the existing system, produces personalized hub scores, and ensures the pre-trusted set only changes via explicit operator action. Document this as a required binding in the design.

### Warning 2: SybilRank homophily assumption unvalidated for operational mesh networks
All random-walk Sybil detection (SybilRank, SybilGuard, SybilLimit) assumes **social graph homophily**: honest nodes cluster together and attack edges between the Sybil region and honest region are sparse. Validated on Tuenti (11M users, 1.4B social links) — a very different scale and topology from a Styrene mesh.

Problems for Styrene:
- Mesh network endorsement graphs are driven by operational trust (who you work with), not social affinity. Homophily properties may differ significantly from social networks.
- Small networks (<10K nodes) may not exhibit the mixing time properties that SybilRank's convergence proofs require. The log₂|V| step count is a theoretical bound that needs tuning for small networks.
- SybilHP (MDPI 2023) extends SybilRank for directed networks with adaptive homophily prediction — more appropriate if SybilRank is pursued.
- An attacker routing Sybil nodes through a hub in your OPERATOR+ roster creates attack edges inside your trusted region — defeating homophily at the trust boundary.

**Resolution:** Label SybilRank as a "Phase 2 candidate, unvalidated for operational mesh topology." The reciprocity heuristic (hermetically-sealed endorsement cluster detection from locally-fetched manifests) is more appropriate for Phase 1 because it requires no homophily assumption.

### Warning 3: Appleseed energy budget is a sensitive parameter
Appleseed convergence depends on the energy budget parameter. The cblgh reference implementation uses `e=0.85` (tuned for Epinions-scale graphs). For small meshes (50–500 nodes), a fixed budget will either be too sparse (misses peers beyond hop 2) or too generous (cycles accumulate beyond convergence).

**Resolution:** Derive energy budget at compute time: `energy = log₂(|reachable_nodes|) × base_energy`. This scales with mesh size naturally. Add `base_energy` to `TrustEngineConfig` (default: 0.85, range: 0.5–0.98).

### Warning 4: petgraph requires explicit concurrency design in async context
petgraph graphs are `&mut` for all writes — no interior mutability. In a Tokio async daemon, the trust graph needs `Arc<tokio::sync::RwLock<DiGraph<...>>>` for safe concurrent read/write access. Use `tokio::sync::RwLock` (async-aware), NOT `std::sync::RwLock` (blocks the thread pool). The read path (score lookups) should only hold the RwLock for microseconds; the write path (integrating a new manifest) holds it for the full graph update — design accordingly to avoid starvation.

Alternative: dedicated trust engine thread with `mpsc` channel for manifest updates and `oneshot` for score queries. Cleaner isolation but adds latency to score queries.

### Warning 5: Guha α weights not validated outside Epinions — mesh-operational profile needed
Post-2010 papers consistently cite Guha WLC as a baseline but note the coefficients are specific to consumer review networks. For operational mesh networks, transpose (mutual trust, currently α₃=0.1) is likely a stronger signal than in consumer reviews. Making α configurable is confirmed correct.

Add a second named profile alongside Guha defaults:
- **guha** (default): α=(0.4, 0.4, 0.1, 0.1) — Epinions-grounded
- **mesh-operational**: α=(0.5, 0.2, 0.2, 0.1) — higher direct + transpose, lower co-citation

Operators can select via `TrustEngineConfig.profile` or override individual weights.

### Warning 6: rs-eigentrust is cloud-batch, not daemon-native
Karma3Labs/rs-eigentrust is designed for batch computation on large social graphs (Farcaster, Lens). It's production-quality and handles distrust credentials via signed CAIP attestations. However, it's not designed for continuous operation inside a mesh daemon.

**Adaptation required for Styrene:** Wrap in a background `tokio::task` that recomputes on a schedule (e.g., every 15 minutes or on significant manifest updates). Expose scores via a cached read path `(StyreneId → EigenTrustScore, computed_at: Instant)`. The computation is inherently batch — that's fine, just design the cache invalidation correctly.

## New candidate to track: GrapeRank

The Nostr community developed GrapeRank (`github.com/Pretty-Good-Freedom-Tech/graperank-nodejs`) as a configurable algorithm handling follows, mutes, and reports (positive + negative signals) in a single scoring pass. Currently JavaScript/Node.js but the algorithm is straightforward. If Appleseed + one-step distrust filter proves insufficient for integrated negative signal handling, GrapeRank is the Phase 2 alternative to evaluate before building custom. Watch the repo for protocol formalization.

## Layer 1: Local trust (Appleseed) — per-node, offline, source-centric

**Algorithm**: Appleseed (Ziegler & Lausen 2005) with Guha WLC atomic operators

Every full Styrene node computes trust from its own perspective. Starting from the operator's explicitly trusted peers as seeds, energy spreads through the endorsement graph with decay γ=0.5 per hop. The result is a local ranking of all reachable peers by trust score from this node's perspective.

- Input: explicit trust assignments (T matrix entries from your RBAC) + endorsement edges from fetched manifests
- Output: `{styrene_id → trust_score ∈ [0, 1.0]}` for all reachable peers
- Convergence: ~3-5 iterations for typical mesh sizes (<1000 nodes)
- Incremental update: adding a new endorsement edge is local to the affected subtree (no full recompute)
- Works completely offline — no coordination with other nodes needed

Appleseed replaces the flat "PEER / not PEER" binary with a continuous score that naturally reflects depth attenuation and co-citation (Guha α weights). The score informs the TUI display but still requires explicit operator action to grant RBAC capabilities.

## Layer 2: Sybil pre-filter (SybilRank) — background, gossip-assisted

**Algorithm**: SybilRank (Cao et al. 2012) — short random walk at log2(|V|) steps

Runs as a background service on full nodes. Gossips the locally-visible endorsement graph with trusted peers to build a partial view of the global trust topology. Runs power iteration to assign a Sybil-suspicion score to each known StyreneID.

- Input: the combined endorsement graph from all fetched manifests
- Output: `{styrene_id → sybil_suspicion_score ∈ [0, 1.0]}`
- Sybil clusters have high suspicion score (low trust propagation from seed); honest nodes have low suspicion
- Feeds a "Sybil warning" signal in the TUI — not an automatic block, just a flag
- **Gossip constraint**: Only shares graph edges from peers you've explicitly fetched (not automatic broadcast). Prevents the pre-filter from becoming a surveillance mechanism.

This is the mathematical grounding for the "reciprocity suspicion" signal: a hermetically-sealed mutual endorsement cluster will have high suspicion score because it's not reachable from the honest seed set.

## Layer 3: Global hub/content reputation (EigenTrust) — hub-computed, served to lite nodes

**Algorithm**: EigenTrust (Kamvar 2003) with trust-only B=T (Guha recommendation for global scoring)

Runs only on full nodes acting as hubs (or delegated to a trusted hub). Computes the global EigenTrust score across the visible endorsement graph. These scores represent the recursive endorsement the entire visible network has in each peer.

- Input: the full endorsement graph from hub's perspective
- Output: `{styrene_id → eigentrust_score ∈ [0, 1.0]}` — publishable as a signed "reputation snapshot"
- Serves lite nodes (/meta) that can't run local computation
- Updates on a schedule (hourly/daily), not real-time
- Hub signs the snapshot with its StyreneID → recipients can verify + assign the hub's trust weight to the scores

## Interaction between layers

```
Explicit RBAC assignment (operator) → always wins
     ↓
Appleseed local score (Layer 1)  → informs TUI display, WoT tier suggestion
     ↓  filtered by  ↓
SybilRank pre-filter (Layer 2)  → suppresses endorsements from Sybil-suspicious peers
     ↓  bootstraps lite nodes  ↓
EigenTrust global score (Layer 3) → serves constrained devices, hub reputation display
```

## The one-step distrust filter (Guha) sits at Layer 1

When computing Appleseed from a source node, any endorsement edge *from* a BLOCKED peer is discounted by one step before spreading activation continues. This implements Guha's "one-step distrust" finding at the right architectural layer — it's applied during local trust computation, not as a separate propagation phase.

## Privacy: endorsement edges are encrypted in transit, DP in aggregate

- Individual endorsement edges are only revealed to explicit fetch recipients (not broadcast)
- Aggregate trust scores published by hubs can have DP noise injection (ITCS 2025 framework) to prevent social graph inference from the scores
- ZK trust proofs (future, Phase 3) allow peers to prove "score ≥ threshold" without revealing endorser identities

## Rust

### `fluencelabs/trust-graph` — certificate chains and revocation
- crates.io: `trust-graph`, `trust-graph-distro`
- docs.rs: https://docs.rs/trust-graph
- **What it does**: Stores and manages certificate chains for a trust graph. Has Auth (who gives trust), Certificate (chain from self-signed root), and Revocation primitives. Does NOT implement weighted propagation — just the storage and verification layer.
- **What it's missing**: No WLC propagation, no Appleseed, no EigenTrust. Just the cryptographic substrate.
- **Usefulness for Styrene**: High. This is exactly the certificate chain management we need for the StyreneID manifest and attestation storage layer. We extend on top of it.
- **License**: Apache-2.0

### `Karma3Labs/rs-eigentrust` — production EigenTrust in Rust  
- GitHub: https://github.com/Karma3Labs/rs-eigentrust
- **What it does**: Models a graph of users + snaps, runs EigenTrust from signed attestation credentials, produces trust scores. Production quality — used in Farcaster and Lens social graph ranking (OpenRank protocol). Has both power-iteration and matrix-inversion variants.
- **What it's missing**: No distrust handling, no Appleseed local metric, no Sybil detection.
- **Usefulness for Styrene**: High for hub-level global reputation scoring. Can be adapted to run Appleseed-style local trust by using a single-node pre-trust seed vector.
- **License**: MIT

### `hypnagonia/eigentrust-rust` — lightweight Rust EigenTrust
- GitHub: https://github.com/hypnagonia/eigentrust-rust
- **What it does**: Simpler Rust EigenTrust, designed for decentralized networks. Runs natively and in WASM.
- **Usefulness for Styrene**: Lower resource footprint than rs-eigentrust. WASM target could run on the Styrene edge web bridge. 
- **License**: check repo

### `privacy-ethereum/zk-eigentrust` — ZK-proof-backed EigenTrust
- GitHub: https://github.com/privacy-ethereum/zk-eigentrust  
- **What it does**: EigenTrust inside Halo2 ZK circuits. Proves "score ≥ threshold" without revealing graph structure.
- **Usefulness for Styrene**: The privacy layer for the future. Not for initial implementation (Halo2 proof generation is heavy), but the architecture shows how to add ZK privacy later without changing the trust model.
- **License**: check repo

### `petgraph` — graph data structures in Rust
- crates.io: `petgraph`
- **What it does**: Directed/undirected graphs with edge weights, algorithms (Dijkstra, BFS, DFS, Bellman-Ford, Tarjan SCCs). The foundation for building custom trust propagation.
- **Usefulness for Styrene**: The graph storage primitive for implementing Appleseed or custom WLC propagation. Well-maintained (2024 active), widely used.
- **License**: MIT/Apache-2.0

---

## Python

### `Karma3Labs/openrank-sdk` — Python EigenTrust API
- GitHub: https://github.com/Karma3Labs/openrank-sdk
- **What it does**: Python SDK. `run_eigentrust_from_csv(localtrust_file, pretrust_file)` → list of `Score` objects. Wraps the OpenRank compute API.
- **Usefulness for Styrene**: Best for prototyping and experimentation. Can run EigenTrust on synthetic trust graphs before committing to a Rust implementation. Cloud-hosted compute though — not suitable for offline mesh operation.
- **License**: check repo

### `cblgh/appleseed-metric` — Appleseed reference implementation
- GitHub: https://github.com/cblgh/appleseed-metric  
- Language: **JavaScript/Node.js** (not Python — despite being listed in Python searches)
- **What it does**: Clean ~100-line Appleseed implementation. Source node, trust assignments (src/dst/weight triples), energy budget, attenuation factor, convergence threshold. Returns ranked trust scores from source's perspective.
- **Usefulness for Styrene**: The reference to port to Rust. Very readable, well-documented. Porting to Python (networkx-based) would be trivial. Porting to Rust (petgraph-based) is the right end goal.
- **License**: MIT

### Tribler trust graph (`Tribler/tribler`) — Python, production deployed
- GitHub: https://github.com/Tribler/tribler (see `src/tribler/core/components/bandwidth_accounting/`)
- **What it does**: Real production Sybil-resistant trust system in a deployed P2P BitTorrent client. Uses random walk-based trust ranking. ~6-9 seconds for full recompute on their network.
- **Usefulness for Styrene**: Shows what a production Python trust system looks like. Architecture is instructive — incremental update issue (#2805) is documented. The incremental update problem is relevant to Styrene (trust scores should update efficiently when a new endorsement arrives, not requiring full recompute).
- **License**: LGPL-2.1 (check before incorporating code directly)

### `thibaultlaugel/sybilguard` — Python SybilGuard reference
- GitHub: https://github.com/thibaultlaugel/sybilguard
- **What it does**: Python implementation of SybilGuard random walk algorithm. Reference/research quality.
- **Usefulness for Styrene**: For prototyping the Sybil pre-filter layer before computing Appleseed trust.
- **License**: check repo

---

## Recommended stack for Styrene

**Phase 1 — Prototype (Python)**:
- `networkx` directed graph for the endorsement store
- Port `appleseed-metric` JS → Python for local trust computation
- `openrank-sdk` for verifying EigenTrust results match expected scores on synthetic data

**Phase 2 — Production (Rust)**:
- `petgraph` as the graph substrate
- `fluencelabs/trust-graph` for certificate chain storage (modify to add weighted edges)
- Custom Appleseed propagation built on petgraph (port from JS reference)
- `rs-eigentrust` or `hypnagonia/eigentrust-rust` for hub global scoring
- SybilRank pre-filter (power iteration, log2(|V|) steps) built on petgraph

**Phase 3 — Privacy (Rust)**:
- ZK proof layer from `zk-eigentrust` patterns for selective disclosure of trust proofs
- OR: Differential Privacy noise injection from ITCS 2025 paper for aggregate trust score publication

## What the field has produced in 20 years

Guha 2004 is still the canonical empirical baseline for trust+distrust propagation in signed graphs. It has not been superseded — it has been refined, extended, and validated on larger datasets. The major threads since then:

---

### 1. Appleseed — local group trust via spreading activation (Ziegler & Lausen, 2005)

**Paper**: "Propagation Models for Trust and Distrust in Social Networks", Information Systems Frontiers, 2005.

The key alternative to the global matrix approach. Rather than computing a global F matrix (expensive, requires knowing the full graph), Appleseed computes trust from a *specific source node's perspective*. It models trust as "energy" spreading through a graph from the source:

- Each edge (u, v) with weight w transfers `energy × w × (1 - decay)` from u to v
- Energy dissipates at each hop (decay factor equivalent to γ in Guha)
- Nodes not reachable from source stay at zero — which is the right semantics for decentralized systems

**Why this matters for Styrene**: Appleseed is local. You don't need to know the whole graph to compute your local trust view. A Styrene node computes trust from its own perspective — exactly Appleseed's model. No global consensus needed, works offline.

**Implementation**: `cblgh/appleseed-metric` on GitHub (JavaScript/Node.js, clean reference implementation). Python equivalent would be a ~50-line networkx implementation.

---

### 2. EigenTrust — global P2P reputation via eigenvector (Kamvar, Schlosser, Garcia-Molina, 2003)

**Paper**: "The EigenTrust Algorithm for Reputation Management in P2P Networks", WWW 2003. Pre-dates Guha.

Computes a global trust score for every node in the network by iterating toward the principal eigenvector of the normalized trust matrix. Analogous to PageRank but for trust. Converges to a score that reflects recursive endorsement.

**Why this matters for Styrene**: Ideal for *hub* and *content* trust where a global score makes sense. A hub's global EigenTrust score reflects the recursive trust the whole network has in it. Implemented as power iteration — efficient even on large graphs.

**Key limitation**: Doesn't handle distrust natively. Extensions that add negative edges (like Guha's T-D approach) can be pathological. Better approach: run EigenTrust on positive trust only (Guha's finding: "trust only" with co-citation is the cleanest for global scoring).

**Implementations (both in Rust!)**:
- `Karma3Labs/rs-eigentrust` — production Rust implementation, used by OpenRank protocol, MIT license. Models attestation credentials as trust edges, runs iterative EigenTrust. Used in Farcaster and Lens social graph scoring. [2024 active]
- `hypnagonia/eigentrust-rust` — lighter Rust impl designed for decentralized networks. 
- `Karma3Labs/go-eigentrust` — Go reference implementation with full test suite.
- `privacy-ethereum/zk-eigentrust` — Rust + Halo2 ZK proof variant (see section 5).
- `Karma3Labs/openrank-sdk` — Python SDK wrapping the EigenTrust API.

---

### 3. SybilRank — Sybil detection via short random walk (Cao et al., 2012)

Stops random walk propagation at `log2(|V|)` steps (not full convergence). Honest-region nodes receive high trust; Sybil-region nodes receive low trust because the Sybil cluster has bottlenecked mixing at the attack edge. Degree-normalized to prevent high-degree Sybil hubs from siphoning trust.

**Why this matters for Styrene**: For detecting Sybil clusters in the endorsement graph before they influence trust scores. Run SybilRank as a *pre-filter* before computing WLC propagation — nodes with SybilRank score below threshold are treated as UNKNOWN regardless of their endorsements. This is the mathematical grounding for the "reciprocity suspicion" signal (a hermetically-sealed cluster of mutual endorsers will score low in SybilRank because the cluster doesn't connect to the broader honest graph).

**Production deployment**: Tribler (Python BitTorrent client) ran this on their real P2P network. Reported 6-9 seconds for full recompute on their deployment — acceptable for background refresh, not real-time.

**Implementation**: Ultipa Graph database has built-in SybilRank. Python: networkx + power iteration is straightforward. Tribler's implementation is on GitHub (Python).

---

### 4. Advogato — max-flow / attack-resistant trust metric (Levien, 2002)

Models trust as network flow capacity. Trust in a node = the maximum flow from the set of "seed" trusted nodes to that node, given edge capacities. **Attack-resistant by design**: an attacker can't get more trust than the capacity of their attack edges (the edges between the Sybil cluster and the honest graph).

**Key property (critical for Styrene)**: Advogato is *non-monotonic* — adding more trust edges can *decrease* trust for a node. This is counter-intuitive but necessary for attack resistance. Levien proved this is a required property for any group trust metric to be attack-resistant.

**Known weakness**: Ruderman (2005) found an attack where "confused" nodes (honest nodes tricked into trusting attackers) amplify the attack quadratically rather than linearly. Still, for small honest-graph sizes (a Styrene mesh is never 130K nodes), this is tractable.

**Implementation**: Levien's original C implementation is public domain. The Advogato website itself ran it. No modern maintained Rust/Python library found, but the algorithm is well-specified in his thesis.

---

### 5. ZK-EigenTrust — privacy-preserving trust via ZK proofs (privacy-ethereum, 2023)

**Repo**: `privacy-ethereum/zk-eigentrust` — Rust + Halo2

Runs EigenTrust inside a zero-knowledge proof circuit. Result: you can prove "my computed EigenTrust score from my trusted peers exceeds threshold T" without revealing *which* peers endorse you, *by how much*, or *who your peers trust*.

**Why this matters for Styrene**: Directly addresses the "privacy of endorsements" open question. A peer can publish a ZK proof that they have sufficient trust in their local graph to be treated at PEER tier — without revealing their social graph. PGP's mistake was making the graph public. ZK-EigenTrust gives you the mathematical guarantee without the privacy leak.

**Caveat**: Halo2 proofs are computationally expensive to generate (seconds to minutes). Acceptable for identity manifest generation (done once, cached) but not for real-time trust computation on every message.

---

### 6. Differential Privacy on Trust Graphs (ITCS 2025)

**Paper**: "Differential Privacy on Trust Graphs", ITCS 2025, arXiv:2410.12045.

Introduces (ε, δ, G)-Trust Graph Differential Privacy: a protocol where each party only trusts a known subset of others with their data, and the privacy guarantee holds against the *complement* of each node's trust neighborhood. Also "Robust TGDP" where even t adversarial trusted neighbors can't compromise the guarantee.

**Why this matters for Styrene**: This is the formal framework for the "partial disclosure" model. Rather than endorsements being fully public (PGP) or fully private (no WoT possible), TGDP gives mathematically bounded privacy leakage. You can tune ε to control how much information about your trust graph leaks from the aggregate computation. This is the answer to the privacy-of-endorsements question — not "public or private" but "differentially private."

---

### 7. DeciTrustNET — graph framework for global + pairwise trust (Ureña et al., 2020)

**Paper**: "DeciTrustNET: A graph based trust and reputation framework for social networks", Information Fusion, 2020.

Extends prior work by computing *both* global reputation (like EigenTrust, how much does the network trust this node) *and* pairwise trust (how much does node A specifically trust node B, beyond just "does A's trusted set endorse B"). Handles temporal dynamics (trust changes over time) and uncertainty (fuzzy membership).

**Why this matters for Styrene**: The distinction between global reputation (useful for hubs and content) and pairwise trust (useful for RBAC and role assignment) is exactly the distinction between our infrastructure trust and identity trust surfaces. DeciTrustNET formalizes both.

---

### 8. GNN-based trust prediction (2019-2024)

Multiple papers apply Graph Neural Networks to predict trust from signed network structure. Key finding: GNNs can learn both local (Appleseed-like) and global (EigenTrust-like) propagation rules from data, outperforming hand-crafted rules on held-out prediction.

**Why this matters for Styrene (cautiously)**: For a future "adaptive" trust engine, GNN inference could tune propagation weights based on observed network behavior rather than hardcoding α=(0.4,0.4,0.1,0.1). However, this requires training data and centralized training infrastructure — not suitable for a mesh-first architecture. Worth noting for the roadmap but not for initial implementation.

**Key paper**: "Graph Neural Networks for Trust Evaluation: Criteria, State-of-the-Art and Future Directions", ResearchGate 2025 (preprint).

## The formal framework

The paper separates two matrices: T (trust) and D (distrust), rather than a single signed spectrum. Distrust is not "negative trust" — it is a different kind of information that interacts with trust under different rules. This validates the Styrene asymmetric treatment.

**Four atomic propagation operators** (Table 2 in the paper):

| Operator | Formula | Meaning |
|---|---|---|
| Direct propagation | B | A trusts B, B trusts C → A likely trusts C |
| Co-citation | B^T B | Multiple trusted sources endorse same peer → stronger signal |
| Transpose trust | B^T | If A trusts B, some reciprocal trust develops |
| Trust coupling | BB^T | A and B trust the same peers → they share a worldview, A should trust B |

Combined: C_{B,α} = α₁B + α₂B^T B + α₃B^T + α₄BB^T, where α is a weight vector. Best empirical weights: α = (0.4, 0.4, 0.1, 0.1).

## Three distrust models tested

1. **Trust-only** (B = T): Ignore distrust. Leaves useful signal on the table; baseline error ~17.7%.
2. **One-step distrust** (B = T, P^k = C^k_{B,α} · (T−D)): Distrust propagates ONE step only — when A distrusts B, A discounts all B's endorsements once. Trust continues to propagate further. **Best performer**: error drops to ~8.2% on balanced set.
3. **Propagated distrust** (B = T−D): Trust and distrust both propagate iteratively. **Pathological**: directed cycles with negative products cause a user to distrust themselves through iterated propagation. Error mixed; generally worse than one-step.

## Key empirical findings

**One-step distrust is the robust recommendation.** From paper §5.1.2: "We can consistently recommend one-step distrust in this case... robust, effective, and easy to compute." Direct propagation (α = e₁ only) is the one situation where distrust "actually hurts, sometimes quite substantially" — i.e., naive direct propagation without the combined operators degrades when distrust is present.

**Distrust is sparse in real systems** (85.3% trust vs. 14.7% distrust in Epinions). This sparsity is load-bearing: the mathematical model's predictive power depends on distrust being the exception, not the norm. Systems that make distrust "free" (no cost, no evidence required) will see the ratio invert, degrading the WoT.

**Majority rounding outperforms global and local rounding.** Predicting a peer's trust from the majority label in their local trusted neighborhood is more accurate than any global statistic. Maps to the Styrene design: "what do my trusted neighbors say about this person" is the right question, not a global score.

**WLC with γ = 0.5 is empirically grounded.** γ is the per-hop discount factor. γ = 0.5 (trust halves per hop) outperforms γ = 0.9 (trust stays nearly constant across hops). This empirically validates the "50% attenuation per hop" depth model we proposed.

**Co-citation is powerful.** When two or more trusted nodes independently endorse the same peer, the signal is significantly stronger than a single endorsement. The B^T B operator captures this. For Styrene: a threshold consensus (multiple independent endorsers) for high-trust levels is mathematically grounded, not just a design choice.

## The "enemy of my enemy" problem — explicitly unresolved in the paper

Section 3.3: "if i distrusts j and j distrusts k, does i trust k?" The paper offers two incompatible interpretations and does not prescribe which is correct. **Recommendation for Styrene: do NOT implement the (distrust→distrust=trust) transitivity rule.** It's empirically weak, philosophically unresolved, and trivially exploited: an attacker gets their Sybil farm to "publicly distrust" legitimate voices, triggering a false trust signal from naive users. One-step distrust only.

## Mapping to Styrene design

| Paper concept | Styrene mapping |
|---|---|
| T matrix | `endorsements[]` in identity manifest |
| D matrix | Tier 1 BLOCK list; Tier 2 advisory |
| One-step distrust | Discounting endorsements from BLOCKED peers by one step before computing trust |
| Co-citation (B^T B) | Multiple independent endorsers required for OPERATOR+ trust threshold |
| WLC γ = 0.5 | Depth attenuation: trust halves per WoT hop (depth 1=full, 2=50%, 3=25%, 4+=<12%) |
| Majority rounding | TUI shows "N of your M trusted contacts also endorse this peer" |
| Distrust sparsity | Evidence requirement for Tier 2 advisories preserves the natural cost of expressing distrust |
