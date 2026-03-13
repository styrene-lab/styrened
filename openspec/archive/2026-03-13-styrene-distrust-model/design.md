# Styrene Distrust Model — Negative Signals, Propagation Boundaries, and Sybil Resistance — Design

## Architecture Decisions

### Decision: One-step distrust model — distrust filters trust signals, never propagates independently

**Status:** decided
**Rationale:** Directly grounded in Guha et al. 2004, the best empirical performer on real WoT data. When node A has BLOCKED node B (Tier 1) or issued/received a Tier 2 advisory about B: B's trust endorsements are discounted once before contributing to A's trust computation. Distrust does not propagate further. Independent trust paths (C endorses X without going through B) are unaffected by A's distrust of B. The alternative — propagated distrust (B = T−D, iterated) — creates pathological self-distrust cycles and is explicitly rejected by the paper. Implementation: when computing a peer's derived trust score, filter the endorsement graph to downweight edges from BLOCKED peers by one step before running the WLC propagation.

### Decision: No enemy-of-my-enemy transitivity — (distrust→distrust) has no transitive meaning

**Status:** decided
**Rationale:** The paper leaves this philosophically unresolved and identifies pathological cases. An attacker can construct Sybil nodes that loudly distrust legitimate voices hoping to trigger false trust signals via double-negation. The rule is not implemented. A's distrust of B, combined with B's distrust of C, tells A nothing about C. The only valid distrust transitivity is the one-step filter: A distrusts B → A discounts B's positive endorsements once. Negative×negative=positive is not modeled.

### Decision: 0.16.0 is a clean break — no compat shims, no deferred migrations

**Status:** decided
**Rationale:** Pre-1.0 software with no external users. All breaking changes ship together in 0.16.0: contacts.peer_hash PK migrated to identity_hash in this release (not deferred). CmdBlockPeerRequest.peer_hash field removed entirely — only identity_hash. No dual-field compat shim. MeshDevice.identity property deleted without deprecation warning. The cost of carrying shims forward in a pre-1.0 codebase exceeds the cost of the breaking change. Do it once, do it cleanly.

### Decision: block-store-canonicalization implemented in v0.16.0

**Status:** decided
**Rationale:** peer_blocks SQLite table is the authoritative runtime block store keyed on identity_hash. contacts table PK migrated from peer_hash to identity_hash. MeshDevice.identity property deleted. IPC breaking changes landed (no shims). Blocks survive restart via _seed_blocks_to_rbac(). LXMF receive path resolves source_hash to identity_hash via NodeStore before RBAC check. Tagged v0.16.0.

## Research Context

### Why distrust is fundamentally harder than trust — and must be treated asymmetrically

The positive trust model has a natural brigade resistance: your endorsement only matters to peers who already trust YOU. A bot farm endorsing each other is useless unless they can infiltrate your trusted set first — and that's already a key compromise problem, not a WoT problem.

**Distrust does not have this natural containment if it propagates.**

Consider: if negative signals accumulate and propagate the same way positive signals do, a coordinated Sybil attack can silence any legitimate voice:
- 1000 bot StyreneIDs all file distrust reports against journalist J
- If those reports propagate and accumulate toward J's trust score, the attack succeeds
- The attacker doesn't need to compromise anyone in J's trusted set — they just need volume

This is not hypothetical. It's the exact attack used in:
- Twitter "report abuse" brigading to silence journalists and dissidents
- Wikipedia edit-war coordinated mass-revert campaigns
- Yelp/App Store review bombing
- Early DNSBL reputation systems that were trivially gamed

**The asymmetry principle: negative signals must never auto-propagate.**

Positive trust propagates (attenuated) because it builds the network's utility. Negative trust must NOT propagate automatically — if it does, the Sybil resistance that protects positive trust (depth attenuation, local primacy) is inverted into a weapon.

This means distrust and trust are NOT symmetric operations. They use different mechanisms, have different propagation rules, and have different resistance properties. Building them symmetrically would be the mistake.

### Three-tier distrust model — scoped by propagation boundary

Distrust operates at three distinct scopes, each with strictly contained propagation:

---

### Revocation of distrust — un-blocking must be as easy as blocking

Every distrust action must have a clear revocation path, otherwise the system accumulates permanent grudges and false positives calcify into permanent blocks.

**Tier 1 (personal BLOCK):** Trivially revocable — operator unblocks in TUI. The block database entry is removed. No cascading effects because the block never propagated. This is the "edit your own mind" operation.

**Tier 2 (advisory warning):** Revocation is a signed retraction sent to the same OPERATOR+ peers who received the original advisory. The retraction is a new signed message:
```json
{
  "type": "distrust-retraction",
  "subject_styrene_id": "...",
  "issuer_styrene_id": "...",
  "original_advisory_timestamp": 1234567890,
  "reason": "resolved / mistaken identity / situation changed",
  "timestamp": 1234567891,
  "signature": "..."
}
```
Recipients who acted on the advisory can choose to revise their Tier 1 block. They are not forced to — their local decision is sovereign. But they receive the updated information.

**Tier 3 (hub ban federation):** Entries have mandatory expiry dates. Renewal is an explicit operator action, not automatic. To un-ban: remove the entry from your list. Partner hubs that imported the entry will see it as expired/removed on their next sync. Explicit revocation can also be sent as a signed "remove entry" update to federated partners.

**The "trust decay" principle:**
Distrust, like trust, should decay over time without renewal. A block that was issued years ago against a peer who has since reformed (or who was mistakenly identified) should not persist indefinitely. Tier 1 blocks are permanent until explicitly removed (by design — you control your own block list). But Tier 2 advisories and Tier 3 ban entries carry expiry timestamps and must be actively renewed to remain in effect. This prevents historical incidents from permanently defining a peer's standing on the network.

