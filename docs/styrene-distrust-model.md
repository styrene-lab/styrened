---
id: styrene-distrust-model
title: Styrene Distrust Model — Negative Signals, Propagation Boundaries, and Sybil Resistance
status: implemented
parent: styrene-trust-model
open_questions: []
branches: ["feature/styrene-distrust-model"]
openspec_change: styrene-distrust-model
---

# Styrene Distrust Model — Negative Signals, Propagation Boundaries, and Sybil Resistance

## Overview

> Parent: [Styrene Trust Model — Web of Trust, Attestations, and Sybil Resistance](styrene-trust-model.md)
> Spawned from: "Distrust and negative signals: how does a user mark a peer, hub, or piece of content as untrustworthy, and how is that signal scoped to prevent bot-brigading and Sybil silencing attacks targeting legitimate users?"

*To be explored.*

## Research

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

## Decisions

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

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/models/messages.py` (modified) — Add peer_blocks table to init_db(). Add identity_hash column + index migration to contacts table. One-time migration: backfill contacts.identity_hash from NodeStore on startup.
- `src/styrened/services/lxmf_service.py` (modified) — Redesign block_peer(identity_hash, lxmf_dest_hash=None). Redesign unblock_peer(identity_hash). Add _seed_blocks_to_rbac() reading from peer_blocks. Fix _handle_lxmf_message: NodeStore lookup before RBAC check. Add _load_peer_blocks() from new table. Remove _load_blocklist() dead code.
- `src/styrened/ipc/messages.py` (modified) — CmdBlockPeerRequest: add identity_hash field, deprecate peer_hash (compat shim). CmdUnblockPeerRequest: same. QueryBlockedPeers response: return identity_hash + optional lxmf_dest_hash.
- `src/styrened/ipc/handlers.py` (modified) — handle_cmd_block_peer: read identity_hash first, fall back to resolving peer_hash via NodeStore shim. Same for handle_cmd_unblock_peer.
- `src/styrened/ipc/client.py` (modified) — block_peer(identity_hash) and unblock_peer(identity_hash) — parameter rename.
- `src/styrened/ipc/bridge.py` (modified) — block_peer(identity_hash), unblock_peer(identity_hash) — parameter rename.
- `src/styrened/models/mesh_device.py` (modified) — Remove MeshDevice.identity property (legacy alias returning destination_hash). All callers must use .identity_hash or .destination_hash explicitly.
- `src/styrened/tui/screens/conversation.py` (modified) — Block action: use device.identity_hash not device.identity.
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Block action: use peer's identity_hash.
- `src/styrened/daemon.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `openspec/changes/styrene-distrust-model/tasks.md` (modified) — Post-assess reconciliation delta — touched during follow-up fixes

### Constraints

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

## Python styrened — what exists for trust/block today

### RBAC policy (models/rbac.py)
- Full `RBACPolicy` with Role hierarchy: BLOCKED < NONE < PEER < MONITOR < OPERATOR < ADMIN
- Capability strings (chat.send, rpc.exec, terminal.full, vpn.handshake, etc.)
- `RosterEntry(identity_hash, role, label, grants)` — keyed on RNS **identity_hash** (32-char hex)
- `RBACPolicy.blocked` — list of identity hash prefixes (prefix-match)
- `block()` / `unblock()` / `resolve_role()` / `has_capability()` — full CRUD
- Config-based: the `rbac.roster` YAML section populates this at startup

### Contacts model (models/contacts.py)
- `Contact(peer_hash, alias, notes, blocked, blocked_at)` — keyed on LXMF **destination hash**
- `Contact.blocked = True` is the "social block" (messaging layer)

### block_peer() in lxmf_service.py — the key inconsistency
- `block_peer(peer_hash)` does TWO things:
  1. Sets `Contact.blocked = True` in SQLite (keyed on LXMF destination hash)
  2. Calls `self._rbac_policy.block(peer_hash)` — inserting the **LXMF destination hash** into the RBAC blocked list (which is documented to take identity hashes)
- The LXMF receive handler checks: `self._rbac_policy.resolve_role(source_hash)` where `source_hash = message.source_hash.hex()` — this IS an LXMF destination hash
- So block_peer() is internally consistent within the LXMF layer: both insert and check use destination hash. The block actually works for LXMF message gating.

