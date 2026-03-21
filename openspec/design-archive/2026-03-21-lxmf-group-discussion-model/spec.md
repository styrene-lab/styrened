# LXMF Group Discussion Model — Design Spec (extracted)

> Auto-extracted from docs/lxmf-group-discussion-model.md at decide-time.

## Decisions

### Group threads should be first-class conversation scopes separate from direct identity threads and forum/topic threads (decided)

Identity-centric threading remains correct for direct correspondence, but group chat and forum discussion have different security, membership, and UX semantics. The model should distinguish at least direct threads, private group threads, and forum/topic threads so that participant sets, permissions, visibility, and cryptographic scope are explicit instead of being forced into one peer-thread abstraction.

### Cryptographic isolation should be per group thread with membership epochs (decided)

Privacy and compromise containment require that one room's compromise not expose another room or direct-message history. Each private group thread should therefore have its own cryptographic context and rotation epochs, especially on membership changes. This supports forward secrecy for future room traffic after removals and keeps thread compromise bounded to that room/epoch instead of the whole account.

### Hub-assisted group key exchange is acceptable if the hub is not the long-term plaintext trust anchor (decided)

A Styrene hub can pragmatically help bootstrap group membership and key exchange, particularly on constrained or intermittently connected networks, but room confidentiality should not depend on the hub being honest forever. The hub may assist with enrollment, invitations, and rekey coordination, while actual room traffic remains end-to-end at the room scope and degrades to ordinary LXMF-compatible delivery where richer room semantics are unavailable.

### Use a Signal-style sender-key group model as the initial design reference, adapted to LXMF's asynchronous delivery model (decided)

Signal's group messaging approach is mature, widely scrutinized, and maps well to the stated goals: per-group compromise isolation, efficient group fanout, authenticated senders, and rekey-on-membership-change semantics. Styrene should not blindly copy Signal's exact protocol or assumptions, but it should adopt the same architectural pattern—pairwise-encrypted membership/control messages plus per-group sender-key style message encryption with epochs—as the initial reference design for private LXMF group threads.

### Initial private group-thread lifecycle should use pairwise-encrypted control messages and room-scoped epoch keys (decided)

This gives Styrene a feasible first implementation path that works with LXMF's store-and-forward delivery model. Pairwise-encrypted control traffic handles invites, joins, and rekeys; room messages use room-scoped sender-key style encryption tied to a room id and epoch id. Membership changes rotate the epoch and redistribute fresh room state to the new roster.

### Direct, Group, and Forum should be distinct conversation scope kinds in both UX and state models (decided)

A unified inbox should not mean a flattened conversation ontology. Direct threads are identity-centric, Group threads are room-centric with explicit membership and epochs, and Forum threads are topic-centric and often page-linked. Distinguishing these scope kinds lets the UI unify discussions at the right level while preserving correct security, visibility, and navigation semantics.

### Group invitations should be identity-targeted and transport-unified, with delivery choosing the highest authoritative route available at send time (decided)

A private room is a room-centric object, not a transport-specific fork. Invitations, membership updates, and epoch control messages should target participant identities and use whichever authoritative route is best currently available, while recording delivery-path metadata. This allows a LoRa-only peer to participate in the same room asynchronously, avoids duplicating rooms per transport, and lets the UI show each participant's highest currently available interface without redefining room identity.

### Room UX should expose capability-aware media friction and ask before expensive transfers on constrained paths such as LoRa (decided)

A participant reachable only over low-bandwidth or high-latency paths should still be part of the same room, but the UI must reflect that rich payloads may be costly or impractical. The room model should therefore carry transport capability and delivery-friction metadata per participant and per send path, enabling prompts such as whether to attempt media download over LoRa and allowing all participants to be shown at their highest currently available interface.

### Group rooms remain room-centric across transports, with participants shown at their highest authoritative interface at the moment (decided)

The same participant may be reachable through different interfaces over time, and different participants in one room may have very different path quality. The room should not fork by transport. Instead, the UI and state model should preserve one room identity and show each member's best currently authoritative route, fallback paths, and any delivery/media constraints. This keeps invitation, membership, and epoch semantics coherent while still exposing operational reality.

### Group-thread storage and richer features should be tiered, with hardware-informed first-run defaults and explicit operator override (decided)

Constrained devices should not be forced into a full-featured room implementation by default if that risks storage, RAM, CPU, or link exhaustion. A feature/storage tier can pick a safe initial profile based on authoritative local hardware signals, but it must remain operator-visible and overrideable. Degradation should reduce conveniences like deep retained history, automatic media fetch, and aggressive background catch-up while preserving room identity, membership semantics, and basic asynchronous participation.

## Research Summary

### Current LXMF group-discussion landscape

Current upstream signals still suggest there is no widely adopted, canonical LXMF native group-chat standard on par with one-to-one messaging. Upstream LXMF documentation explicitly says distributed discussion/news-groups and bulletins can be built using LXMF fields plus propagation nodes, but this remains more of a protocol possibility than a universal end-user room model. Recent Reticulum discussion threads also still describe fully distributed native group messaging as a future plan, while po…

### Security and privacy constraints for group threading

A group-thread model should minimize blast radius: compromise of one room should not expose direct-message history or other rooms, and membership changes should not silently preserve access to future traffic. This argues against a single long-lived account-wide group secret and toward per-thread cryptographic context with explicit room identity, membership epoching, and sender-authenticated envelopes. Group threading therefore needs both a conversation-scope model (direct vs group vs forum/topic…

### Styrene hub as assisted key-exchange, not message trust anchor

Using a Styrene hub for group key exchange can be useful, but the hub should be treated as an enrollment and distribution assistant rather than the permanent trust anchor for message confidentiality. A good model is hub-assisted pairwise introduction and distribution of a per-group shared secret or sender-key state, after which regular group messages remain end-to-end within the room scope. This preserves sideways compatibility with plain LXMF delivery semantics while avoiding a design where the…

### Signal-style group messaging as a reference pattern

Signal's well-proven group messaging lineage is a strong reference example for Styrene: pairwise trust relationships bootstrap group membership, while sender-key style room state gives efficient fanout for group messages without requiring a central plaintext relay. The appealing properties are practical end-to-end encryption, sender authentication, per-group compromise isolation, and a separation between membership/change control and day-to-day message encryption. For Styrene, this suggests usin…

### Proposed room lifecycle for Signal-style LXMF groups

A practical first lifecycle for private LXMF group threads is: (1) Create room — creator generates room identity, room metadata, initial epoch, and sender-key package; (2) Invite member — creator or authorized member sends a pairwise-encrypted invitation carrying room metadata, membership policy, and bootstrap material or a pointer for hub-assisted retrieval; (3) Join/accept — recipient acknowledges acceptance and proves possession of their pairwise identity/channel, allowing the room roster to …

### Conversation-scope model for direct, group, and forum threads

The UI and protocol model should distinguish at least three conversation scopes: Direct threads (identity-centric, one peer or one operator endpoint), Group threads (private multi-party rooms with explicit room id, membership roster, and epoch state), and Forum/topic threads (page or board-linked discussions whose anchor is a topic id or page/thread identity rather than a private room roster). Direct and Group can both appear under Mail or Comms depending on async/live behavior, but forum/topic …

### Group invitations and room participation should be transport-unified but capability-aware

A room invitation should target the participant identity and group thread, not a single transport silo. The transport layer used to deliver invitation and control packets should be selected from the best currently available authoritative route for that identity, while preserving the room as the same room across transports. A peer reachable only over LoRa/RNS should still see the same group thread and be able to participate asynchronously, but the UX should surface that this path is constrained: …