### Guha et al. 2004 — empirical grounding for the distrust model

The paper directly addresses the distrust propagation question and provides empirical answers from a real deployed WoT (Epinions, 131K users, 841K edges).

### Codebase audit — Python styrened and Rust styrene-rs as-built state



### Post-validation confirmations — distrust design is sound

The three-tier distrust architecture and its foundational decisions were validated against post-2010 literature:

**One-step distrust confirmed (Guha 2004 finding holds):**
Multiple 2018-2019 papers citing Guha as a baseline confirm that one-step distrust (BLOCK of B discounts B's endorsements before trust computation, never propagates further) outperforms propagated distrust models. The ScienceDirect 2019 paper on signed social networks explicitly notes: "distrust is not transitive — incorporating distrust into propagation models is often impractical or even impossible."

**No enemy-of-my-enemy confirmed:**
The ScienceDirect 2018 paper explicitly validates this: "what if Carol is worse than Bob? Alice would not trust her." The Guha paper leaves the distrust-of-distrust case unresolved; later work confirms treating (distrust → distrust) as no signal is correct. The Sybil attack vector (bots publicly distrusting legitimate voices to inflate them via enemy-of-enemy transitivity) remains a real threat that the "no transitivity" decision closes.

**Distrust sparsity (85.3% trust / 14.7% distrust) confirmed as load-bearing:**
The 2018-2019 literature consistently reproduces this ratio across different signed social network datasets. The evidence requirement for Tier 2 advisories (multiple independent OPERATOR+ issuers required for propagation) directly preserves this property.

**Advisory pull model (manifest-included distrust) confirmed:**
No upstream evidence suggests a push model is required for Phase 1. Including Tier 2 advisories in the identity manifest (fetched on demand, not broadcast) avoids building a new transport layer while maintaining correctness. Push notification is a Phase 2 optimization.

**Revision required from codebase audit:**
The current Contact.blocked field uses LXMF destination hash as primary key, while RBAC uses identity hash. Tier 1 distrust (personal BLOCK) must be anchored to identity hash to work correctly across multiple LXMF aspects of the same peer. The hash bifurcation fix in lxmf_service is a prerequisite for unified Tier 1 enforcement.

## File Changes

- `src/styrened/models/messages.py` (modified) — Add peer_blocks table to init_db(). Add identity_hash column + index migration to contacts table. One-time migration: backfill contacts.identity_hash from NodeStore on startup.
- `src/styrened/services/lxmf_service.py` (modified) — Redesign block_peer(identity_hash, lxmf_dest_hash=None). Redesign unblock_peer(identity_hash). Add _seed_blocks_to_rbac() reading from peer_blocks. Fix _handle_lxmf_message: NodeStore lookup before RBAC check. Add _load_peer_blocks() from new table. Remove _load_blocklist() dead code.
- `src/styrened/ipc/messages.py` (modified) — CmdBlockPeerRequest: add identity_hash field, deprecate peer_hash (compat shim). CmdUnblockPeerRequest: same. QueryBlockedPeers response: return identity_hash + optional lxmf_dest_hash.
- `src/styrened/ipc/handlers.py` (modified) — handle_cmd_block_peer: read identity_hash first, fall back to resolving peer_hash via NodeStore shim. Same for handle_cmd_unblock_peer.
- `src/styrened/ipc/client.py` (modified) — block_peer(identity_hash) and unblock_peer(identity_hash) — parameter rename.
- `src/styrened/ipc/bridge.py` (modified) — block_peer(identity_hash), unblock_peer(identity_hash) — parameter rename.
- `src/styrened/models/mesh_device.py` (modified) — Remove MeshDevice.identity property (legacy alias returning destination_hash). All callers must use .identity_hash or .destination_hash explicitly.
- `src/styrened/tui/screens/conversation.py` (modified) — Block action: use device.identity_hash not device.identity.
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Block action: use peer's identity_hash.

## Constraints

- Canonical block key is rns_identity_hash everywhere. LXMF dest hash is a transport address, not a peer identifier.
- Runtime block_peer() writes ONLY to peer_blocks SQLite table + in-memory RBAC. Never writes to YAML config. YAML rbac.blocked is for static pre-configured operator blocks only.
- contacts.blocked is a denormalized UI hint kept in sync with peer_blocks. peer_blocks is the authoritative block store.
- contacts.peer_hash PK remains as LXMF dest hash in 0.16.0-rc1. Full contacts PK migration to identity_hash deferred to 0.17.0.
- IPC compat shim: CmdBlockPeerRequest accepts both identity_hash (preferred) and peer_hash (deprecated). Handler checks identity_hash first; if empty, resolves peer_hash via NodeStore. Shim removed at 0.17.0.
- Backfill gap: if a peer is in contacts.blocked=1 but not in NodeStore, write peer_blocks with dest hash as best-effort identity key. Block still works at LXMF layer. Entry self-heals on next announce.
- _seed_blocks_to_rbac() reinstated at LXMF init time. Reads peer_blocks table. Merges with static YAML blocks already in RBACPolicy.blocked.
- _handle_lxmf_message: NodeStore.get_identity_for_lxmf_destination(source_lxmf_hash) before RBAC check. Falls back to source_lxmf_hash if NodeStore lookup returns None.
- MeshDevice.identity property removed (not deprecated) — it silently returned destination_hash masquerading as identity_hash, which caused 8 TUI bugs. All callers must use .identity_hash or .destination_hash explicitly.
- Version target: 0.16.0rc1 (PEP 440 pre-release). Tag: v0.16.0rc1. Promote to v0.16.0 after validation.