### The hash bifurcation bug
- Config-based RBAC roster: keyed on identity hash → works for RPC server, terminal, web auth, TUI dashboard
- Runtime block_peer(): uses destination hash → works ONLY for LXMF message gating
- Cross-layer mismatch: if you config-roster-block an identity hash, their LXMF messages are NOT blocked (destination hash ≠ identity hash). If you block_peer() a destination hash, it doesn't show as BLOCKED in the TUI dashboard (which checks identity hash via RBAC).
- The NodeStore has the resolution mapping (destination → identity) but lxmf_service doesn't use it

### "in_my_mesh" definition today
- Dashboard: `rbac.resolve_role(device.identity_hash) >= Role.PEER`
- So "trusted" = any peer with an explicit PEER+ roster entry
- No continuous score, no endorsement graph, no WoT — just flat RBAC role assignment

### No trust scoring infrastructure
- Zero Appleseed, EigenTrust, SybilRank, or WoT propagation
- Zero endorsement storage
- Zero manifest parsing
- Zero advisory distribution

## Rust styrene-rs — what exists

### Zero authorization enforcement
- `identity_store.rs`: load/create PrivateIdentity from file — no RBAC
- `config.rs`: only interface configs — no roster section
- No contact storage, no block list, no capability checking
- Any LXMF message from any source is processed without authorization

### Wire protocol gaps for trust
- `StyreneMessageType` enum has these unallocated ranges: 0x80-0x9F (hub services), 0xE0-0xFE (app-specific)
- No manifest request/response types
- No advisory publish/retract types
- No trust snapshot types
- The CBOR migration (msgpack → CBOR in styrene-mesh) is already planned and affects where trust messages should be designed

### SDK capabilities (sdk_capabilities.rs)
- These are RPC/SDK session negotiation capabilities (e.g., "sdk.capability.topics")
- Orthogonal to mesh RBAC — these govern what RPC methods the daemon exposes to local SDK clients
- `sdk.capability.contact_management` and `sdk.capability.identity_discovery` are relevant but describe SDK features, not mesh trust

## What this means for the trust model

### The trust model design is additive — no conflicts with existing code
The existing RBAC system is the output binding point for trust scores:
- Trust score → TUI display of Appleseed score
- Trust score above operator-set threshold → TUI suggests role assignment
- Operator explicitly assigns role → RBAC roster entry
- RBAC roster → all enforcement (message gating, RPC caps, terminal, web)
The trust engine doesn't need to touch RBAC enforcement — it feeds suggestions into the UI.

### The hash bifurcation must be fixed before trust can be the source of truth
Until lxmf_service resolves destination → identity before RBAC checks, RBAC-level trust enforcement won't work end-to-end. The fix is: use NodeStore to map `message.source_hash` → identity hash before `resolve_role()`. This is a pre-requisite, not a trust feature.

### Rust RBAC port is the first Rust trust deliverable
Before Layer 1 (Appleseed) can be enforced in the Rust daemon, it needs an RBAC policy port. The Python RBACPolicy is pure functional (HashMap + enum), highly portable to Rust. Priority: port RBACPolicy as `styrene-mesh`'s authorization contract (or a new `styrene-auth` crate).

## What the paper says about distrust propagation

**One-step distrust is the empirically best model.** When A distrusts B, the correct computation is: discount all of B's trust endorsements by one step before applying them to A's worldview. Distrust does NOT propagate further. This has two important consequences for Styrene:

1. **Distrust is a filter on trust signals, not an independent propagating quantity.** You BLOCK B → B's endorsements of C, D, E are discounted once. If C endorses X independently (not through B), A's trust in X is unaffected by A's distrust of B.

2. **Propagated distrust is pathological.** Treating B = T−D and iterating leads to self-distrust cycles. The paper explicitly identifies this as a failure mode. Do not build a system that iteratively propagates distrust.

## The Sybil/brigading argument from the mathematics

The "one-step distrust is best" finding has a direct Sybil implication:

A bot farm that issues distrust signals against journalist J cannot make other nodes distrust J through propagation — distrust stops at one step. For the bot distrust to affect peer A:
1. A must have explicitly trusted a bot (put it in A's T matrix)
2. That bot must issue distrust toward J
3. A's trust in J is then discounted once — not zeroed, just reduced

For this attack to succeed, the bots need to already BE in A's trusted set. At that point, A has a key-compromise/social-engineering problem, not a WoT problem.

**The evidence requirement for Tier 2 advisories maps directly to the paper's finding about distrust sparsity.** In Epinions, 85.3% of edges are trust and only 14.7% are distrust. The model's predictive power assumes distrust is the exception. Making distrust expensive (evidence required) preserves this ratio property and keeps the WoT predictive.

## The "enemy of my enemy" rule is empirically rejected for Styrene

The paper leaves (distrust→distrust) transitivity unresolved, but explicitly notes the pathological cases. For Styrene: do NOT implement this rule. An attacker can trivially exploit it:
1. Create Sybil bot S
2. Have S publicly distrust all legitimate voices (J₁, J₂, J₃...)
3. Hope that naive users interpret "S distrusts J" as evidence in J's favor — but only if the "enemy of my enemy" rule is active

This attack is incoherent (you'd need to trust S's judgment to use S's distrust as a signal), but it creates confusion. The cleanest design: (distrust→distrust) has no transitive meaning. A's distrust of B, combined with B's distrust of C, says nothing about A's view of C.

## Tier 1: Personal BLOCK — local only, never propagates

Already implemented as RBAC BLOCKED. Operator says "I will not receive from or respond to this StyreneID."

- **Scope**: your node only
- **Propagation**: zero — nobody else ever learns about your block
- **Brigade resistance**: perfect — a Sybil farm cannot use your blocks against anyone because they never leave your node
- **Revocation**: trivial — unblock in the TUI
- **False positive recovery**: easy — only you were affected
- **Applies to**: peers, specific hubs (stop routing through this hub), specific content sources

This is the primary and default distrust mechanism. It covers 99% of cases.

---

## Tier 2: Advisory warning to explicitly-trusted peers — explicit, not forwarded

When an operator observes genuinely malicious behavior (coordinated spam, attempted exploits, impersonation), they can issue a signed advisory warning to peers they hold at OPERATOR+ trust level.

Structure:
```json
{
  "type": "distrust-advisory",
  "subject_styrene_id": "...",          // who the warning is about
  "issuer_styrene_id": "...",           // your identity
  "severity": "warning|serious|critical",
  "evidence": [                          // REQUIRED — see below
    { "type": "lxmf-headers", "data": "..." },
    { "type": "exploit-attempt", "log": "..." }
  ],
  "timestamp": 1234567890,
  "signature": "...",                    // signed by your StyreneID
  "forward": false                       // MUST be false; recipients MUST NOT re-broadcast
}
```

**The `forward: false` contract is protocol-level, not just advisory.**
Recipients of a Tier 2 advisory MUST NOT automatically forward it. If a recipient chooses to act on it (add their own block), that is a local decision using Tier 1. The advisory terminates at the first hop. This is enforced by:
- The `forward: false` field being checked and rejected if set otherwise
- The advisory being encrypted to the specific recipient's StyreneID (not broadcast)
- The protocol explicitly rejecting any advisory that was received forwarded

**Evidence requirement — this is the core Sybil resistance:**
A Tier 2 advisory with no evidence field has zero weight. Recipients are expected to examine the evidence before acting. Evidence types:
- LXMF message headers (signed, showing spam pattern)
- Exploit attempt logs with timestamps (unambiguous malicious behavior)
- Impersonation proof (showing two manifests with conflicting identity claims)

The evidence must be cryptographically verifiable by the recipient independently. "I don't like this person" is not evidence. A signed message flood with source StyreneID matching the subject IS evidence.

**Brigade resistance**: A Sybil farm cannot:
- Send advisories to your trusted peers → they don't have OPERATOR+ trust relationships with your peers
- Flood you with advisories → you only accept advisories from your OPERATOR+ trusted set
- Fabricate signed evidence → LXMF headers and signed logs can't be forged

---

## Tier 3: Hub ban list — infrastructure-level, opt-in federation

Hub operators maintain a local ban list (StyreneIDs banned from their hub). This is a Tier 1 block at the infrastructure level. It is local by default.

**Optional federation between hub operators:**
- Hub A's operator publishes their ban list as a signed document (timestamped, with evidence references)
- Hub B's operator, who trusts Hub A's operator at OPERATOR+ level, can explicitly import Hub A's list
- Import is a manual operator action — never automatic
- Hub B can override any entry from Hub A's list (local primacy always wins)
- Imported entries carry an attribution: "banned by Hub A operator, imported by Hub B"

This is the model used by email spam filtering (Spamhaus, etc.) — trusted organizations share lists with their partners. It works because:
1. You choose whose list you import (trust-gated)
2. The import is explicit and auditable
3. You can override any entry
4. If the list maintainer is compromised, you stop importing their list

**Expiry is mandatory:** Hub ban list entries have required timestamps and expiry dates. An operator cannot issue a permanent network-wide ban through federation — entries must be periodically renewed. Stale entries auto-expire. This prevents historical grievances from becoming permanent infrastructure blocks.
